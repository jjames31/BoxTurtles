"""Bounded durable workers. Routes only validate and enqueue; inference lives here."""
import logging
import math
import shutil
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from time import perf_counter

import cv2
from PIL import Image
from sqlalchemy import delete, select, update

from .db import CapturedImage, Detection, ProcessingJob, now
from .engine import EngineSelection, YoloDetector
from .ingestion import decode_image, predict_frame, save_frame
from .metadata import CaptureMetadata, supplied, video_metadata
from .public_store import Submission
from .schemas import Metadata

log = logging.getLogger(__name__)


class WorkerDetectors:
    """Preloaded, independent models assigned to fixed processing threads."""
    def __init__(self, detectors):
        self.detectors = tuple(detectors)
        self.model = self.detectors[0].model
        self.device = self.detectors[0].device

    def for_worker(self, index):
        return self.detectors[index]

    def predict(self, image, threshold):
        # Standalone callers retain the regular Detector contract.
        return self.detectors[0].predict(image, threshold)


def load_selection(config):
    import torch
    torch.set_num_threads(config.torch_threads)
    path = config.model_path.resolve()
    device = config.device
    if device == "auto":
        device = "0" if torch.cuda.is_available() else "cpu"
    if device != "cpu" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable. Set TURTLE_DEVICE=cpu.")
    detector = YoloDetector(path, [], device=device)
    # Read best.pt once, then copy its weights before any predictor creates mutable state.
    detectors = [detector] + [detector.clone_uninitialized() for _ in range(config.workers - 1)]
    for worker_detector in detectors:
        worker_detector.predict(Image.new("RGB", (64, 64)), config.confidence)
    # Ultralytics device setup can reset the CPU thread count during warmup.
    torch.set_num_threads(config.torch_threads)
    return EngineSelection("best.pt", "best.pt", config.confidence, False,
                           WorkerDetectors(detectors), model_kind="yolo")


def video_properties(path, config):
    cap = cv2.VideoCapture(str(path))
    try:
        fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not cap.isOpened() or not all(math.isfinite(x) and x > 0 for x in [fps, count, width, height]):
            raise ValueError("Video cannot be decoded. Use an MP4 or MOV with H.264 video.")
        if config.max_video_seconds and count / fps > config.max_video_seconds:
            raise ValueError(f"Video exceeds the {config.max_video_seconds:g} second limit.")
        if config.max_video_pixels and width * height > config.max_video_pixels:
            raise ValueError("Video exceeds the configured resolution limit.")
        ok, _ = cap.read()
        if not ok:
            raise ValueError("Video contains no readable frames.")
        return fps, int(count)
    finally:
        cap.release()


