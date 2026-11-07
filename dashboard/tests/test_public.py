"""Public API integration tests use explicit dependency injection, never a production fallback."""
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from backend.app.db import CapturedImage, ProcessingJob, now
from backend.app.engine import EngineSelection
from backend.app.public import create_app
from backend.app.public_config import PublicConfig
from backend.app.public_store import Submission
from backend.app.schemas import Candidate


class TestDetector:
    __test__ = False
    device = "cpu"
    model = SimpleNamespace(names={0: "box turtle"})

    def __init__(self, candidates=None, gate=None):
        self.candidates = candidates or []
        self.gate = gate

    def predict(self, image, threshold):
        if self.gate:
            self.gate.wait(timeout=10)
        return self.candidates


def setup(tmp_path, detector=None, **overrides):
    config = PublicConfig(data_dir=tmp_path, requests_per_minute=10000, admin_token="test-secret", **overrides)
    selection = EngineSelection("best.pt", "best.pt", .35, False, detector or TestDetector(), model_kind="yolo")
    return create_app(config, detector_loader=lambda _: selection)


def image_bytes(fmt="JPEG"):
    buffer = io.BytesIO()
    Image.new("RGB", (160, 120), "white").save(buffer, fmt)
    return buffer.getvalue()


def send(client, content=None, name="turtle.jpg", mime="image/jpeg", metadata=None):
    return client.post("/api/upload", files={"file": (name, content if content is not None else image_bytes(), mime)},
                       data={"metadata": json.dumps(metadata or {})})


def wait(client, job_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job_id}").json()["data"]
        if result["status"] in {"failed", "completed"}:
            return result
        time.sleep(.05)
    raise AssertionError("Job timed out")


def test_multiple_boxes_orientation_metadata_and_admin(tmp_path):
    candidates = [Candidate(class_name="box turtle", confidence=.91, bounding_box=[10, 20, 70, 80]),
                  Candidate(class_name="box turtle", confidence=.72, bounding_box=[90, 30, 140, 100])]
    with TestClient(setup(tmp_path, TestDetector(candidates))) as client:
        response = send(client, metadata={"latitude": 35.9, "longitude": -78.9, "captured_at": "2025-01-02T03:04:05-05:00"})
        assert response.status_code == 202, response.text
        result = wait(client, response.json()["data"]["id"])
        assert result["status"] == "completed", result
        assert result["detections_created"] == 2
        image = result["images"][0]
        assert image["latitude"] == 35.9
        assert image["captured_at"] == "2025-01-02T03:04:05-05:00"
        assert len(image["detections"]) == 2
        assert image["detections"][0]["bounding_box"] == [10, 20, 70, 80]
        assert image["metadata"]["processing_ms"] >= 0
        annotated = Image.open(io.BytesIO(client.get(image["annotated_url"]).content))
        assert annotated.size == (160, 120)
        # Both rectangles must appear in the combined preview, not just the first object.
        for x, y in [(10, 50), (90, 70)]:
            r, g, b = annotated.getpixel((x, y))
            assert g > r + 10
        detection = image["detections"][0]
        assert client.post(f'/api/detections/{detection["id"]}/verify').status_code == 401
        headers = {"Authorization": "Bearer test-secret"}
        assert client.post(f'/api/detections/{detection["id"]}/verify', headers=headers).status_code == 200
        assert client.post(f'/api/detections/{detection["id"]}/verify', headers=headers).status_code == 409
        assert client.get('/api/stats').json()["data"]["verified"] == 1
        assert client.get('/api/detections?gps=true').json()["total"] == 2
        for path in ['/api/settings', '/api/models', '/api/inference/frame', '/api/streams']:
            assert client.get(path).status_code == 404
        assert client.get(f'/media/{image["id"]}/source.bin').status_code == 404


def test_empty_results_formats_and_persistence(tmp_path):
    for extension, fmt, mime in [('jpg', 'JPEG', 'image/jpeg'), ('png', 'PNG', 'image/png'), ('webp', 'WEBP', 'image/webp')]:
        with TestClient(setup(tmp_path)) as client:
            result = wait(client, send(client, image_bytes(fmt), f'../test.{extension}', mime).json()["data"]["id"])
            assert result['status'] == 'completed', result
            assert result['detections_created'] == 0
            assert result['images'][0]['captured_at'] is None
            assert result['images'][0]['latitude'] is None
            assert result['filename'] == f'test.{extension}'
            job_id = result['id']
    with TestClient(setup(tmp_path)) as client:
        result = client.get(f'/api/jobs/{job_id}').json()['data']
        assert result['status'] == 'completed'
        assert client.get(result['images'][0]['original_url']).status_code == 200
        assert client.get('/api/stats').json()['data']['images'] == 3


