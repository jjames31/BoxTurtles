> Historical local-dashboard documentation. The public website now uses the default build. For this legacy application, replace frontend `npm run build` with `npm run build:legacy` and `npm run dev` with `npm run dev:legacy`. `website.py` automatically builds the legacy interface into `frontend/dist-legacy/`. Keep this server on loopback.

# Asian Baddies · Turtle survey workspace

A local, responsive turtle detection dashboard for **recorded DJI Avata 2 footage, uploaded photographs, and live model annotations from a shared scrcpy window**. Demo mode is the default and works without a drone, model file, PyTorch, or paid API.

## Start on this computer

On the existing development computer, the project-local Python environment, portable Node runtime, and production frontend are already prepared. From the local `BoxTurtleProject` directory in PowerShell:

In the GitHub repository, this application is in `dashboard/`; run the setup commands from that folder. The repository's training notebook remains separate from the website.

```powershell
.\.venv\Scripts\python.exe website.py
# Or: .\run.ps1
```

Open **http://127.0.0.1:8000**. API documentation is at **http://127.0.0.1:8000/docs**. Stop with Ctrl+C. The launcher rebuilds the frontend when its source changes; it never installs packages or downloads models automatically.

If the dashboard is already running, launching it again prints the existing address and exits successfully. It does not start a second server or touch the database. If another application occupies port 8000, the launcher explains the conflict and leaves that application running. To restart an existing dashboard after backend changes, stop its original server first.

After changing Python backend files, stop and restart `website.py` once, then refresh the browser. Refreshing alone can load new buttons while the previous API process is still running. If photo deletion reports an unsupported route, restart the backend before retrying; a missing route does not delete any files.

## Fresh installation: Windows

Install Python 3.11 or 3.12 and Node.js 22 LTS (22.12 or newer). Then:

```powershell
cd C:\path\to\BoxTurtles\dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe website.py
```

If Windows points `python` to a Store shortcut, use `py -3.12` or the full path to your installed interpreter. The portable tooling in `.tools/` is optional and specific to this development workspace.

## Fresh installation: Ubuntu or Linux Mint

With Python 3.11/3.12, the matching `python3-venv` package, and Node.js 22 LTS installed:

```bash
cd /path/to/BoxTurtles/dashboard
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python website.py
```

FFmpeg/`ffprobe` is optional for embedded video capture tags. Without it, video decoding and external telemetry still work, and missing tags are reported. H.264 MP4 is the most portable export choice for Avata 2 recordings; unsupported codecs produce a failed job with an explanation.

## Use the workspace

- **Dashboard:** detection totals, pending/verified/rejected counts, average confidence, recent sightings, review activity, and a location map.
- **Pending detections:** inspect the full frame, saved annotation, or crop; toggle boxes; confirm or reject. Rejected records remain available in the archive.
- **Verified sightings:** search by ID, filename, or coordinates; filter by capture date, confidence, and GPS availability; sort; export CSV; or return a mistaken verification to pending.
- **Turtle map:** OpenStreetMap/Leaflet markers for verified records with GPS. Marker popups open the sighting. Fit all markers with the expand button. Missing locations never become map markers.
- **Upload media:** multiple photographs or one video at a time, optional GPS/capture time, configurable frame sampling, external CSV/SRT telemetry, and processing progress.
- **Settings:** select the demo engine or a registered .pt model, change detection confidence and video defaults, optionally enable a separate automatic-acceptance threshold, and register more models by their backend-local paths.
- **Live feed:** share your existing scrcpy window through the desktop browser, preview it, then optionally start sampled local detection using the active model. Set a frame interval and session limit; stop sharing or leave the page to disconnect. Open the dashboard on the Ubuntu computer displaying scrcpy through localhost, loopback, or HTTPS. No OBS or MediaMTX is needed. See [Live feed setup](docs/LIVE_FEED.md).
- **Live YOLO:** watch continuously updated model boxes and confidence scores on the exact frames sent for inference. Target up to 10 frames/second, with one request at a time; actual speed depends on local inference. Preview does not save records by default. Enable **Save candidate frames** to retain frames containing candidates and apply the saved review policy. The existing window share is retained when switching between Live feed and Live YOLO.

