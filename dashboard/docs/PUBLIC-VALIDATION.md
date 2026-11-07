# Public website validation

Executed on November 6, 2026, on branch `feat/public-turtle-website` in the separate `website/BoxTurtles` worktree. The original `/home/jaco/Main/BoxTurtles` checkout remained clean on `main`.

## Executed checks

| Check | Result |
| --- | --- |
| `python -m pytest tests -q` | **85 passed**. Existing local workflow tests plus 11 public API integration tests. One upstream Starlette/httpx deprecation warning. Temporary storage used for fixtures. |
| `npm run build` | Passed; production React/Vite frontend built. |
| `npm run build:legacy` | Passed; original frontend built separately into `dist-legacy`. |
| `npm run test:public` | **2 passed** against an isolated database and the actual local `best.pt`: image upload, no-detection results, restoration after refresh, gallery/map navigation and mobile viewport. |
| `scripts/verify_public.py --image .tools/turtle-test.jpg` | Passed with the actual checkpoint: 1 image detection, 0 blank-image detections, 2 video frames processed with 2 detections, results and JPEGs preserved across app restart. |
| `docker build -t boxturtles-public:test dashboard` | Passed with CPU PyTorch. |
| `docker run --rm boxturtles-public:test pip check` | Passed: no broken requirements. |
| Docker Compose startup with read-only filesystem, resource limits, persistent volume and read-only model mount | Passed; health check became healthy. |
| HTTP image/video uploads to the running Compose container | Passed with real model: 1 image detection, actual embedded EXIF GPS extracted, 0 blank-image detections, 2 sampled video frames and 2 video detections. |
| `docker compose restart app` followed by fetching the prior job and annotated image | Passed; SQLite records and generated media persisted. |
| Browser against the actual Compose container | Passed: real-model gallery, detail dialog, real EXIF GPS marker/popup, and marker-to-detail navigation; no browser page errors. |
| CPU and GPU Compose configuration parsing | Passed. GPU inference itself was not run. |
| `caddy validate --config /etc/caddy/Caddyfile` | Passed inside the official Caddy image. |
| `git diff --check` | Passed. |

The API tests exercise multiple objects and correct annotation positions, absent capture/GPS metadata, JPEG/PNG/WebP decoding, content/MIME mismatches, oversized files and streamed bodies, concurrent visitors, daily/active quotas, queue capacity, rate limits, disk limits, retention, interrupted/queued restart handling, protected administrator review/deletion, and responsive health/statistics requests while video inference is blocked in its worker. Test detectors are explicitly injected into test app factories; production has no fallback detector.

## Real model and fixture

Checkpoint: the user's supplied `best.pt`, copied unchanged into `dashboard/` and ignored by Git. SHA-256:

```text
31496e7d3b129a7593deba7777773cd440544423ddde812c55d9dd3430cfb141
```

The checkpoint reports the class `turtle`. One full-resolution test photograph produced confidence **0.6879455**; resized/compressed video frames have different scores. These smoke checks establish functional inference, not field accuracy, precision or recall.

The external test photograph was [Eastern Box Turtle close up](https://commons.wikimedia.org/wiki/File:Eastern_Box_Turtle_close_up.jpg), by DrStew82, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). It was downloaded only into ignored local test tooling. Test videos and annotated screenshots derived from this image remain local ignored artifacts, with the same attribution/license. No external photograph, derived video, weights, uploaded media or SQLite data is committed. GPS checks used the photograph's existing EXIF coordinates; no wildlife location was synthesized. All test detections remained unverified.

Local screenshots and machine-readable results are in ignored `dashboard/artifacts/`, including `public-desktop.png`, `public-mobile.png`, `public-gallery-real.png`, `public-detail-real.png`, `public-map-real.png`, `real-smoke.json` and `container-check.json`.

## Remaining deployment validation

No internet-facing service, DNS hostname or public certificate was provisioned. Live HTTPS issuance and external reachability require the destination Linux server/domain. NVIDIA GPU inference was not executed. The optional GPU override and Caddy configuration are provided, with these limits stated explicitly.

The application intentionally supports a single API process/replica with bounded internal worker threads. It has basic public-upload protections, not distributed abuse prevention. Native media decoding remains in-process; hostile workloads at larger scale should move into separately constrained worker processes. Server backup, disk monitoring, dependency updates and domain operations remain operator responsibilities.