def test_missing_model_no_fallback(tmp_path):
    def fail(_):
        raise ValueError('best.pt missing')
    with TestClient(create_app(PublicConfig(data_dir=tmp_path), detector_loader=fail)) as client:
        assert client.get('/api/health').status_code == 503
        assert 'best.pt missing' in client.get('/api/health').text
        assert send(client).status_code == 503
        assert client.get('/api/detections').json()['total'] == 0


def test_limits_types_content_and_paths(tmp_path):
    with TestClient(setup(tmp_path, max_upload_mb=1)) as client:
        assert send(client, b'x' * (1024 ** 2 + 1)).status_code == 413
        assert send(client, b'', name='empty.jpg').status_code == 422
        assert send(client, b'<script>bad</script>').status_code == 422
        assert send(client, image_bytes('PNG')).status_code == 422
        assert send(client, name='bad.svg', mime='image/svg+xml').status_code == 415
        assert send(client, mime='text/html').status_code == 415
        assert send(client, metadata={'latitude': 10}).status_code == 422
        assert send(client, metadata={'latitude': 95, 'longitude': 20}).status_code == 422
        assert client.get('/media/../../best.pt').status_code == 404
        assert client.post('/api/images/delete-rejected', json={'image_ids': ['00000000-0000-0000-0000-000000000001']}).status_code == 401