Automatic acceptance is **off by default**. In Settings, enable **Automatically accept high-confidence turtles** and choose **Automatic acceptance threshold (%)** (95% by default). This threshold is separate from the lower detection threshold and must be at least as high. New genuine local YOLO turtle detections meeting it enter Verified sightings with an **Automatically accepted** label and the policy threshold recorded; other candidates remain pending. Demo/mock results and externally supplied detections are never automatically accepted. Existing pending records are not changed. Model confidence is a score, not a guarantee that a turtle is present; automatically accepted records remain available for inspection and correction.

The **Text size** menu in the top bar offers Standard, Large (default), and Extra large. The selection is saved in this browser. The interface uses larger labels, higher-contrast secondary text, larger controls, and responsive layouts on wide and small screens.

The **View** menu above the pending, verified, and rejected files offers small, medium, or large thumbnails and a compact list. Your browser remembers the choice. Open a file and use **Previous / Next** in the inspector header or the Left/Right arrow keys to browse the current results in their selected sort order. Navigation stays above the photo so it does not cover the image. The inspector shows your position, retains the frame/crop/annotation and box choices between files, and stops at the first and last result. New detections arriving during inspection appear in the collection when you close the inspector.

Use each file's checkbox or **Select all matching** to manage several detections together. Selection follows the current filters and remains selected when switching between thumbnails and list view. Pending items offer **Confirm selected / Reject selected**; verified or rejected items offer **Restore selected**. Individual reviews are saved independently; if one fails, successful reviews remain saved and the remaining selection can be retried.

In **Rejected archive**, **Delete selected photos** lists the affected original photos and the number of associated rejected detections before you confirm permanent removal. Every detection on a photo must be rejected, including candidates outside the current filter. Pending or verified siblings block deletion. The server rechecks this when you confirm and rejects the entire deletion batch if a photo's status changed. Selected originals, their original-byte copies, crops, and annotations are removed; unrelated photos, shared media, and source videos are kept. This action cannot be undone.

The **info buttons** beside frame sampling fields explain their units and effects. For the live feed, a **5-second frame interval** checks about **12 still frames per minute**, subject to processing speed. **Maximum frames per session** is a cap on sampled frames, not turtle candidates: a limit of 60 stops detection after at most 60 frames while keeping the preview available. Recorded-video sampling uses seconds of the original recording and has its own maximum-frame cap.

The **Light/Dark** button beside Text size switches the entire workspace theme. Dark is the default; your browser saves the choice. The Spotify-inspired layout uses neutral surfaces, a compact sidebar, rounded controls and a green accent. Dark mode pairs bright green primary buttons with dark text; light mode pairs deep green buttons with white text. Disabled controls remain readable. The map follows the selected theme; photos keep their original colors. Dashboard review actions remain available on mobile.

The capture-time timezone field can be left blank when the camera's timezone is unknown. The original local timestamp is preserved and flagged, rather than applying the computer's current offset. Failed files stay selected after a partial upload so they can be retried. See [the bug review](docs/QA_REVIEW.md) for the fixes and verification scope.

Updates appear immediately after review and refresh from the backend every five seconds while the browser is visible. The single local server serves both the UI and API. Uploaded files and SQLite records persist across restarts.

### Demo data

First startup seeds 12 synthetic detections: 7 pending, 4 verified, 1 rejected. The illustrations, coordinates, and capture times are explicitly marked **synthetic demo**. Uploaded photographs processed by the demo engine receive a fixed **87% simulated candidate**, subject to the confidence threshold; this does not inspect their contents or prove a turtle is present. Set a threshold above 87% to exercise the no-candidate case.

To generate an example photograph and a six-second recording:

```powershell
.\.venv\Scripts\python.exe scripts/create_example_data.py
```

Upload files in `examples/generated/`. The example telemetry files contain synthetic coordinates and timestamps; do not use them as real survey metadata.

