"""Public production entrypoint. Run one Uvicorn process; workers are bounded internally."""
import hashlib
import hmac
import logging
import secrets
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from sqlalchemy import delete, func, select, update
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

from .config import ROOT
from .db import CapturedImage, Detection, ProcessingJob, connect, now, uid
from .deletion import delete_rejected_photos
from .ingestion import decode_image
from .presentation import detection_data
from .public_config import PublicConfig
from .public_processing import Processor, load_selection, video_properties
from .public_store import Submission
from .schemas import Metadata, RejectedPhotoDeletion

log = logging.getLogger(__name__)


class BodyTooLarge(MultiPartException):
    pass


class PublicBoundary:
    """Limit before Starlette multipart spooling; never trust forwarded headers here."""
    def __init__(self, app, config):
        self.app, self.config = app, config
        self.clients = OrderedDict()
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        limit = (self.config.max_upload_mb + 1) * 1024 ** 2 if self.config.max_upload_mb else 0
        async def error(code, message):
            await JSONResponse({"error": {"message": message}}, status_code=code)(scope, receive, send)
        try:
            if limit and int(headers.get(b"content-length", b"0")) > limit:
                return await error(413, "Request body exceeds the upload limit.")
        except ValueError:
            return await error(400, "Invalid content length.")
        if self.config.requests_per_minute and scope["path"].startswith("/api/"):
            client, stamp = (scope.get("client") or ("unknown",))[0], monotonic()
            with self.lock:
                count, start = self.clients.pop(client, (0, stamp))
                if stamp - start >= 60:
                    count, start = 0, stamp
                self.clients[client] = (count + 1, start)
                while len(self.clients) > 10000:
                    self.clients.popitem(last=False)
            if count >= self.config.requests_per_minute:
                return await error(429, "Request rate exceeded. Try again in one minute.")
        size = 0
        too_large = False
        async def limited_receive():
            nonlocal size, too_large
            message = await receive()
            size += len(message.get("body", b""))
            if limit and size > limit:
                too_large = True
                raise BodyTooLarge("Request body exceeds the upload limit.")
            return message
        async def secure_send(message):
            if too_large:
                return
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
                    (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"default-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")]
            await send(message)
        try:
            await self.app(scope, limited_receive, secure_send)
            if too_large:
                await error(413, "Request body exceeds the upload limit.")
        except BodyTooLarge:
            await error(413, "Request body exceeds the upload limit.")


def image_data(image):
    return {"id": image.id, "filename": image.filename, "width": image.width, "height": image.height,
            "original_url": f"/media/{image.original_image_path}", "annotated_url": f"/media/{image.id}/annotated.jpg",
            "uploaded_at": image.uploaded_at, "captured_at": image.captured_at,
            "latitude": image.latitude, "longitude": image.longitude, "metadata": image.metadata_info,
            "detections": [detection_data(x) for x in image.detections]}


def job_data(job):
    return {key: getattr(job, key) for key in ["id", "filename", "status", "processed_frames", "total_frames", "detections_created",
            "error", "warnings", "settings_snapshot", "created_at", "finished_at"]}