def make_video(path, seconds=2):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 5, (160, 120))
    for _ in range(seconds * 5):
        writer.write(np.full((120, 160, 3), 120, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def test_video_jobs_progress_responsiveness_and_timestamps(tmp_path):
    gate = threading.Event()
    app = setup(tmp_path / 'store', TestDetector([Candidate(confidence=.9, bounding_box=[5, 5, 40, 40])], gate), frame_interval=1)
    video = make_video(tmp_path / 'test.mp4')
    with TestClient(app) as client:
        try:
            response = send(client, video, 'test.mp4', 'video/mp4')
            assert response.status_code == 202, response.text
            job_id = response.json()['data']['id']
            started = time.monotonic()
            assert client.get('/api/health').status_code == 200
            assert client.get('/api/stats').status_code == 200
            assert time.monotonic() - started < 1
            assert client.get(f'/api/jobs/{job_id}').json()['data']['status'] in ['queued', 'processing']
        finally:
            gate.set()
        job = wait(client, job_id)
        assert job['status'] == 'completed', job
        assert job['processed_frames'] == 2
        assert [x['metadata']['provenance']['video_frame']['offset_seconds'] for x in job['images']] == [0, 1]
        assert all(x['captured_at'] is None for x in job['images'])
        assert client.get('/api/stats').json()['data']['videos'] == 1
    with TestClient(setup(tmp_path / 'duration', max_video_seconds=1)) as client:
        assert send(client, video, 'test.mov', 'video/quicktime').status_code == 422


def test_concurrent_clients_quotas_and_queue(tmp_path):
    gate = threading.Event()
    app = setup(tmp_path, TestDetector(gate=gate), client_active_jobs=1, max_queue=1, workers=1)
    with TestClient(app, client=('192.0.2.1', 1234)) as one:
        two = TestClient(app, client=('192.0.2.2', 1234))
        three = TestClient(app, client=('192.0.2.3', 1234))
        try:
            assert send(one).status_code == 202
            assert send(one).status_code == 429
            assert send(two).status_code == 202
            assert send(three).status_code == 503
        finally:
            gate.set()
            two.close()
            three.close()


def test_daily_quota_rate_limit_disk(tmp_path):
    with TestClient(setup(tmp_path / 'daily', client_daily_uploads=1)) as client:
        wait(client, send(client).json()['data']['id'])
        assert send(client).status_code == 429
    app = create_app(PublicConfig(data_dir=tmp_path / 'rate', requests_per_minute=1), detector_loader=lambda _: EngineSelection('best.pt', 'best.pt', .35, False, TestDetector()))
    with TestClient(app) as client:
        assert client.get('/api/stats').status_code == 200
        assert client.get('/api/stats').status_code == 429
    with TestClient(setup(tmp_path / 'full', max_disk_mb=10)) as client:
        (tmp_path / 'full' / 'large').write_bytes(b'0' * 10 * 1024 ** 2)
        assert send(client).status_code == 422


def test_restart_recovers_queue_and_marks_interruption(tmp_path):
    app = setup(tmp_path)
    with app.state.sessions() as session:
        for status in ['queued', 'processing', 'receiving']:
            path = tmp_path / 'uploads' / f'{status}.jpg'
            path.write_bytes(image_bytes())
            session.add(ProcessingJob(id=status, filename=path.name, status=status, settings_snapshot={'kind': 'image'}))
            session.flush()
            session.add(Submission(id=status, client='test', kind='image', path=str(path.relative_to(tmp_path)), size=path.stat().st_size))
        session.commit()
    with TestClient(app) as client:
        assert wait(client, 'queued')['status'] == 'completed'
        assert client.get('/api/jobs/processing').json()['data']['status'] == 'failed'
        assert client.get('/api/jobs/receiving').json()['data']['status'] == 'failed'


def test_simultaneous_uploads_and_retention(tmp_path):
    gate = threading.Event()
    app = setup(tmp_path, TestDetector(gate=gate), retention_days=1)
    with TestClient(app) as client:
        visitors = [TestClient(app, client=(f'192.0.2.{n}', 1234)) for n in (10, 11)]
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(send, visitors))
            assert all(response.status_code == 202 for response in responses), [r.text for r in responses]
        finally:
            gate.set()
        results = [wait(client, response.json()['data']['id']) for response in responses]
        with app.state.sessions() as session:
            submission = session.get(Submission, results[0]['id'])
            submission.created_at = '2000-01-01T00:00:00+00:00'
            session.commit()
        app.state.processor.cleanup()
        assert client.get('/api/jobs/' + results[0]['id']).status_code == 404
        assert client.get(results[0]['images'][0]['original_url']).status_code == 404
        assert client.get('/api/jobs/' + results[1]['id']).status_code == 200
        for visitor in visitors:
            visitor.close()


def test_streamed_request_body_limit_before_multipart_spooling(tmp_path):
    with TestClient(setup(tmp_path, max_upload_mb=1)) as client:
        def chunks():
            for _ in range(3):
                yield b'x' * 1024 ** 2
        response = client.post('/api/upload', content=chunks(), headers={'Content-Type': 'multipart/form-data; boundary=large'})
        assert response.status_code == 413


def test_model_loaded_once_and_missing_weights_fail_without_download(tmp_path):
    from backend.app.engine import YoloDetector
    calls = []
    def loader(config):
        calls.append(config.model_path)
        return EngineSelection('best.pt', 'best.pt', .35, False, TestDetector())
    with TestClient(create_app(PublicConfig(data_dir=tmp_path), detector_loader=loader)) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/health').status_code == 200
        wait(client, send(client).json()['data']['id'])
        assert len(calls) == 1
    with pytest.raises(ValueError, match='downloads are disabled'):
        YoloDetector(tmp_path / 'missing.pt', [])


def test_unlimited_upload_settings_accept_large_media_and_many_pending_jobs(tmp_path):
    overrides = dict(max_upload_mb=0, max_video_seconds=0, max_video_pixels=0,
                     max_frames=0, max_queue=0, client_active_jobs=0,
                     client_daily_uploads=0, max_disk_mb=0)
    gate = threading.Event()
    app = setup(tmp_path, TestDetector(gate=gate), **overrides)
    # Upload a valid PNG larger than the former middleware's accidental 1 MiB cap.
    rng = np.random.default_rng(42)
    buffer = io.BytesIO()
    Image.fromarray(rng.integers(0, 256, (700, 700, 3), dtype=np.uint8)).save(buffer, 'PNG')
    assert len(buffer.getvalue()) > 1024 ** 2
    with TestClient(app) as client:
        try:
            for _ in range(32):
                response = send(client, buffer.getvalue(), 'large.png', 'image/png')
                assert response.status_code == 202, response.text
        finally:
            gate.set()
        result = wait(client, response.json()['data']['id'])
        assert result['status'] == 'completed'
        video = make_video(tmp_path / 'unlimited.mp4', seconds=2)
        response = send(client, video, 'unlimited.mp4', 'video/mp4')
        assert response.status_code == 202, response.text
        assert wait(client, response.json()['data']['id'])['processed_frames'] > 0
    with TestClient(create_app(PublicConfig(data_dir=tmp_path / 'rate', requests_per_minute=0),
            detector_loader=lambda _: EngineSelection('best.pt', 'best.pt', .35, False, TestDetector()))) as client:
        for _ in range(125):
            assert client.get('/api/health').status_code == 200


def test_two_workers_enter_inference_together_without_duplicate_claims(tmp_path):
    class ConcurrentDetector(TestDetector):
        def __init__(self):
            super().__init__()
            self.barrier = threading.Barrier(2)
            self.lock = threading.Lock()
            self.calls = 0
            self.threads = set()

        def predict(self, image, threshold):
            with self.lock:
                self.calls += 1
                self.threads.add(threading.current_thread().name)
            # A serialized inference path times out and fails both jobs.
            self.barrier.wait(timeout=5)
            return []

    detector = ConcurrentDetector()
    app = setup(tmp_path, detector, workers=2)
    with TestClient(app) as client:
        jobs = [send(client).json()['data']['id'] for _ in range(2)]
        results = [wait(client, identifier) for identifier in jobs]
        assert all(result['status'] == 'completed' for result in results), results
        assert detector.calls == 2
        assert len(detector.threads) == 2
        assert len({result['images'][0]['id'] for result in results}) == 2
        assert client.get('/api/health').json()['data']['workers'] == 2


def test_worker_model_assignment_is_independent_and_checkpoint_loaded_once(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    from backend.app import public_processing
    calls = []

    class IndependentDetector(TestDetector):
        def __init__(self, path, labels, device):
            super().__init__()
            calls.append(path)
            self.device = device
            self.warmed = False

        def clone_uninitialized(self):
            assert not self.warmed
            clone = object.__new__(type(self))
            TestDetector.__init__(clone)
            clone.device = self.device
            clone.warmed = False
            return clone

        def predict(self, image, threshold):
            self.warmed = True
            return []

    monkeypatch.setattr(public_processing, 'YoloDetector', IndependentDetector)
    selection = public_processing.load_selection(PublicConfig(data_dir=tmp_path, workers=2))
    assert len(calls) == 1
    first, second = selection.detector.for_worker(0), selection.detector.for_worker(1)
    assert first is not second
    assert first.warmed and second.warmed


def test_admin_check_distinguishes_missing_and_incorrect_tokens(tmp_path):
    with TestClient(setup(tmp_path)) as client:
        assert client.post('/api/admin/check').status_code == 401
        assert client.post('/api/admin/check', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        response = client.post('/api/admin/check', headers={'Authorization': 'bearer test-secret  '})
        assert response.status_code == 200
        assert response.json()['data']['authenticated'] is True
        assert response.headers['cache-control'] == 'no-store'
        assert 'test-secret' not in response.text
    app = create_app(PublicConfig(data_dir=tmp_path / 'unconfigured', admin_token=''),
        detector_loader=lambda _: EngineSelection('best.pt', 'best.pt', .35, False, TestDetector()))
    with TestClient(app) as client:
        response = client.post('/api/admin/check', headers={'Authorization': 'Bearer anything'})
        assert response.status_code == 503
        assert 'not configured' in response.json()['error']['message']


def test_reject_and_delete_image_is_authenticated_and_preserves_source(tmp_path):
    candidates = [Candidate(confidence=.9, bounding_box=[5, 5, 40, 40]),
                  Candidate(confidence=.8, bounding_box=[50, 50, 90, 90])]
    with TestClient(setup(tmp_path, TestDetector(candidates))) as client:
        job = wait(client, send(client).json()['data']['id'])
        image = job['images'][0]
        payload = {'image_ids': [image['id']]}
        assert client.post('/api/images/reject-and-delete', json=payload).status_code == 401
        assert client.get('/api/detections').json()['total'] == 2
        response = client.post('/api/images/reject-and-delete', json=payload, headers={'Authorization': 'Bearer test-secret'})
        assert response.status_code == 200, response.text
        assert response.json()['data']['deleted_photos'] == 1
        assert client.get('/api/detections').json()['total'] == 0
        assert client.get(image['original_url']).status_code == 404
        assert client.get(image['annotated_url']).status_code == 404
        with client.app.state.sessions() as session:
            submission = session.get(Submission, job['id'])
            assert (tmp_path / submission.path).is_file()


def test_reject_and_delete_does_not_modify_verified_images_and_rolls_back_on_io_error(tmp_path, monkeypatch):
    from backend.app import deletion
    candidates = [Candidate(confidence=.9, bounding_box=[5, 5, 40, 40]),
                  Candidate(confidence=.8, bounding_box=[50, 50, 90, 90])]
    headers = {'Authorization': 'Bearer test-secret'}
    with TestClient(setup(tmp_path, TestDetector(candidates))) as client:
        image = wait(client, send(client).json()['data']['id'])['images'][0]
        detection_id = image['detections'][0]['id']
        assert client.post(f'/api/detections/{detection_id}/verify', headers=headers).status_code == 200
        payload = {'image_ids': [image['id']]}
        response = client.post('/api/images/reject-and-delete', json=payload, headers=headers)
        assert response.status_code == 409
        statuses = [d['status'] for d in client.get('/api/detections').json()['data']]
        assert sorted(statuses) == ['pending', 'verified']
        assert client.post(f'/api/detections/{detection_id}/reset', headers=headers).status_code == 200
        def fail_move(*args):
            raise OSError('Test storage failure')
        monkeypatch.setattr(deletion, '_move_file', fail_move)
        response = client.post('/api/images/reject-and-delete', json=payload, headers=headers)
        assert response.status_code == 500
        assert all(d['status'] == 'pending' for d in client.get('/api/detections').json()['data'])
        assert client.get(image['original_url']).status_code == 200
