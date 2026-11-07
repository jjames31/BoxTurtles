# BoxTurtles · Field Intelligence

A React/Vite and FastAPI website for public image/video uploads using your trained **`dashboard/best.pt`**. SQLite stores submissions, jobs and detections. Original uploads and generated previews persist on disk. Four pages provide an overview, uploads/results, a detection gallery and an interactive Leaflet map.

The production server never uses mock detections, downloads weights, registers arbitrary models or automatically verifies sightings. Missing or incompatible weights produce a visible error and HTTP 503 readiness; existing records remain readable. CPU is the default. Model class names come directly from the checkpoint. Video statistics count sampled-frame detections, **not unique animals**.

## Quick start with Docker (CPU)

From `dashboard/`, with Docker Engine and Compose installed:

```bash
cp .env.example .env
# Put your trusted best.pt in this directory. It is ignored by Git and Docker build.
docker compose up --build -d app
```

Open **http://localhost:8000**. If the original dashboard already uses port 8000, set `TURTLE_BIND_PORT=8001` in `.env` before starting and open port 8001 instead. The supplied Compose configuration binds the app to loopback. Check startup with `docker compose logs -f app` and `curl -f http://localhost:8000/api/health`. The health response includes model classes, device and configured limits. Startup reads the checkpoint once, creates an independent model copy per worker, and warms each copy. Two uploads can run inference simultaneously.

`best.pt` is mounted read-only; the named `turtle-data` volume contains SQLite, raw uploads and previews. Recreating the container preserves these files. `docker compose down` preserves volumes; **`down -v` deletes them**. Do not put untrusted `.pt` files on the server: model checkpoints are administrator-provided executable artifacts.

## Public HTTPS on your Linux server

1. Point a DNS hostname at your server and allow inbound TCP 80/443. Docker Engine and Compose must be installed.
2. Set `TURTLE_DOMAIN=your-hostname.example` in `.env`. Set a long random `TURTLE_ADMIN_TOKEN` if administrator review is needed; blank disables administrator actions.
3. Run `docker compose --profile https up --build -d`.
4. Visit `https://your-hostname.example`. Caddy obtains and renews HTTPS certificates. Check `docker compose logs app proxy` if startup fails.

No hosting account is created and no paid infrastructure is provisioned by this repository. Public DNS/server provisioning is a separate operational step.

The app trusts forwarded client addresses in the container command. **Keep port 8000 bound to loopback** and route internet traffic only through Caddy. Caddy overwrites `X-Forwarded-For` with the actual connecting address; do not expose the app directly or attach untrusted containers to its network. If adding another proxy/CDN, configure trusted proxy ranges and address handling explicitly before relying on per-client quotas. For direct local development, Uvicorn defaults to trusted loopback forwarding only; use `--no-proxy-headers` when no reverse proxy is used.

Caddy has no configured request-body size cap. Upload limits are controlled by the application environment. Docker bounds memory, CPU, process count and temporary storage; tune these for your hardware. Native decoder failures can fail a job; hostile workloads at larger scale should isolate media decoding in separate worker processes/containers.

## Local development

Python 3.12, Node.js 22 and FFmpeg/ffprobe are recommended. From `dashboard/`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-public.txt pytest httpx
cp .env.example .env
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python -m uvicorn backend.app.public:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open http://127.0.0.1:8000. For live frontend editing, run `npm run dev` in `frontend/` and open http://127.0.0.1:5173; Vite proxies API and generated media to port 8000. Local data defaults to `dashboard/public-data/`, isolated from the original application's `data/`. API docs: `/docs`.

## Configuration

**This checkout is configured without upload quotas or size/duration/queue/storage/rate caps.** Set any corresponding limit to `0` to disable it; positive values restore a cap. File validation, sampled-frame processing, worker concurrency and physical free-disk checks still apply. Existing hosts must restart the server to pick up these settings.

All settings are environment variables beginning with `TURTLE_`, or entries in `dashboard/.env`. Configuration and model replacement are administrator operations on the server; restart after changing them. There is no public model/configuration endpoint.

| Variable | Example configuration | Purpose |
| --- | --- | --- |
| `MODEL_PATH` | `dashboard/best.pt` | Trusted local checkpoint; Compose mounts `/app/best.pt` |
| `DATA_DIR` | `dashboard/public-data` | Persistent storage; `/data` in Docker |
| `DEVICE` | `cpu` | `cpu`, `auto` (CUDA if available), or GPU index such as `0` |
| `CONFIDENCE` | `0.35` | Inference threshold, 0.01–1 |
| `MAX_UPLOAD_MB` | `0` | Maximum bytes per file, in MiB |
| `MAX_VIDEO_SECONDS` | `0` | Maximum video duration |
| `MAX_VIDEO_PIXELS` | `0` | Maximum video frame area, up to 4K |
| `FRAME_INTERVAL` | `3` | Seconds between sampled video frames |
| `MAX_FRAMES` | `0` | Maximum sampled frames per video |
| `WORKERS` | `2` | Parallel jobs, 1–4; each worker owns an independent warmed model instance |
| `TORCH_THREADS` | `2` | CPU inference threads per model; bounds CPU contention between workers |
| `MAX_QUEUE` | `0` | Waiting capacity in addition to worker slots |
| `CLIENT_ACTIVE_JOBS` | `0` | Receiving, queued and processing submissions per client |
| `CLIENT_DAILY_UPLOADS` | `0` | Accepted uploads per hashed IP in a rolling 24 hours |
| `REQUESTS_PER_MINUTE` | `0` | API requests per client IP |
| `MAX_DISK_MB` | `0` | Admission/output storage budget; refuses work when full |
| `RETENTION_DAYS` | `0` | 0 preserves data; positive values permanently remove expired public submissions and their results |
| `ADMIN_TOKEN` | blank | Bearer token for review and selected rejected-photo deletion |
| `CLIENT_HASH_SALT` | persisted random value | Optional stable salt; raw IPs are not stored in SQLite |