def create_app(config=None, *, detector_loader=load_selection):
    config = config or PublicConfig()
    storage = config.storage
    engine, sessions = connect(storage)
    for directory in ["media", "uploads"]:
        (storage / directory).mkdir(exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        salt_path = storage / ".client-salt"
        if not salt_path.exists():
            salt_path.write_text(secrets.token_hex(32))
            salt_path.chmod(0o600)
        app.state.client_salt = config.client_hash_salt or salt_path.read_text()
        app.state.selection, app.state.model_error = None, None
        try:
            app.state.selection = await run_in_threadpool(detector_loader, config)
        except Exception as exc:
            app.state.model_error = f"Cannot load best.pt: {exc}"
            log.exception("Model initialization failed")
        app.state.processor = Processor(app)
        if app.state.selection:
            app.state.processor.start()
        try:
            yield
        finally:
            await run_in_threadpool(app.state.processor.close)
            engine.dispose()

    app = FastAPI(title="BoxTurtles", version="2.0.0", lifespan=lifespan)
    app.state.config, app.state.storage, app.state.sessions = config, storage, sessions
    app.add_middleware(PublicBoundary, config=config)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_, exc):
        return JSONResponse({"error": {"message": str(exc.detail)}}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        return JSONResponse({"error": {"message": "Invalid request fields.", "details": [
            {"field": ".".join(map(str, x["loc"])), "message": x["msg"]} for x in exc.errors()]}}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_, exc):
        log.exception("Unexpected public API failure", exc_info=exc)
        return JSONResponse({"error": {"message": "The server could not complete this request. Please retry or contact the administrator."}}, status_code=500)

    def db():
        with sessions() as session:
            yield session

    def admin(authorization: str = Header("")):
        expected = config.admin_token.strip()
        if not expected:
            raise HTTPException(503, "Administrator access is not configured on this server. Set TURTLE_ADMIN_TOKEN and recreate the app container.")
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.casefold() != "bearer" or not secrets.compare_digest(token.strip().encode(), expected.encode()):
            raise HTTPException(401, "Invalid administrator token. Paste the configured token and try again.",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.post("/api/admin/check", dependencies=[Depends(admin)])
    def check_admin():
        return JSONResponse({"data": {"authenticated": True}}, headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        ready = app.state.selection is not None
        return JSONResponse({"data": {"status": "ready" if ready else "unavailable", "model": "best.pt",
            "device": app.state.selection.detector.device if ready else None,
            "classes": app.state.selection.detector.model.names if ready else {},
            "error": app.state.model_error, "confidence": config.confidence,
            "workers": config.workers, "torch_threads": config.torch_threads,
            "limits": {"upload_mb": config.max_upload_mb, "video_seconds": config.max_video_seconds,
                       "frame_interval": config.frame_interval, "retention_days": config.retention_days}}}, status_code=200 if ready else 503)

    def client_id(request):
        address = request.client.host if request.client else "unknown"
        return hmac.new(app.state.client_salt.encode(), address.encode(), hashlib.sha256).hexdigest()

    @app.post("/api/upload", status_code=202)
    async def upload(request: Request, file: UploadFile = File(...), metadata: str = Form("{}"), session=Depends(db)):
        if not app.state.selection:
            raise HTTPException(503, app.state.model_error)
        try:
            manual = Metadata.model_validate_json(metadata)
        except ValueError as exc:
            raise HTTPException(422, "Capture metadata must contain valid paired GPS coordinates and an optional capture timestamp.") from exc
        suffix = Path(file.filename or "").suffix.lower()
        formats = {".jpg": ("image", "image/jpeg", "JPEG"), ".jpeg": ("image", "image/jpeg", "JPEG"),
                   ".png": ("image", "image/png", "PNG"), ".webp": ("image", "image/webp", "WEBP"),
                   ".mp4": ("video", "video/mp4", None), ".mov": ("video", "video/quicktime", None)}
        if suffix not in formats:
            raise HTTPException(415, "Upload JPEG, PNG, WebP, MP4 or MOV media.")
        kind, mime, expected = formats[suffix]
        if file.content_type not in {mime, "application/octet-stream"}:
            raise HTTPException(415, "File type does not match the filename.")
        identifier, size, client = uid(), 0, client_id(request)
        path = storage / "uploads" / f"{identifier}{suffix}"
        processor = app.state.processor
        try:
            # Serialize admission and bounded writes, while inference runs on its own worker.
            def admit():
                cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
                with processor.lock:
                    active = select(func.count()).select_from(ProcessingJob).join(Submission).where(ProcessingJob.status.in_(["receiving", "queued", "processing"]))
                    if config.max_queue and session.scalar(active) >= config.max_queue + config.workers:
                        raise HTTPException(503, "Processing queue is full. Try again later.")
                    if config.client_active_jobs and session.scalar(active.where(Submission.client == client)) >= config.client_active_jobs:
                        raise HTTPException(429, "Your active processing quota is full. Wait for your jobs to finish.")
                    if config.client_daily_uploads and session.scalar(select(func.count()).select_from(Submission).where(Submission.client == client, Submission.created_at >= cutoff)) >= config.client_daily_uploads:
                        raise HTTPException(429, "Daily upload quota reached. Try again tomorrow.")
                    processor.check_space()
                    # Reserve a durable active slot before releasing the admission lock.
                    job = ProcessingJob(id=identifier, filename=Path((file.filename or "upload").replace("\\", "/")).name[:200],
                        status="receiving", settings_snapshot={"kind": kind, "model": "best.pt", "confidence": config.confidence, "frame_interval": config.frame_interval})
                    session.add(job)
                    session.flush()
                    session.add(Submission(id=identifier, client=client, kind=kind, path=str(path.relative_to(storage)), size=0,
                        metadata_info=manual.model_dump(mode="json")))
                    session.commit()
                return job
            job = await run_in_threadpool(admit)
            with path.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if config.max_upload_mb and size > config.max_upload_mb * 1024 ** 2:
                        raise HTTPException(413, f"File exceeds {config.max_upload_mb} MB.")
                    def write_chunk():
                        with processor.lock:
                            processor.check_space(len(chunk))
                            output.write(chunk)
                            output.flush()
                    await run_in_threadpool(write_chunk)
            if not size:
                raise ValueError("The uploaded file is empty.")
            def validate():
                if kind == "image":
                    with Image.open(path) as probe:
                        if probe.format != expected:
                            raise ValueError("Image content does not match its declared format.")
                    decode_image(path.read_bytes())
                else:
                    # Require an ISO Base Media container, not just an OpenCV-decodable renamed file.
                    with path.open("rb") as source:
                        if source.read(12)[4:8] != b"ftyp":
                            raise ValueError("Video content must be an MP4 or MOV container.")
                    video_properties(path, config)
            await run_in_threadpool(validate)
            with processor.lock:
                submission = session.get(Submission, identifier)
                submission.size = size
                job.status = "queued"
                session.commit()
            return {"data": job_data(job)}
        except Exception as exc:
            session.rollback()
            session.execute(delete(Submission).where(Submission.id == identifier))
            session.execute(delete(ProcessingJob).where(ProcessingJob.id == identifier))
            session.commit()
            path.unlink(missing_ok=True)
            if isinstance(exc, (ValueError, OSError)):
                raise HTTPException(422, str(exc)) from exc
            raise
        finally:
            await file.close()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100), session=Depends(db)):
        job = session.get(ProcessingJob, job_id)
        if not job or not session.get(Submission, job_id):
            raise HTTPException(404, "Job not found.")
        statement = select(CapturedImage).where(CapturedImage.metadata_info["job_id"].as_string() == job_id)
        images = session.scalars(statement.order_by(CapturedImage.uploaded_at, CapturedImage.id).offset(offset).limit(limit)).all()
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        return {"data": job_data(job) | {"images": [image_data(x) for x in images]}, "total": total}

    @app.get("/api/detections")
    def detections(status: str | None = None, gps: bool = False, offset: int = Query(0, ge=0), limit: int = Query(24, ge=1, le=100), session=Depends(db)):
        statement = select(Detection).join(CapturedImage).where(CapturedImage.source.in_(["public-image", "public-video"]))
        if status:
            if status not in {"pending", "verified", "rejected"}:
                raise HTTPException(422, "Invalid review status.")
            statement = statement.where(Detection.status == status)
        if gps:
            statement = statement.where(CapturedImage.latitude.is_not(None), CapturedImage.longitude.is_not(None))
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
        records = session.scalars(statement.order_by(Detection.created_at.desc(), Detection.id).offset(offset).limit(limit)).all()
        return {"data": [detection_data(x) for x in records], "total": total}

    @app.get("/api/stats")
    def stats(session=Depends(db)):
        public = CapturedImage.source.in_(["public-image", "public-video"])
        total = session.scalar(select(func.count()).select_from(Detection).join(CapturedImage).where(public))
        verified = session.scalar(select(func.count()).select_from(Detection).join(CapturedImage).where(public, Detection.status == "verified"))
        activity = session.execute(select(func.substr(Detection.created_at, 1, 10), func.count()).join(CapturedImage).where(public)
                                  .group_by(func.substr(Detection.created_at, 1, 10)).order_by(func.substr(Detection.created_at, 1, 10).desc()).limit(14)).all()
        def count_kind(kind):
            return session.scalar(select(func.count()).select_from(Submission).join(ProcessingJob).where(Submission.kind == kind, ProcessingJob.status == "completed"))
        return {"data": {"total": total, "verified": verified, "images": count_kind("image"), "videos": count_kind("video"),
                         "activity": [{"date": day, "count": n} for day, n in reversed(activity)]}}

    @app.post("/api/detections/{detection_id}/{action}", dependencies=[Depends(admin)])
    def review(detection_id: str, action: str, session=Depends(db)):
        targets = {"verify": "verified", "reject": "rejected", "reset": "pending"}
        record = session.get(Detection, detection_id)
        if not record or record.image.source not in {"public-image", "public-video"}:
            raise HTTPException(404, "Detection not found.")
        if action not in targets:
            raise HTTPException(404, "Unknown action.")
        expected = ["verified", "rejected"] if action == "reset" else ["pending"]
        changed = session.execute(update(Detection).where(Detection.id == detection_id, Detection.status.in_(expected)).values(
            status=targets[action], reviewed_at=None if action == "reset" else now(), review_method=None if action == "reset" else "human"))
        if not changed.rowcount:
            raise HTTPException(409, "Detection has already changed status.")
        session.commit()
        return {"data": detection_data(session.get(Detection, detection_id))}

    @app.post("/api/images/delete-rejected", dependencies=[Depends(admin)])
    def delete_photos(payload: RejectedPhotoDeletion, session=Depends(db)):
        return {"data": delete_rejected_photos(session, storage, payload.image_ids)}

    @app.post("/api/images/reject-and-delete", dependencies=[Depends(admin)])
    def reject_and_delete(payload: RejectedPhotoDeletion, session=Depends(db)):
        return {"data": delete_rejected_photos(session, storage, payload.image_ids, reject_pending=True)}

    # Only safe generated JPEGs are served. Raw uploads, SQLite and model weights remain private.
    @app.get("/media/{image_id}/{filename}")
    def media(image_id: str, filename: str):
        from uuid import UUID
        try:
            UUID(image_id)
        except ValueError:
            raise HTTPException(404, "Media not found.")
        if filename != Path(filename).name or not filename.endswith(".jpg"):
            raise HTTPException(404, "Media not found.")
        path = storage / "media" / image_id / filename
        if not path.is_file():
            raise HTTPException(404, "Media not found.")
        return FileResponse(path, media_type="image/jpeg")

    frontend = ROOT / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith(("api/", "media/")) or Path(path).suffix:
                raise HTTPException(404, "Route not found.")
            return FileResponse(frontend / "index.html")
    return app
