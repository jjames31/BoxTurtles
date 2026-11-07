"""Explicit, photo-level removal from the rejected archive."""
import json
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, select, text, update

from .db import CapturedImage, Detection, uid, now

logger = logging.getLogger(__name__)


def _is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _media_path(media, value):
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(409, "A selected photo has an unsafe storage path; no photos were deleted.")
    path = media / relative
    if path == media or not path.resolve().is_relative_to(media):
        raise HTTPException(409, "A selected photo has an unsafe storage path; no photos were deleted.")
    cursor = media
    for part in relative.parts:
        cursor /= part
        if _is_link(cursor):
            raise HTTPException(409, "A selected photo uses a storage link; no photos were deleted.")
    if path.exists() and not path.is_file():
        raise HTTPException(409, "A selected photo has an unexpected storage path; no photos were deleted.")
    return path


def _image_paths(image_id, original):
    return [original, str(Path(original).parent / "source.bin"), str(Path(image_id) / "source.bin")]


def _move_file(source, destination):
    source.replace(destination)


def delete_rejected_photos(session, storage, image_ids, *, reject_pending=False):
    """Serialize review/deletion writers and roll back media moves on failed commits.

    Media is moved outside the public /media mount before records are removed.
    Shared paths remain available to surviving records. Only individual files
    are removed; uploaded videos and unrelated folder contents are preserved.
    """
    image_ids = list(dict.fromkeys(str(value) for value in image_ids))
    moved = []
    staging = None
    manifest = None
    cleanup_pending = False
    folders = set()
    try:
        # Lock before reading statuses so a concurrent review cannot make a
        # verified/pending sibling disappear between validation and deletion.
        session.execute(text("BEGIN IMMEDIATE"))
        images = session.scalars(select(CapturedImage).where(CapturedImage.id.in_(image_ids))).all()
        if len(images) != len(image_ids):
            raise HTTPException(404, "One or more selected photos no longer exist. Refresh the archive; no photos were deleted.")
        records = session.scalars(select(Detection).where(Detection.image_id.in_(image_ids))).all()
        if reject_pending:
            if any(record.status not in {"pending", "rejected"} for record in records):
                raise HTTPException(409, "This image contains verified detections. Reset them to pending before rejecting and deleting the image; nothing was changed.")
            pending_ids = [record.id for record in records if record.status == "pending"]
            if pending_ids:
                changed = session.execute(update(Detection).where(Detection.id.in_(pending_ids), Detection.status == "pending").values(
                    status="rejected", reviewed_at=now(), review_method="human", auto_accept_threshold=None))
                if changed.rowcount != len(pending_ids):
                    raise HTTPException(409, "A detection changed status; nothing was deleted. Refresh and try again.")
        if {record.image_id for record in records} != set(image_ids) or any(record.status != "rejected" for record in records):
            raise HTTPException(409, "A selected photo has pending or verified detections. Only photos with all detections rejected can be deleted; no photos were deleted.")

        media_root = storage / "media"
        if _is_link(media_root):
            raise HTTPException(409, "Photo storage uses a link; no photos were deleted.")
        media = media_root.resolve()
        selected_paths = []
        for image in images:
            selected_paths.extend(_image_paths(image.id, image.original_image_path))
            combined = f"{image.id}/annotated.jpg"
            if (media / combined).is_file():
                selected_paths.append(combined)
        for record in records:
            selected_paths.extend([record.cropped_image_path, record.annotated_image_path])
        paths = {_media_path(media, value) for value in selected_paths}

        # A surviving photo or detection can reference the same normalized
        # path. Include exact-upload sidecars beside surviving originals.
        protected = set()
        for image_id, original in session.execute(select(CapturedImage.id, CapturedImage.original_image_path).where(CapturedImage.id.not_in(image_ids))):
            protected.update((media / value).resolve() for value in _image_paths(image_id, original))
        for crop, annotation in session.execute(select(Detection.cropped_image_path, Detection.annotated_image_path).where(Detection.image_id.not_in(image_ids))):
            protected.update([(media / crop).resolve(), (media / annotation).resolve()])
        removable = sorted(paths - protected)

        staging_root = storage / ".deletion-staging"
        if _is_link(staging_root) or not staging_root.resolve().is_relative_to(storage.resolve()):
            raise HTTPException(409, "Deletion recovery storage is unavailable; no photos were deleted.")
        staging = staging_root / uid()
        staging.mkdir(parents=True)
        manifest = staging / "manifest.json"
        manifest.write_text(json.dumps({
            "image_ids": image_ids,
            "files": [{"staged_name": str(index), "media_relative_path": source.relative_to(media).as_posix()}
                      for index, source in enumerate(removable)],
        }, indent=2), encoding="utf-8")
        for index, source in enumerate(removable):
            if source.exists():
                destination = staging / str(index)
                _move_file(source, destination)
                moved.append((source, destination))
                folders.add(source.parent)

        detection_ids = [record.id for record in records]
        result = session.execute(delete(Detection).where(Detection.id.in_(detection_ids), Detection.status == "rejected").execution_options(synchronize_session=False))
        if result.rowcount != len(detection_ids):
            raise HTTPException(409, "A selected detection changed status; no photos were deleted. Refresh the archive and try again.")
        session.execute(delete(CapturedImage).where(CapturedImage.id.in_(image_ids)).execution_options(synchronize_session=False))
        session.commit()
    except Exception as exc:
        session.rollback()
        recovery_failed = False
        for source, destination in reversed(moved):
            try:
                _move_file(destination, source)
            except OSError:
                recovery_failed = True
                logger.exception("Could not restore photo file %s from %s", source, destination)
        if manifest is not None and not recovery_failed:
            try:
                manifest.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove completed rollback manifest %s", manifest)
        if staging is not None:
            try:
                staging.rmdir()
            except OSError:
                pass
        if recovery_failed:
            raise HTTPException(500, "Deletion could not finish. Some photo files are preserved in local recovery storage; check the server log before retrying.") from exc
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Rejected photo deletion rolled back")
        raise HTTPException(500, "The selected photos could not be deleted. Close programs using those files and try again; no photos were deleted.") from exc

    # Once committed, a cleanup failure must not turn a successful logical
    # deletion into an error that invites a destructive retry. The remaining
    # bytes stay outside the public media mount for manual cleanup.
    for _, destination in moved:
        try:
            destination.unlink()
        except OSError:
            cleanup_pending = True
            logger.exception("Could not clean privately staged deleted photo file %s", destination)
    if not cleanup_pending:
        try:
            manifest.unlink()
        except OSError:
            cleanup_pending = True
            logger.exception("Could not remove completed deletion manifest %s", manifest)
    for folder in folders | {staging}:
        try:
            folder.rmdir()
        except OSError:
            pass
    return {"deleted_image_ids": image_ids, "deleted_detection_ids": detection_ids,
            "deleted_photos": len(image_ids), "cleanup_pending": cleanup_pending}
