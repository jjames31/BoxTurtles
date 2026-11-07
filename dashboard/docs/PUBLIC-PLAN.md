# Public website implementation

Preserve the original local application (`backend.app.main`, `src/App.jsx`) while validating a new production entrypoint (`backend.app.public`, `src/PublicApp.jsx`). Reuse database models, image orientation and validation, provenance, crop/annotation generation, and Leaflet.

1. Load the administrator-provided best.pt once; no demo fallback, model registration, live sources or automatic verification in the public server.
2. Persist uploads and jobs in SQLite; bound queue, workers, per-client quotas, request bodies, video duration and storage. Resume queued jobs and explicitly fail interrupted work on restart.
3. Build four responsive pages with progress, results including empty results, gallery and GPS map.
4. Provide CPU Docker, optional GPU override, Caddy HTTPS, persistent storage and deployment documentation.
5. Execute existing and new backend tests, actual model inference, frontend build, browser checks and Docker checks where available. Record unverified checks honestly.