For a fresh field database without seeded examples, set both of these in `.env` before startup:

```dotenv
TURTLE_DATA_DIR=./data-field
TURTLE_SEED_DEMO=false
```

Then select an actual model in Settings. Turning off seeding does not erase an existing database. Back up the whole configured data directory to preserve records and their images together.

### Enable local YOLO inference

Demo mode needs no ML packages. When you have a trusted local model:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-yolo.txt
```

Use the same Python environment that runs `website.py`. If it reports `No module named pip`, run `.\.venv\Scripts\python.exe -m ensurepip --upgrade`, then retry the install. After installation, restart the dashboard before selecting the model again. The same installation is described in the [Ultralytics setup guide](https://docs.ultralytics.com/quickstart/).

1. Open Settings and register its `.pt` path **on the computer running FastAPI**, name, and candidate class labels.
2. Select it, choose the threshold, and save. Activation loads the model and reports errors before changing the saved engine.
3. Upload new media. Inference runs locally on CPU; existing records keep their original model provenance.

Class matching is case insensitive. Use the exact labels in your model, such as `turtle` or `box turtle`; leaving labels empty accepts all classes. No training is required. Only load model files you trust. Models are never fetched by name or URL. The default adapter handles axis-aligned YOLO detection boxes; other output types need a separate adapter that emits the common candidate format.

### Capture metadata and telemetry

- JPEG/other supported EXIF images: GPS and `DateTimeOriginal` are read before orientation is normalized. `OffsetTimeOriginal` is preserved when available. A timezone-less original stays timezone-less and is flagged.
- Video: `ffprobe` inspects available creation/location tags. Their provenance is displayed; verify the camera clock before treating creation tags as survey time.
- Manual values override embedded image/video values. For video, a supplied timestamp means **recording start**; frame timestamps add the actual frame offset.
- External telemetry overrides matched frame fields. CSV columns: `offset_seconds,latitude,longitude,captured_at`. ISO timestamps can include `Z` or an explicit offset. Both coordinates must be supplied together.
- SRT supports explicit `latitude` and `longitude`/`longtitude` fields and recognizable timestamps. DJI subtitle formats differ; unsupported layouts are rejected with a CSV alternative, rather than guessed.
- Matching uses the nearest sample within two seconds by default, configurable with `TURTLE_TELEMETRY_TOLERANCE_SECONDS`. GPS is not interpolated. An absolute telemetry timestamp is adjusted by the frame-to-sample offset.
- Missing GPS/capture time remains null. Upload time and filesystem modification time are never substituted for capture time.
- New shared scrcpy frames record the browser's UTC timestamp at the instant the frame is copied from the preview, before JPEG encoding or upload. This appears as **Live frame captured**, with seconds and `browser frame capture` provenance. It uses the browser's clock and may differ from the camera's exposure time because the mirrored video can be delayed. GPS stays null. Explicit original camera metadata takes precedence when supplied; old records without a measured timestamp stay unchanged. CSV export includes `capture_time_source` to distinguish these timestamps.

See `examples/telemetry.csv`, `examples/telemetry.srt`, and [the interface specification](docs/ARCHITECTURE.md).

## Development and checks

For React hot reload, run FastAPI and Vite in separate terminals from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
# Other terminal:
cd frontend
npm run dev
```

Vite runs at http://127.0.0.1:5173 and proxies `/api` and `/media` to FastAPI. On Linux use `.venv/bin/python`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

The Playwright configuration starts its own backend on port 8011 with isolated data under `.tools/e2e-data/`; it does not review or upload into your normal database. On this computer, if Node is not on PATH, add the `.tools/node-*-win-x64` folder to PATH and set `PLAYWRIGHT_BROWSERS_PATH` to `.tools/browsers` before running browser tests. `requirements-lock.txt` records the exact Python packages validated in this workspace; `frontend/package-lock.json` locks the frontend.

## API

