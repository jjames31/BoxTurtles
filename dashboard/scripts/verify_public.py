"""Exercise the real local model, uploads, video frames and persistence in temporary storage.

Run from dashboard/: python scripts/verify_public.py --image /path/to/turtle.jpg
No data is seeded and no external files or weights are downloaded.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from backend.app.public import create_app
from backend.app.public_config import PublicConfig


def wait(client, job_id):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()["data"]
        if job["status"] in {"completed", "failed"}:
            assert job["status"] == "completed", job["error"]
            return job
        time.sleep(.2)
    raise AssertionError("Processing exceeded 180 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--model", default=Path(__file__).resolve().parents[1] / "best.pt", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="boxturtles-verification-") as temporary:
        root = Path(temporary)
        config = PublicConfig(data_dir=root / "store", model_path=args.model.resolve(), requests_per_minute=10000, frame_interval=1)
        with TestClient(create_app(config)) as client:
            health = client.get("/api/health")
            assert health.status_code == 200, health.text
            image = Image.open(args.image).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "JPEG")
            response = client.post("/api/upload", files={"file": ("turtle.jpg", buffer.getvalue(), "image/jpeg")})
            assert response.status_code == 202, response.text
            detected = wait(client, response.json()["data"]["id"])
            assert detected["detections_created"] > 0, "The supplied image did not yield a detection at the configured threshold."
            blank = io.BytesIO()
            Image.new("RGB", (160, 120), "white").save(blank, "PNG")
            response = client.post("/api/upload", files={"file": ("empty.png", blank.getvalue(), "image/png")})
            assert response.status_code == 202, response.text
            empty = wait(client, response.json()["data"]["id"])
            assert empty["detections_created"] == 0, "The model detected an object in the blank fixture."
            path = root / "clip.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (320, 240))
            assert writer.isOpened(), "OpenCV MP4 encoder is unavailable"
            frame = cv2.cvtColor(np.asarray(image.resize((320, 240))), cv2.COLOR_RGB2BGR)
            for _ in range(10):
                writer.write(frame)
            writer.release()
            response = client.post("/api/upload", files={"file": ("clip.mp4", path.read_bytes(), "video/mp4")})
            assert response.status_code == 202, response.text
            video = wait(client, response.json()["data"]["id"])
            assert video["processed_frames"] == 2
            report = {"model": health.json()["data"], "image_detections": detected["detections_created"],
                      "blank_detections": empty["detections_created"], "video_frames": video["processed_frames"],
                      "video_detections": video["detections_created"]}
            image_url = detected["images"][0]["annotated_url"]
        with TestClient(create_app(config)) as client:
            assert client.get(f'/api/jobs/{detected["id"]}').json()["data"]["status"] == "completed"
            assert client.get(image_url).status_code == 200
            report["restart_persistence"] = True
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