Use the full name, e.g. `TURTLE_CONFIDENCE=0.5`. A positive retention policy is an explicit administrator decision to expire **all** results in those expired submissions, including verified detections. Default retention preserves everything. Zero limit settings mean unlimited, not zero permitted uploads. Storage budget checks cover the data directory and conservative output estimates; reserve additional capacity for SQLite journals, dependency caches and operating-system files. High-resolution images with many objects may be refused before annotations are written. Rejected uploads are removed; accepted failed jobs and partial results remain available until retention removes them.

Run **one Uvicorn process and one app replica** against this SQLite volume. Internal workers provide bounded concurrency. Each worker processes a separate upload; sampled frames within a single video stay in timestamp order. SQLite and file writes remain serialized for consistency. Parallel inference uses more memory than a single worker. Multiple replicas require a shared admission/queue implementation and database migration; do not scale Compose replicas or add Uvicorn workers.

Jobs are persisted before enqueueing. Queued jobs resume after restart. Jobs interrupted while receiving or processing are marked failed with an explanation; completed partial frames remain visible. Upload IDs are random, and raw uploads, database files, the client salt and model weights are never served publicly. Safe generated JPEGs are public.

## Optional NVIDIA GPU

Install a compatible NVIDIA driver and NVIDIA Container Toolkit on the host, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d app
```

The override installs CUDA PyTorch wheels and requests GPUs. `TURTLE_DEVICE=auto` selects CUDA when available; explicitly requesting CUDA without it produces a startup error. GPU deployment must be tested on the target host; CPU deployment needs no NVIDIA packages.

## Capture metadata and verification

Images use EXIF orientation before inference, so boxes and previews share the displayed pixel coordinate system. JPEG, PNG and WebP contents are decoded and checked against their declared type. MP4/MOV containers are checked and decoded, with duration/resolution limits. Video results include frame indices and elapsed video seconds. Known capture timestamps can be offset by frame time; unknown capture time remains null. Embedded video `creation_time` is labeled with its provenance and requires checking the camera clock.

Optional user-supplied GPS/capture metadata is labeled unverified. No location is generated and upload time never becomes capture time. The map displays only records with real stored coordinate pairs, 24 per page, and clearly labels unverified detections. Free OpenStreetMap tiles require network access; stored coordinates remain available if tiles fail. Public upload results are separate from administrator-verified sightings.

Open a detection, expand **Administrator review**, enter the token, and click **Unlock admin actions**. The validated token is held only in page memory across dialogs until you lock admin actions, refresh, or close the page; it is never persisted in browser storage. A missing server token gives a clear configuration error; an incorrect token gives an authentication error. A Docker deployment must recreate the app container after `.env` token changes (`docker compose --profile https up -d --force-recreate app`); restarting alone does not refresh container environment variables. Review transitions are conditional: a reviewed record must be reset before another review. The **Reject & delete image** button opens a confirmation panel. It atomically rejects all pending detections in that selected image and deletes its saved image/crops/previews. Verified detections block the operation without changing reviews. Source uploads and videos are retained. The authenticated API is `/api/images/reject-and-delete` with the same image-ID payload. For deletion of already rejected photos, authenticated administrators can POST `{"image_ids":["selected-image-uuid"]}` to `/api/images/delete-rejected` with `Authorization: Bearer <token>`. Every detection on each selected photo must already be rejected. Source videos and raw uploads are retained by this operation. Retention is the mechanism for expiring complete submissions.

Upload results include original and combined annotated frames, each object's class/confidence, processing duration and video progress. The latest job ID is saved in browser session storage so returning to Upload or refreshing resumes progress. An image/video with zero detections is a successful result with a clear “No turtles detected” message.

## Verification

```bash
.venv/bin/python -m pytest tests -q
npm --prefix frontend run build
# Requires your real checkpoint and an image that the model detects:
.venv/bin/python scripts/verify_public.py --image /path/to/turtle.jpg
# Browser checks start an isolated real-model server/database:
npm --prefix frontend run test:public
```

Tests use temporary storage. Injected detectors exist only in API tests; production always loads `best.pt`. Real verification performs image inference, a blank-image negative check, sampled-video inference and a restart persistence check. See [validation results](docs/PUBLIC-VALIDATION.md) for checks actually executed in this implementation.

## Original local dashboard

The original backend and frontend are retained for compatibility and demo use, with no model requirement. They are excluded from the public server's routes and UI. Run `npm --prefix frontend run build:legacy`, then `python website.py`. The legacy frontend builds to `frontend/dist-legacy`; the public build stays in `frontend/dist`. See [the original application documentation](docs/LEGACY.md). Keep the legacy server on loopback: it is a local application with unauthenticated administrative features. The original checkout and its data were not modified.

## Backup and operations

Stop the app, back up the complete named data volume, then restart. Restore the entire directory together, including SQLite, uploads, previews and `.client-salt`; copying only database files loses media. Use Docker volume inspection to locate the volume on the host. Preserve the read-only `best.pt` separately. Monitor `docker compose ps`, `/api/health`, free disk and logs. Dependency versions should be reviewed and rebuilt regularly. TLS/DNS renewal and off-host backups are the server operator's responsibility.