Successful responses use `{ "data": ... }`. Lists include pagination metadata where applicable. Errors use `{ "error": { "message": "...", "code": 422 } }`, with field details for request validation.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Local server/source status |
| `GET /api/detections?status=pending&limit=1000&offset=0` | Paginated candidates, all or by status |
| `GET /api/detections/{id}` | Candidate, media, provenance and metadata |
| `POST /api/detections/{id}/verify` | Pending → verified |
| `POST /api/detections/{id}/reject` | Pending → rejected |
| `POST /api/detections/{id}/reset` | Verified/rejected → pending |
| `POST /api/images/delete-rejected` | Permanently delete explicitly selected photos only when all their detections are rejected; JSON `{"image_ids":["UUID", "..."]}` (1–1000 IDs) |
| `GET /api/sightings` | Paginated verified detections |
| `GET /api/stats` | Aggregate statistics |
| `POST /api/upload` | Multipart image file + JSON `metadata` |
| `POST /api/upload/video` | Multipart video + optional metadata, telemetry, interval, frame limit |
| `POST /api/ingest/frame` | Multipart image + standardized JSON `envelope` |
| `POST /api/inference/frame` | Active-model prediction for one frame; multipart `file`, JSON `envelope`, optional `persist_candidates` (false by default); only frames with candidates are saved when enabled |
| `GET /api/jobs`, `GET /api/jobs/{id}` | Video job progress/errors |
| `GET /api/settings`, `PUT /api/settings` | Detection/video settings and optional automatic-acceptance policy |
| `GET /api/models`, `POST /api/models` | Register/selectable local models |
| `GET /api/live-source`, `PUT /api/live-source` | Legacy saved player configuration; unused by the current scrcpy capture page |

Repeated or conflicting reviews return **409**, rather than duplicate sightings. A reset is required before another review. The verified record references the same image and detection; files are not moved or duplicated during verification.

## Project structure

```text
BoxTurtleProject/
  backend/app/
    main.py          # HTTP routes, validation, static frontend
    db.py            # SQLite/SQLAlchemy entities and sessions
    schemas.py       # Model/drone independent frame contract
    engine.py        # Demo and lazy local YOLO adapters
    ingestion.py     # Frame storage, crops, annotations, video jobs
    metadata.py      # EXIF, video tags, CSV/SRT synchronization
    streams.py       # Legacy saved player configuration compatibility
    demo.py          # Offline synthetic fixtures
    config.py        # Environment configuration
  frontend/
    src/App.jsx      # Dashboard, review, sightings, uploads, settings
    src/MapView.jsx  # Leaflet map and sighting popups
    src/LiveFeed.jsx # Browser-shared scrcpy preview and sampled local detection
    src/api.js       # Shared API client
    src/styles.css   # Tailwind and responsive theme
    src/readability.css # Readable typography, text scale and layouts
    src/themes.css   # Shared light/dark palette and readable control states
    package.json, package-lock.json, vite.config.js
  tests/test_workflow.py
  frontend/tests/workflow.spec.js
  scripts/create_example_data.py
  examples/          # Telemetry, ingestion envelope, generated fixtures
  docs/              # Architecture and development progress
  data/              # Ignored local SQLite, media, videos
  website.py, run.ps1
  requirements*.txt, .env.example
```

This is a single-user local application bound to loopback, with no general account/login layer. `TURTLE_INGEST_TOKEN` can protect the frame-ingestion and frame-inference endpoints; if configured, enter it under **Advanced connection settings** in either live page. It is held only in page memory and does not authenticate other routes. Before exposing the app beyond this computer, add authentication, TLS, and appropriate network access controls.

Video jobs run in the local server process with per-frame commits. A restart marks unfinished jobs failed; completed frames remain reviewable, and the recording is retained for reprocessing. Re-uploading creates a new job and may create duplicate candidates for already-processed frames. Full durable job resumption and multi-user deployment are future extensions.

OpenStreetMap tiles require internet access and attribution; saved GPS records and marker popups remain available if tiles fail. The app makes no cloud AI calls, uses no paid API credentials, and provides no billing or credit-purchase flows. See [development progress](docs/PROGRESS.md) for validation and remaining integration work.
