import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool

from .config import ROOT, Config
from .db import CapturedImage, Detection, DetectionModel, ProcessingJob, RuntimeSettings, connect, now, uid
from .demo import seed_demo
from .deletion import delete_rejected_photos
from .engine import EngineRegistry
from .ingestion import decode_image, predict_frame, process_video, save_frame
from .metadata import live_frame_timestamp, read_telemetry, supplied
from .schemas import IngestEnvelope, Metadata, ModelRegistration, RejectedPhotoDeletion, SettingsUpdate
from .streams import router as streams_router

logger = logging.getLogger(__name__)


from .presentation import detection_data


def job_data(job):
    return {column.name: getattr(job, column.name) for column in job.__table__.columns}


def settings_data(settings):
    return {"active_model_id": settings.active_model_id, "confidence_threshold": settings.confidence_threshold,
            "frame_interval_seconds": settings.frame_interval_seconds, "max_frames": settings.max_frames,
            "auto_accept_enabled": settings.auto_accept_enabled, "auto_accept_threshold": settings.auto_accept_threshold}


def create_app(config: Config | None = None):
    config = config or Config()
    storage = config.storage
    engine, sessions = connect(storage)
    (storage / "media").mkdir(exist_ok=True)
    (storage / "videos").mkdir(exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        with sessions() as session:
            if not session.get(RuntimeSettings, 1):
                session.add(RuntimeSettings(id=1))
                session.commit()
            # Background jobs are local and in-process. Never misreport them as running after a restart.
            session.execute(update(ProcessingJob).where(ProcessingJob.status.in_(["queued", "processing"])).values(
                status="failed", error="Server restarted before processing finished. Already-created detections are preserved; upload again to start a new job.", finished_at=now()))
            session.commit()
            if config.seed_demo:
                seed_demo(session, storage)
        yield
        engine.dispose()

    app = FastAPI(title="Asian Baddies · Turtle Survey API", version="1.0.0", lifespan=lifespan)
    app.state.config, app.state.storage, app.state.sessions = config, storage, sessions
    app.state.registry = EngineRegistry()
    app.include_router(streams_router)
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins, allow_methods=["GET", "POST", "PUT"], allow_headers=["*"])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_, exc):
        return JSONResponse({"error": {"message": str(exc.detail), "code": exc.status_code}}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        details = [{"field": ".".join(str(x) for x in error["loc"]), "message": error["msg"]} for error in exc.errors()]
        return JSONResponse({"error": {"message": "Check the supplied fields.", "details": details, "code": 422}}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_, exc):
        logger.exception("Unexpected API error", exc_info=exc)
        return JSONResponse({"error": {"message": "The request could not be completed. Check the server log.", "code": 500}}, status_code=500)

    def db():
        with sessions() as session:
            yield session

    def selection(session):
        try:
            return app.state.registry.select(session, session.get(RuntimeSettings, 1))
        except Exception as exc:
            raise HTTPException(422, f"Cannot load detection engine: {exc}") from exc

    def parse_metadata(value):
        try:
            return Metadata.model_validate_json(value)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, f"Invalid capture metadata: {exc}") from exc

    async def read_limited(file, max_bytes):
        chunks, size = [], 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if max_bytes and size > max_bytes:
                raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
            chunks.append(chunk)
        if not size:
            raise HTTPException(422, "The uploaded file is empty.")
        return b"".join(chunks)

    @app.get("/api/health")
    def health():
        return {"data": {"status": "ok", "drone_connected": False, "source_mode": "recorded-media", "paid_services": False}}

    @app.get("/api/detections")
    def detections(status: str | None = None, limit: int = Query(1000, ge=1, le=1000), offset: int = Query(0, ge=0), session=Depends(db)):
        statement = select(Detection).options(joinedload(Detection.image))
        count = select(func.count()).select_from(Detection)
        if status:
            if status not in {"pending", "verified", "rejected"}:
                raise HTTPException(422, "Status must be pending, verified or rejected.")
            statement, count = statement.where(Detection.status == status), count.where(Detection.status == status)
        records = session.scalars(statement.order_by(Detection.created_at.desc(), Detection.id).offset(offset).limit(limit)).all()
        return {"data": [detection_data(record) for record in records], "total": session.scalar(count), "offset": offset, "limit": limit}

    @app.get("/api/detections/{detection_id}")
    def detection(detection_id: str, session=Depends(db)):
        record = session.get(Detection, detection_id)
        if record is None:
            raise HTTPException(404, "Detection not found.")
        return {"data": detection_data(record)}

    def review(detection_id, target, session):
        expected = ["verified", "rejected"] if target == "pending" else ["pending"]
        result = session.execute(update(Detection).where(Detection.id == detection_id, Detection.status.in_(expected)).values(
            status=target, reviewed_at=None if target == "pending" else now(),
            review_method=None if target == "pending" else "human", auto_accept_threshold=None))
        if result.rowcount == 0:
            session.rollback()
            if not session.get(Detection, detection_id):
                raise HTTPException(404, "Detection not found.")
            raise HTTPException(409, "This detection has already changed status. Return it to pending before reviewing it again.")
        session.commit()
        session.expire_all()
        return {"data": detection_data(session.get(Detection, detection_id))}

    @app.post("/api/detections/{detection_id}/verify")
    def verify(detection_id: str, session=Depends(db)):
        return review(detection_id, "verified", session)

    @app.post("/api/detections/{detection_id}/reject")
    def reject(detection_id: str, session=Depends(db)):
        return review(detection_id, "rejected", session)

    @app.post("/api/detections/{detection_id}/reset")
    def reset(detection_id: str, session=Depends(db)):
        return review(detection_id, "pending", session)

    @app.post("/api/images/delete-rejected")
    def delete_rejected(payload: RejectedPhotoDeletion, session=Depends(db)):
        return {"data": delete_rejected_photos(session, storage, payload.image_ids)}

    @app.get("/api/sightings")
    def sightings(limit: int = Query(1000, ge=1, le=1000), offset: int = Query(0, ge=0), session=Depends(db)):
        return detections("verified", limit, offset, session)

    @app.get("/api/stats")
    def stats(session=Depends(db)):
        counts = dict(session.execute(select(Detection.status, func.count()).group_by(Detection.status)).all())
        latest = session.scalar(select(Detection).join(CapturedImage).where(Detection.status == "verified", CapturedImage.captured_at.is_not(None))
                                .order_by(func.julianday(CapturedImage.captured_at).desc()).limit(1))
        return {"data": {"total": sum(counts.values()), "pending": counts.get("pending", 0), "verified": counts.get("verified", 0),
                         "rejected": counts.get("rejected", 0), "average_confidence": session.scalar(select(func.avg(Detection.confidence))) or 0,
                         "latest_sighting": detection_data(latest) if latest else None,
                         "images": session.scalar(select(func.count()).select_from(CapturedImage)),
                         "mock_detections": session.scalar(select(func.count()).select_from(Detection).where(Detection.is_mock.is_(True)))}}

    @app.get("/api/settings")
    def get_settings(session=Depends(db)):
        return {"data": settings_data(session.get(RuntimeSettings, 1))}

    @app.put("/api/settings")
    def put_settings(payload: SettingsUpdate, session=Depends(db)):
        current = session.get(RuntimeSettings, 1)
        # Old clients may omit the added fields. Preserve stored values rather
        # than silently resetting an opt-in policy while saving another setting.
        values = settings_data(current) | payload.model_dump(exclude_unset=True)
        if values["auto_accept_enabled"] and values["auto_accept_threshold"] < values["confidence_threshold"]:
            raise HTTPException(422, "Automatic acceptance confidence must be at least the detection confidence threshold.")
        if payload.active_model_id != "demo":
            try:
                app.state.registry.select(session, payload)
            except Exception as exc:
                raise HTTPException(422, f"Cannot activate this model: {exc}") from exc
        for key, value in values.items():
            setattr(current, key, value)
        session.commit()
        return {"data": settings_data(current)}

    @app.get("/api/models")
    def models(session=Depends(db)):
        result = [{"id": "demo", "name": "Demo simulator", "kind": "demo", "available": True, "path": None, "labels": ["turtle"]}]
        for model in session.scalars(select(DetectionModel).order_by(DetectionModel.created_at.desc())):
            result.append({"id": model.id, "name": model.name, "kind": "yolo", "path": model.path, "labels": model.labels,
                           "available": Path(model.path).is_file()})
        return {"data": result}

    @app.post("/api/models", status_code=201)
    def register_model(payload: ModelRegistration, session=Depends(db)):
        path = Path(payload.path).expanduser()
        path = (ROOT / path if not path.is_absolute() else path).resolve()
        if not path.is_file() or path.suffix.lower() != ".pt":
            raise HTTPException(422, "Provide the path to an existing .pt file on the backend computer.")
        model = DetectionModel(name=payload.name.strip(), path=str(path), labels=[x.strip() for x in payload.labels if x.strip()])
        session.add(model)
        session.commit()
        return {"data": {"id": model.id, "name": model.name, "path": model.path, "labels": model.labels}}

    @app.post("/api/upload", status_code=201)
    async def upload(file: UploadFile = File(...), metadata: str = Form("{}"), session=Depends(db)):
        manual = parse_metadata(metadata)
        active = await run_in_threadpool(selection, session)
        content = await read_limited(file, min(config.max_upload_mb, 50) * 1024 * 1024)
        try:
            image, embedded = await run_in_threadpool(decode_image, content)
            record, created = await run_in_threadpool(save_frame, session, storage, image, Path(file.filename or "image").name, "manual-upload",
                                                      embedded.apply(supplied(manual)), selection=active, original_bytes=content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"data": {"image_id": record.id, "detections": [detection_data(x) for x in created], "metadata": record.metadata_info,
                         "is_mock": active.is_mock, "message": f"Created {len(created)} review candidates."}}

    @app.post("/api/ingest/frame", status_code=201)
    async def ingest_frame(file: UploadFile = File(...), envelope: str = Form("{}"), x_ingest_token: str | None = Header(None), session=Depends(db)):
        if config.ingest_token and not secrets.compare_digest(x_ingest_token or "", config.ingest_token):
            raise HTTPException(401, "A valid X-Ingest-Token is required.")
        try:
            payload = IngestEnvelope.model_validate_json(envelope)
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid ingestion envelope: {exc}") from exc
        active = await run_in_threadpool(selection, session) if payload.detections is None else None
        content = await read_limited(file, min(config.max_upload_mb, 50) * 1024 * 1024)
        try:
            image, embedded = await run_in_threadpool(decode_image, content)
            capture = live_frame_timestamp(embedded.apply(supplied(payload.metadata, "upstream source")), payload.frame_captured_at)
            record, created = await run_in_threadpool(save_frame, session, storage, image, Path(file.filename or "frame.jpg").name, payload.source,
                                                      capture, selection=active, candidates=payload.detections,
                                                      model_id=payload.model_id, model_name=payload.model_name, is_mock=payload.is_mock, original_bytes=content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"data": {"image_id": record.id, "detections": [detection_data(x) for x in created], "metadata": record.metadata_info}}

    @app.post("/api/inference/frame")
    async def inference_frame(file: UploadFile = File(...), envelope: str = Form("{}"), persist_candidates: bool = Form(False),
                              x_ingest_token: str | None = Header(None), session=Depends(db)):
        """Infer transient viewer frames, saving candidate frames only on opt-in."""
        if config.ingest_token and not secrets.compare_digest(x_ingest_token or "", config.ingest_token):
            raise HTTPException(401, "A valid X-Ingest-Token is required.")
        try:
            payload = IngestEnvelope.model_validate_json(envelope)
        except ValidationError as exc:
            raise HTTPException(422, f"Invalid ingestion envelope: {exc}") from exc
        if payload.detections is not None:
            raise HTTPException(422, "Live inference runs the active local model; omit upstream detections.")
        active = await run_in_threadpool(selection, session)
        content = await read_limited(file, min(config.max_upload_mb, 50) * 1024 * 1024)
        try:
            image, embedded = await run_in_threadpool(decode_image, content)
            started = perf_counter()
            candidates = await run_in_threadpool(predict_frame, image, active)
            inference_ms = (perf_counter() - started) * 1000
            capture = live_frame_timestamp(embedded.apply(supplied(payload.metadata, "upstream source")), payload.frame_captured_at)
            record = None
            if persist_candidates and candidates:
                record, created = await run_in_threadpool(save_frame, session, storage, image, Path(file.filename or "frame.jpg").name,
                                                          payload.source, capture, selection=active, predicted=candidates, original_bytes=content)
                result = [detection_data(item) for item in created]
            else:
                result = [candidate.model_dump() | {"id": None, "status": None, "review_method": None,
                                                    "auto_accept_threshold": None, "is_mock": active.is_mock} for candidate in candidates]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"data": {"width": image.width, "height": image.height, "detections": result,
                         "model_id": active.model_id, "model_name": active.model_name, "is_mock": active.is_mock,
                         "inference_ms": round(inference_ms, 2), "image_id": record.id if record else None,
                         "metadata": record.metadata_info if record else capture.info()}}

    @app.post("/api/upload/video", status_code=202)
    async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...), metadata: str = Form("{}"),
                           telemetry: UploadFile | None = File(None), frame_interval_seconds: float | None = Form(None),
                           max_frames: int | None = Form(None), session=Depends(db)):
        manual = parse_metadata(metadata)
        settings = session.get(RuntimeSettings, 1)
        interval = frame_interval_seconds if frame_interval_seconds is not None else settings.frame_interval_seconds
        limit = max_frames if max_frames is not None else settings.max_frames
        if not 0.25 <= interval <= 3600 or not 1 <= limit <= 1000:
            raise HTTPException(422, "Frame interval must be 0.25–3600 seconds and maximum frames 1–1000.")
        if Path(file.filename or "").suffix.lower() not in {".mp4", ".mov", ".avi", ".mkv"}:
            raise HTTPException(422, "Upload an MP4, MOV, AVI or MKV recording.")
        points = []
        if telemetry and telemetry.filename:
            try:
                points = read_telemetry(await read_limited(telemetry, 10 * 1024 * 1024), telemetry.filename)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        active = await run_in_threadpool(selection, session)
        job_id = uid()
        path = storage / "videos" / f"{job_id}{Path(file.filename).suffix.lower()}"
        size = 0
        try:
            with path.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if config.max_upload_mb and size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"Video exceeds the {config.max_upload_mb} MB limit.")
                    output.write(chunk)
            if not size:
                raise HTTPException(422, "The video file is empty.")
            job = ProcessingJob(id=job_id, filename=Path(file.filename).name, settings_snapshot={"model_id": active.model_id,
                                "model_name": active.model_name, "confidence_threshold": active.threshold, "is_mock": active.is_mock,
                                "auto_accept_enabled": active.auto_accept_enabled, "auto_accept_threshold": active.auto_accept_threshold,
                                "frame_interval_seconds": interval, "max_frames": limit, "telemetry_records": len(points)})
            session.add(job)
            session.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        background_tasks.add_task(process_video, app, job_id, path, manual, points, active, interval, limit)
        return {"data": job_data(job)}

    @app.get("/api/jobs")
    def jobs(session=Depends(db)):
        return {"data": [job_data(job) for job in session.scalars(select(ProcessingJob).order_by(ProcessingJob.created_at.desc()).limit(50))]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, session=Depends(db)):
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise HTTPException(404, "Processing job not found.")
        return {"data": job_data(job)}

    app.mount("/media", StaticFiles(directory=storage / "media"), name="media")
    frontend = ROOT / "frontend" / "dist-legacy"
    if frontend.is_dir():
        class SPA(StaticFiles):
            async def get_response(self, path, scope):
                route_path = path.replace("\\", "/").lstrip("/")
                if route_path == "api" or route_path.startswith("api/"):
                    raise HTTPException(404, "API route not found.")
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if exc.status_code != 404 or Path(path).suffix:
                        raise
                    return FileResponse(frontend / "index.html")
        app.mount("/", SPA(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