class Processor:
    def __init__(self, app):
        self.app = app
        self.config = app.state.config
        self.storage = app.state.storage
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.threads = []
        self.worker = threading.local()

    def disk_bytes(self):
        return sum(p.stat().st_size for p in self.storage.rglob("*") if p.is_file())

    def check_space(self, extra=0):
        if self.config.max_disk_mb and self.disk_bytes() + extra > self.config.max_disk_mb * 1024 ** 2:
            raise ValueError("Storage capacity reached. An administrator must free space or configure retention.")
        if shutil.disk_usage(self.storage).free < extra + 64 * 1024 ** 2:
            raise ValueError("Insufficient free disk space.")

    def start(self):
        with self.app.state.sessions() as session:
            session.execute(update(ProcessingJob).where(ProcessingJob.status.in_(["receiving", "processing"])).values(
                status="failed", error="Processing interrupted by server restart. Partial results are preserved; submit again.", finished_at=now()))
            session.commit()
        self.cleanup()
        for index in range(self.config.workers):
            thread = threading.Thread(target=self.run, args=(index,), name=f"media-worker-{index}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join()  # Finish the current frame; no database disposal while a worker is active.

    def run(self, index=0):
        selection = self.app.state.selection
        if hasattr(selection.detector, "for_worker"):
            selection = replace(selection, detector=selection.detector.for_worker(index))
        self.worker.selection = selection
        while not self.stop.is_set():
            with self.lock, self.app.state.sessions() as session:
                job = session.scalar(select(ProcessingJob).join(Submission).where(ProcessingJob.status == "queued")
                                     .order_by(ProcessingJob.created_at).limit(1))
                job_id = job.id if job else None
                if job:
                    job.status = "processing"
                    session.commit()
            if job_id:
                self.process(job_id)
            else:
                self.stop.wait(0.25)
            try:
                self.cleanup()
            except Exception:
                log.exception("Retention cleanup failed")

    def save(self, session, job, image, metadata):
        started = perf_counter()
        selection = getattr(self.worker, "selection", self.app.state.selection)
        candidates = predict_frame(image, selection)
        with self.lock:
            # Conservative bound for originals, crops, per-object annotations and combined preview.
            self.check_space(image.width * image.height * (16 + 16 * len(candidates)) + 65536)
            record, detections = save_frame(session, self.storage, image, job.filename,
                "public-image" if job.settings_snapshot["kind"] == "image" else "public-video",
                metadata, selection=selection, predicted=candidates, combined_annotation=True,
                extra_metadata={"job_id": job.id, "processing_ms": round((perf_counter() - started) * 1000, 2)})
            job.processed_frames += 1
            job.detections_created += len(detections)
            session.commit()

    def process(self, job_id):
        with self.app.state.sessions() as session:
            job, submission = session.get(ProcessingJob, job_id), session.get(Submission, job_id)
            started = perf_counter()
            try:
                path = self.storage / submission.path
                manual = Metadata.model_validate(submission.metadata_info)
                if submission.kind == "image":
                    image, embedded = decode_image(path.read_bytes())
                    job.total_frames = 1
                    self.save(session, job, image, embedded.apply(supplied(manual, "user supplied (unverified)")))
                else:
                    fps, count = video_properties(path, self.config)
                    step = max(1, round(self.config.frame_interval * fps))
                    indices = range(0, count, step)
                    if self.config.max_frames:
                        indices = indices[:self.config.max_frames]
                    job.total_frames = len(indices)
                    if math.ceil(count / step) > len(indices):
                        job.warnings = [f"Limited to the first {self.config.max_frames} sampled frames."]
                    session.commit()
                    base = video_metadata(path).apply(supplied(manual, "user supplied (unverified)"))
                    cap = cv2.VideoCapture(str(path))
                    try:
                        for index in indices:
                            if self.stop.is_set():
                                raise ValueError("Processing interrupted by server shutdown. Partial results are preserved.")
                            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                            ok, pixels = cap.read()
                            if not ok:
                                raise ValueError(f"Cannot decode sampled frame {index}. Partial results are preserved.")
                            seconds = index / fps
                            metadata = CaptureMetadata(base.latitude, base.longitude, base.captured_at, dict(base.provenance), list(base.warnings))
                            if metadata.captured_at:
                                metadata.captured_at = (datetime.fromisoformat(metadata.captured_at) + timedelta(seconds=seconds)).isoformat()
                            metadata.provenance["video_frame"] = {"job_id": job.id, "offset_seconds": seconds, "frame_index": index}
                            self.save(session, job, Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)), metadata)
                    finally:
                        cap.release()
                job.status = "completed"
            except Exception as exc:
                log.exception("Processing job %s failed", job_id)
                session.rollback()
                job = session.get(ProcessingJob, job_id)
                job.status, job.error = "failed", str(exc)
            job.finished_at = now()
            job.settings_snapshot = job.settings_snapshot | {"processing_ms": round((perf_counter() - started) * 1000, 2)}
            session.commit()

    def cleanup(self):
        if not self.config.retention_days:
            return
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)).isoformat()
        with self.lock, self.app.state.sessions() as session:
            submissions = session.scalars(select(Submission).join(ProcessingJob).where(
                Submission.created_at < cutoff, ProcessingJob.status.in_(["completed", "failed"]))).all()
            for submission in submissions:
                images = session.scalars(select(CapturedImage).where(CapturedImage.metadata_info["job_id"].as_string() == submission.id)).all()
                for image in images:
                    session.execute(delete(Detection).where(Detection.image_id == image.id))
                    session.delete(image)
                    shutil.rmtree(self.storage / "media" / image.id, ignore_errors=True)
                (self.storage / submission.path).unlink(missing_ok=True)
                job = session.get(ProcessingJob, submission.id)
                session.delete(submission)
                session.flush()
                session.delete(job)
            session.commit()
