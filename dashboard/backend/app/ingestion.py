from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from sqlalchemy import update

from .db import CapturedImage, Detection, ProcessingJob, now, uid
from .metadata import CaptureMetadata, exif_metadata, match_telemetry, supplied, video_metadata
from .schemas import Candidate, Metadata


def decode_image(content: bytes):
    try:
        image = Image.open(BytesIO(content))
        if image.width * image.height > 40_000_000:
            raise ValueError("Image exceeds the 40 megapixel limit.")
        embedded = exif_metadata(image)
        image.load()
        # All boxes use the displayed, EXIF-oriented pixel coordinate system.
        return ImageOps.exif_transpose(image).convert("RGB"), embedded
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a supported, decodable image.") from exc


def predict_frame(image: Image.Image, selection):
    """Run one model pass and validate the displayed pixel coordinate contract."""
    candidates = selection.detector.predict(image, selection.threshold)
    for candidate in candidates:
        if candidate.bounding_box[2] > image.width or candidate.bounding_box[3] > image.height:
            raise ValueError("Bounding box is outside the EXIF-oriented image dimensions.")
    return candidates


def save_frame(session, storage: Path, image: Image.Image, filename: str, source: str, metadata: CaptureMetadata,
               selection=None, candidates: list[Candidate] | None = None, model_id="external", model_name="External detector", is_mock=False,
               is_demo=False, original_bytes: bytes | None = None, predicted: list[Candidate] | None = None, extra_metadata: dict | None = None, combined_annotation=False):
    local_inference = candidates is None
    if candidates is None:
        if selection is None:
            raise ValueError("A detection engine is required.")
        candidates = predicted if predicted is not None else predict_frame(image, selection)
        model_id, model_name, is_mock = selection.model_id, selection.model_name, selection.is_mock
    # Reject upstream invalid boxes instead of silently misaligning crops or annotations.
    for candidate in candidates:
        if candidate.bounding_box[2] > image.width or candidate.bounding_box[3] > image.height:
            raise ValueError("Bounding box is outside the EXIF-oriented image dimensions.")
    image_id = uid()
    folder = storage / "media" / image_id
    folder.mkdir(parents=True, exist_ok=True)
    saved_files = []
    try:
        original = f"{image_id}/original.jpg"
        image.save(folder / "original.jpg", quality=94)
        saved_files.append(folder / "original.jpg")
        if original_bytes is not None:
            # Keep the exact upload for EXIF, provenance and future reprocessing.
            (folder / "source.bin").write_bytes(original_bytes)
            saved_files.append(folder / "source.bin")
        record = CapturedImage(id=image_id, original_image_path=original, filename=filename, width=image.width, height=image.height,
                               source=source, latitude=metadata.latitude, longitude=metadata.longitude, captured_at=metadata.captured_at,
                               is_demo=is_demo, metadata_info=metadata.info() | (extra_metadata or {}))
        session.add(record)
        session.flush()
        created = []
        auto_accept_ids = []
        for candidate in candidates:
            detection_id = uid()
            x1, y1, x2, y2 = candidate.bounding_box
            # Pillow crop bounds must stay non-empty even for subpixel predictions.
            import math
            crop = image.crop((math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)))
            crop_path = folder / f"{detection_id}-crop.jpg"
            crop.save(crop_path, quality=94)
            saved_files.append(crop_path)
            annotated = image.copy()
            draw = ImageDraw.Draw(annotated)
            draw.rectangle((x1, y1, x2, y2), outline="#6ce3ac", width=max(2, image.width // 250))
            draw.text((x1 + 5, max(0, y1 - 16)), f"{candidate.class_name} {candidate.confidence:.0%}", fill="#6ce3ac")
            annotation_path = folder / f"{detection_id}-annotated.jpg"
            annotated.save(annotation_path, quality=93)
            saved_files.append(annotation_path)
            detection = Detection(id=detection_id, image_id=image_id, class_name=candidate.class_name, confidence=candidate.confidence,
                                  bounding_box=list(candidate.bounding_box), cropped_image_path=f"{image_id}/{crop_path.name}",
                                  annotated_image_path=f"{image_id}/{annotation_path.name}", model_id=model_id, model_name=model_name, is_mock=is_mock)
            session.add(detection)
            created.append(detection)
            label = re.sub(r"[\s_-]+", " ", candidate.class_name.casefold()).strip()
            if (local_inference and selection.model_kind == "yolo" and selection.auto_accept_enabled
                    and not is_mock and not is_demo and candidate.confidence >= selection.auto_accept_threshold
                    and label in {"turtle", "box turtle"}):
                auto_accept_ids.append(detection_id)
        if combined_annotation:
            combined = image.copy()
            draw = ImageDraw.Draw(combined)
            for candidate in candidates:
                x1, y1, x2, y2 = candidate.bounding_box
                draw.rectangle((x1, y1, x2, y2), outline="#6ce3ac", width=max(2, image.width // 250))
                draw.text((x1 + 5, max(0, y1 - 16)), f"{candidate.class_name} {candidate.confidence:.1%}", fill="#6ce3ac")
            combined.save(folder / "annotated.jpg", quality=93)
            saved_files.append(folder / "annotated.jpg")
        if auto_accept_ids:
            session.flush()
            # Only candidates from this newly created frame are eligible. An
            # explicit pending condition retains the same review transition rule.
            session.execute(update(Detection).where(Detection.id.in_(auto_accept_ids), Detection.status == "pending", Detection.is_mock.is_(False)).values(
                status="verified", reviewed_at=now(), review_method="auto-confidence", auto_accept_threshold=selection.auto_accept_threshold))
            # UPDATE synchronization can leave newly inserted nullable audit
            # attributes stale. Reload those values when the caller reads them.
            for detection in created:
                if detection.id in auto_accept_ids:
                    session.expire(detection, ["status", "reviewed_at", "review_method", "auto_accept_threshold"])
        session.commit()
        return record, created
    except Exception:
        session.rollback()
        for path in saved_files:
            path.unlink(missing_ok=True)
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        raise


def process_video(app, job_id, path, manual: Metadata, telemetry, selection, interval, max_frames):
    import cv2
    cap = None
    with app.state.sessions() as session:
        job = session.get(ProcessingJob, job_id)
        try:
            job.status = "processing"
            session.commit()
            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                raise ValueError("Cannot decode this video. Export DJI footage to a supported MP4/MOV codec (H.264 is recommended).")
            fps, count = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if not fps or fps <= 0 or not count or count <= 0:
                raise ValueError("Video has no readable frame count or frame rate.")
            step = max(1, round(interval * fps))
            indices = list(range(0, int(count), step))[:max_frames]
            job.total_frames = len(indices)
            base = video_metadata(path).apply(supplied(manual))
            warnings = list(base.warnings)
            if (int(count) + step - 1) // step > max_frames:
                warnings.append(f"Frame limit reached: only the first {max_frames} sampled frames are selected.")
            session.commit()
            for index in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, pixels = cap.read()
                if not ok:
                    warnings.append(f"Could not decode frame {index}.")
                    continue
                # Derive time from the actual frame index, never from upload time.
                seconds = index / fps
                metadata = CaptureMetadata(base.latitude, base.longitude, base.captured_at, dict(base.provenance), list(base.warnings))
                if metadata.captured_at:
                    metadata.captured_at = (datetime.fromisoformat(metadata.captured_at) + timedelta(seconds=seconds)).isoformat()
                metadata.apply(match_telemetry(telemetry, seconds, app.state.config.telemetry_tolerance_seconds))
                metadata.provenance["video_frame"] = {"job_id": job_id, "offset_seconds": round(seconds, 6), "frame_index": index, "fps": fps}
                _, detections = save_frame(session, app.state.storage, Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)),
                                           f"{job.filename} · frame {index}", "recorded-video", metadata, selection=selection)
                job.processed_frames += 1
                job.detections_created += len(detections)
                for warning in metadata.warnings:
                    if warning not in warnings:
                        warnings.append(warning)
                session.commit()
            if not job.processed_frames:
                raise ValueError("None of the selected frames could be decoded.")
            job.warnings = list(dict.fromkeys(warnings))
            job.status = "completed"
        except Exception as exc:
            session.rollback()
            job = session.get(ProcessingJob, job_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            if cap is not None:
                cap.release()
            job.finished_at = now()
            session.commit()
            # Recorded input is retained under data/videos for reprocessing.
