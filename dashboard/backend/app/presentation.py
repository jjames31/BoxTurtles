def detection_data(record):
    image = record.image
    return {
        "id": record.id, "sighting_id": f"S-{record.id[:8].upper()}", "image_id": record.image_id,
        "class_name": record.class_name, "confidence": record.confidence, "bounding_box": record.bounding_box,
        "status": record.status, "reviewed_at": record.reviewed_at, "created_at": record.created_at,
        "review_method": record.review_method, "auto_accept_threshold": record.auto_accept_threshold,
        "model_id": record.model_id, "model_name": record.model_name, "is_mock": record.is_mock,
        "original_url": f"/media/{image.original_image_path}", "cropped_url": f"/media/{record.cropped_image_path}",
        "annotated_url": f"/media/{record.annotated_image_path}", "filename": image.filename,
        "width": image.width, "height": image.height, "latitude": image.latitude, "longitude": image.longitude,
        "captured_at": image.captured_at, "uploaded_at": image.uploaded_at, "source": image.source,
        "metadata": image.metadata_info, "is_demo": image.is_demo,
    }

