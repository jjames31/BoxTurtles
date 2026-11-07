import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileImage,
  Film,
  LayoutDashboard,
  LayoutGrid,
  LoaderCircle,
  Map as MapIcon,
  MapPin,
  Menu,
  ScanLine,
  Search,
  ShieldCheck,
  UploadCloud,
  Trash2,
  X,
} from "lucide-react";
import MapView from "./MapView.jsx";

const NAV = [
  ["dashboard", "Overview", LayoutDashboard],
  ["upload", "Upload media", UploadCloud],
  ["detections", "Detections", LayoutGrid],
  ["map", "Detection map", MapIcon],
];
const pct = (n) => `${(n * 100).toFixed(1)}%`;
const stamp = (value) =>
  value
    ? /([+-]\d\d:\d\d|Z)$/.test(value)
      ? new Date(value).toLocaleString()
      : `${value.replace("T", " ")} · timezone unknown`
    : "Capture time unavailable";
async function api(path, options) {
  const response = await fetch(`/api${path}`, options);
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(
      body.error?.message || "Request failed. Please try again.",
    );
    error.status = response.status;
    throw error;
  }
  return body;
}
function Mark() {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <ellipse cx="24" cy="26" rx="12" ry="13" />
        <path d="M21 13V8q3-5 6 0v5m-11 5-6-5m22 5 6-5M16 34l-6 5m22-5 6 5m-14 0v4m0-24 6 4v7l-6 4-6-4v-7z" />
      </g>
    </svg>
  );
}
function Empty({ title, children }) {
  return (
    <div className="empty">
      <ScanLine size={30} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function Badge({ status = "pending" }) {
  return (
    <span className={`badge ${status}`}>
      {status === "verified"
        ? "Verified sighting"
        : status === "rejected"
          ? "Rejected"
          : "Unverified detection"}
    </span>
  );
}
function Card({ item, onOpen }) {
  return (
    <button className="card" onClick={() => onOpen(item)}>
      <div className="card-image">
        <img
          loading="lazy"
          src={item.annotated_url}
          alt={`${item.class_name} with detection bounding box`}
        />
        <span className="confidence">{pct(item.confidence)}</span>
      </div>
      <div className="card-body">
        <div className="between">
          <h3>{item.class_name}</h3>
          <Badge status={item.status} />
        </div>
        <p className="truncate">{item.filename}</p>
        <div className="card-meta">
          <span>
            <MapPin size={13} />
            {item.latitude != null ? "GPS available" : "GPS unavailable"}
          </span>
          <span>{stamp(item.captured_at)}</span>
        </div>
      </div>
    </button>
  );
}
function Detail({ item, onClose, onDeleted, adminToken, onAdminTokenChange }) {
  const dialog = useRef(null);
  const [original, setOriginal] = useState(false);
  const [token, setToken] = useState(adminToken || "");
  const [authenticated, setAuthenticated] = useState(Boolean(adminToken));
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const normalizedToken = token.trim().replace(/^Bearer\s+/i, "");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState(item.status);
  useEffect(() => {
    dialog.current.showModal();
  }, []);
  function reportError(error) {
    setMessage(error.message);
    if ([401, 503].includes(error.status)) {
      setAuthenticated(false);
      onAdminTokenChange("");
    }
  }
  async function authenticate() {
    setBusy(true);
    setMessage("");
    try {
      await api("/admin/check", {
        method: "POST",
        headers: { Authorization: `Bearer ${normalizedToken}` },
      });
      setAuthenticated(true);
      setToken(normalizedToken);
      onAdminTokenChange(normalizedToken);
      setMessage("Administrator actions unlocked.");
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(false);
    }
  }
  async function review(action) {
    setBusy(true);
    setMessage("");
    try {
      const response = await api(`/detections/${item.id}/${action}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${normalizedToken}` },
      });
      setStatus(response.data.status);
      setConfirmDelete(false);
      setMessage("Review saved.");
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(false);
    }
  }
  async function deleteImage() {
    setBusy(true);
    setMessage("");
    try {
      await api("/images/reject-and-delete", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${normalizedToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ image_ids: [item.image_id] }),
      });
      onDeleted();
    } catch (error) {
      reportError(error);
    } finally {
      setBusy(false);
    }
  }
  const offset = item.metadata?.provenance?.video_frame?.offset_seconds;
  return (
    <dialog ref={dialog} className="detail" onCancel={onClose}>
      <div className="between">
        <div>
          <span className="eyebrow">DETECTION DETAILS</span>
          <h2>
            {item.class_name} <small>{pct(item.confidence)}</small>
          </h2>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close detection details"
        >
          <X />
        </button>
      </div>
      <div className="tabs">
        <button
          onClick={() => setOriginal(false)}
          className={!original ? "active" : ""}
        >
          Annotated
        </button>
        <button
          onClick={() => setOriginal(true)}
          className={original ? "active" : ""}
        >
          Original
        </button>
      </div>
      <img
        className="detail-image"
        src={original ? item.original_url : item.annotated_url}
        alt={
          original ? "Original uploaded frame" : "Detection with bounding box"
        }
      />
      <div className="detail-grid">
        <div>
          <label>Review status</label>
          <Badge status={status} />
        </div>
        <div>
          <label>Model</label>
          <strong>{item.model_name}</strong>
        </div>
        <div>
          <label>GPS coordinates</label>
          <strong>
            {item.latitude != null
              ? `${item.latitude.toFixed(6)}, ${item.longitude.toFixed(6)}`
              : "Unavailable"}
          </strong>
        </div>
        <div>
          <label>Capture time</label>
          <strong>{stamp(item.captured_at)}</strong>
        </div>
        <div>
          <label>Uploaded</label>
          <strong>{stamp(item.uploaded_at)}</strong>
        </div>
        <div>
          <label>
            {offset != null ? "Video timestamp" : "Processing time"}
          </label>
          <strong>
            {offset != null
              ? `${offset.toFixed(2)} seconds`
              : `${item.metadata?.processing_ms ?? "—"} ms`}
          </strong>
        </div>
      </div>
      <p className="hint">
        Public submissions are unverified. GPS may come from embedded metadata
        or user input; it is never estimated.
      </p>
      <details>
        <summary>Administrator review</summary>
        <label>
          Administrator token
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
              setAuthenticated(false);
              onAdminTokenChange("");
              setConfirmDelete(false);
              setMessage("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && normalizedToken && !busy) {
                event.preventDefault();
                authenticate();
              }
            }}
          />
        </label>
        <button
          className="button secondary"
          disabled={!normalizedToken || busy}
          onClick={authenticate}
        >
          {busy
            ? "Working…"
            : authenticated
              ? "Check token"
              : "Unlock admin actions"}
        </button>
        {authenticated && (
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => {
              setToken("");
              setAuthenticated(false);
              onAdminTokenChange("");
              setConfirmDelete(false);
              setMessage("Administrator actions locked.");
            }}
          >
            Lock admin actions
          </button>
        )}
        <p className="hint">
          The token is remembered in this page’s memory until you refresh or
          close it.
        </p>
        {authenticated && (
          <div className="actions">
            {(status === "pending" ? ["verify", "reject"] : ["reset"]).map(
              (action) => (
                <button
                  className="button secondary"
                  key={action}
                  disabled={busy}
                  onClick={() => review(action)}
                >
                  {action === "verify"
                    ? "Verify sighting"
                    : action === "reject"
                      ? "Reject"
                      : "Return to pending"}
                </button>
              ),
            )}
            {status !== "verified" && (
              <button
                className="button danger"
                disabled={busy}
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 size={15} />
                {status === "rejected"
                  ? "Delete image"
                  : "Reject & delete image"}
              </button>
            )}
          </div>
        )}
        {authenticated && confirmDelete && (
          <section
            className="delete-confirmation"
            role="group"
            aria-label="Confirm image deletion"
          >
            <h3>Delete this image?</h3>
            <p>
              This rejects all pending detections in this selected image and
              permanently removes its saved image, crops and previews. Images
              with verified detections cannot be deleted. Raw uploads and source
              videos are retained.
            </p>
            <div className="actions">
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setConfirmDelete(false)}
              >
                Cancel deletion
              </button>
              <button
                className="button danger"
                disabled={busy}
                onClick={deleteImage}
              >
                Confirm reject and delete
              </button>
            </div>
          </section>
        )}
        <p role="status">{message}</p>
      </details>
    </dialog>
  );
}
function Upload({ health, onComplete, onOpen }) {
  const input = useRef(null),
    xhr = useRef(null);
  const [file, setFile] = useState(null),
    [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0),
    [job, setJob] = useState(() => {
      try {
        const id = sessionStorage.getItem("boxturtles-job");
        return id ? { id } : null;
      } catch {
        return null;
      }
    }),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(() => {
      try {
        return !!sessionStorage.getItem("boxturtles-job");
      } catch {
        return false;
      }
    }),
    [error, setError] = useState("");
  const [latitude, setLatitude] = useState(""),
    [longitude, setLongitude] = useState(""),
    [capture, setCapture] = useState("");
  const limits = health?.limits;
  function choose(value) {
    if (!busy) {
      setFile(value);
      setError("");
      setJob(null);
      try {
        sessionStorage.removeItem("boxturtles-job");
      } catch {}
      setOffset(0);
      setProgress(0);
    }
  }
  useEffect(() => () => xhr.current?.abort(), []);
  useEffect(() => {
    if (!job?.id) return;
    let active = true,
      timer;
    async function poll() {
      try {
        const response = await api(`/jobs/${job.id}?offset=${offset}`);
        if (!active) return;
        setJob(response.data);
        setTotal(response.total);
        setError("");
        if (["completed", "failed"].includes(response.data.status)) {
          setBusy(false);
          onComplete();
        } else timer = setTimeout(poll, 1800);
      } catch (err) {
        if (active) {
          if (err.status === 404) {
            setBusy(false);
            setJob(null);
            try {
              sessionStorage.removeItem("boxturtles-job");
            } catch {}
            setError(
              "This job is no longer available. Choose a file to start again.",
            );
          } else {
            setError(`Could not refresh job: ${err.message} Retrying…`);
            timer = setTimeout(poll, 5000);
          }
        }
      }
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job?.id, offset, onComplete]);
  function submit(event) {
    event.preventDefault();
    setError("");
    if (!file) return;
    if (limits?.upload_mb && file.size > limits.upload_mb * 1024 ** 2) {
      setError(`File exceeds ${limits.upload_mb} MB.`);
      return;
    }
    if ((latitude === "") !== (longitude === "")) {
      setError("Enter both GPS coordinates or leave both empty.");
      return;
    }
    const metadata = {};
    if (latitude !== "") {
      metadata.latitude = Number(latitude);
      metadata.longitude = Number(longitude);
    }
    if (capture) {
      if (!Number.isFinite(Date.parse(capture))) {
        setError("Enter a valid ISO capture timestamp.");
        return;
      }
      metadata.captured_at = capture;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("metadata", JSON.stringify(metadata));
    const request = new XMLHttpRequest();
    xhr.current = request;
    request.open("POST", "/api/upload");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        setProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      let body;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = {};
      }
      if (request.status >= 200 && request.status < 300) {
        setJob(body.data);
        try {
          sessionStorage.setItem("boxturtles-job", body.data.id);
        } catch {}
        setOffset(0);
      } else {
        setBusy(false);
        setError(body.error?.message || "Upload failed. Please try again.");
      }
    };
    request.onerror = () => {
      setBusy(false);
      setError("Connection lost. Check your connection and try again.");
    };
    request.onabort = () => setBusy(false);
    setBusy(true);
    request.send(form);
  }
  return (
    <>
      <div className="upload-layout">
        <form className="panel upload-panel" onSubmit={submit}>
          <div className="section-title">
            <span className="step">01</span>
            <div>
              <h2>Add your media</h2>
              <p>One image or video. We’ll take a closer look.</p>
            </div>
          </div>
          <input
            ref={input}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,.mp4,.mov"
            hidden
            onChange={(event) => choose(event.target.files[0])}
          />
          <button
            type="button"
            className={`dropzone ${dragging ? "dragging" : ""}`}
            disabled={busy}
            onClick={() => input.current.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              choose(event.dataTransfer.files[0]);
            }}
          >
            <div className="upload-icon">
              <UploadCloud size={30} />
            </div>
            <h3>{file ? file.name : "Drop a little discovery here"}</h3>
            <p>
              {file
                ? `${(file.size / 1024 ** 2).toFixed(2)} MB · Click to choose another file`
                : "Drag and drop a file, or browse your files"}
            </p>
            <span className="format-list">JPG · PNG · WEBP · MP4 · MOV</span>
          </button>
          <details className="metadata">
            <summary>
              Capture metadata <span>Optional</span>
            </summary>
            <p className="hint">
              Only enter known capture information. Image EXIF and supported
              video tags are read automatically. Uploaded coordinates remain
              unverified.
            </p>
            <div className="form-grid">
              <label>
                Latitude
                <input
                  type="number"
                  step="any"
                  min="-90"
                  max="90"
                  value={latitude}
                  onChange={(e) => setLatitude(e.target.value)}
                  placeholder="e.g. 35.9200"
                />
              </label>
              <label>
                Longitude
                <input
                  type="number"
                  step="any"
                  min="-180"
                  max="180"
                  value={longitude}
                  onChange={(e) => setLongitude(e.target.value)}
                  placeholder="e.g. -78.9500"
                />
              </label>
            </div>
            <label>
              Original capture timestamp
              <input
                value={capture}
                onChange={(e) => setCapture(e.target.value)}
                placeholder="2026-11-06T14:30:00-05:00"
              />
            </label>
          </details>
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          <button
            className="button primary wide"
            disabled={!file || busy || health?.status !== "ready"}
          >
            {busy ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <ScanLine size={17} />
            )}{" "}
            {busy ? "Processing your media…" : "Find turtles"}
          </button>
          {busy && (
            <div className="progress-area" role="status">
              <div className="between">
                <span>
                  {!job
                    ? progress === 100
                      ? "Validating media"
                      : "Uploading"
                    : job.status === "queued"
                      ? "Waiting in queue"
                      : `Processing ${job.processed_frames} of ${job.total_frames || "…"} frames`}
                </span>
                <strong>
                  {!job
                    ? `${progress}%`
                    : job.total_frames
                      ? `${Math.round((job.processed_frames / job.total_frames) * 100)}%`
                      : ""}
                </strong>
              </div>
              <progress
                max="100"
                value={
                  !job
                    ? progress
                    : job.total_frames
                      ? (job.processed_frames / job.total_frames) * 100
                      : 0
                }
              />
            </div>
          )}
        </form>
        <aside className="upload-aside">
          <div className="panel">
            <div className="aside-icon">
              <CircleHelp />
            </div>
            <h3>A few field notes</h3>
            <p>
              Clear, well-lit images give the model the best chance of spotting
              a turtle.
            </p>
            <ul>
              <li>
                {limits?.upload_mb === 0
                  ? "No file-size limit"
                  : `Up to ${limits?.upload_mb ?? "…"} MB per upload`}
              </li>
              <li>
                {limits?.video_seconds === 0
                  ? "No video-duration limit"
                  : `Videos up to ${limits?.video_seconds ?? "…"} seconds`}
              </li>
              <li>
                One video frame sampled every {limits?.frame_interval ?? "…"}{" "}
                seconds
              </li>
              <li>Multiple turtles can be detected in one frame</li>
            </ul>
          </div>
          <div className="privacy-note">
            <ShieldCheck size={19} />
            <p>
              Uploads and detection results are public.{" "}
              {limits?.retention_days
                ? `Media is retained for ${limits.retention_days} days.`
                : "Media is retained until an administrator removes eligible records."}{" "}
              Only upload media you have permission to share.
            </p>
          </div>
        </aside>
      </div>
      {job && ["completed", "failed"].includes(job.status) && (
        <section className="panel results">
          <div className="between">
            <div>
              <span className="eyebrow">YOUR RESULTS</span>
              <h2>
                {job.status === "failed"
                  ? "Processing could not finish"
                  : job.detections_created
                    ? `${job.detections_created} detections found`
                    : "No turtles detected"}
              </h2>
              <p>
                {job.processed_frames} frames processed ·{" "}
                {((job.settings_snapshot?.processing_ms || 0) / 1000).toFixed(
                  2,
                )}{" "}
                seconds
              </p>
            </div>
            <span className="status-dot">{job.status}</span>
          </div>
          {job.error && (
            <p className="error" role="alert">
              {job.error}
            </p>
          )}
          {job.warnings?.map((w) => (
            <p key={w} className="hint">
              {w}
            </p>
          ))}
          {job.images?.map((image) => (
            <div className="frame-result" key={image.id}>
              <h3>{image.filename}</h3>
              <div className="result-images">
                <figure>
                  <img src={image.original_url} alt="Original frame" />
                  <figcaption>Original</figcaption>
                </figure>
                <figure>
                  <img
                    src={image.annotated_url}
                    alt="All detected objects with bounding boxes"
                  />
                  <figcaption>
                    Annotated · {image.detections.length} detections
                  </figcaption>
                </figure>
              </div>
              <div className="actions">
                {image.detections.map((detection) => (
                  <button
                    key={detection.id}
                    className="button secondary"
                    onClick={() => onOpen(detection)}
                  >
                    {detection.class_name} · {pct(detection.confidence)}{" "}
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
              {!image.detections.length && (
                <p className="hint">No turtles detected in this frame.</p>
              )}
            </div>
          ))}
          <Pager offset={offset} total={total} onChange={setOffset} />
        </section>
      )}
    </>
  );
}
function Pager({ offset, total, onChange }) {
  return (
    total > 24 && (
      <div className="pagination">
        <span>
          {offset + 1}–{Math.min(offset + 24, total)} of {total}
        </span>
        <button
          className="icon-button"
          disabled={!offset}
          onClick={() => onChange(offset - 24)}
          aria-label="Previous page"
        >
          <ChevronLeft />
        </button>
        <button
          className="icon-button"
          disabled={offset + 24 >= total}
          onClick={() => onChange(offset + 24)}
          aria-label="Next page"
        >
          <ChevronRight />
        </button>
      </div>
    )
  );
}
export default function PublicApp() {
  const [page, setPage] = useState(() =>
    NAV.some(([key]) => key === location.hash.slice(1))
      ? location.hash.slice(1)
      : "dashboard",
  );
  const [health, setHealth] = useState(null),
    [stats, setStats] = useState(null),
    [records, setRecords] = useState([]),
    [total, setTotal] = useState(0);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [selected, setSelected] = useState(null),
    [mobile, setMobile] = useState(false);
  const [adminToken, setAdminToken] = useState("");
  const [uploadRevision, setUploadRevision] = useState(0);
  const [status, setStatus] = useState(""),
    [offset, setOffset] = useState(0),
    [search, setSearch] = useState("");
  function navigate(value) {
    setPage(value);
    location.hash = value;
    setMobile(false);
    setOffset(0);
    setError("");
  }
  useEffect(() => {
    const listener = () => {
      const key = location.hash.slice(1);
      if (NAV.some(([id]) => id === key)) {
        setPage(key);
        setOffset(0);
      }
    };
    addEventListener("hashchange", listener);
    return () => removeEventListener("hashchange", listener);
  }, []);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, d, h] = await Promise.all([
        api("/stats"),
        api(
          `/detections?limit=24&offset=${offset}${status ? `&status=${status}` : ""}${page === "map" ? "&gps=true" : ""}`,
        ),
        fetch("/api/health").then((r) => r.json()),
      ]);
      setStats(s.data);
      setRecords(d.data);
      setTotal(d.total);
      setHealth(h.data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [offset, status, page]);
  useEffect(() => {
    load();
  }, [load]);
  const completed = useCallback(() => {
    api("/stats")
      .then((result) => setStats(result.data))
      .catch(() => {});
  }, []);
  const filtered = records.filter((x) =>
    `${x.filename} ${x.class_name}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const titles = {
    dashboard: [
      "A closer look at the wild.",
      "Small discoveries. A bigger picture for turtle conservation.",
    ],
    upload: [
      "Every discovery starts here.",
      "Upload a photo or video. Let your trained model do the looking.",
    ],
    detections: [
      "Your discoveries, collected.",
      "Explore model detections and their original capture details.",
    ],
    map: [
      "Discoveries in the field.",
      "Real coordinates, recorded in context. Never estimated.",
    ],
  };
  return (
    <div className="app">
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <a
          className="brand"
          href="#dashboard"
          onClick={() => navigate("dashboard")}
        >
          <span className="brand-mark">
            <Mark />
          </span>
          <span>
            BoxTurtles<small>FIELD INTELLIGENCE</small>
          </span>
        </a>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {NAV.map(([id, label, Icon]) => (
            <a
              key={id}
              href={`#${id}`}
              onClick={() => navigate(id)}
              className={page === id ? "active" : ""}
            >
              <Icon size={19} />
              {label}
              {id === "detections" && stats?.total > 0 && (
                <span className="nav-count">{stats.total}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="conservation-mark">
            <Mark />
          </div>
          <h3>
            Small turtles.
            <br />
            Meaningful discoveries.
          </h3>
          <p>A clearer view of the wildlife around us.</p>
          <div className="model-state">
            <span
              className={health?.status === "ready" ? "dot" : "dot amber"}
            />
            {health?.status === "ready"
              ? "Detection model ready"
              : "Model unavailable"}
            <small>best.pt · {health?.device || "Check server"}</small>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              onClick={() => setMobile(!mobile)}
              aria-label="Toggle navigation"
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{NAV.find((x) => x[0] === page)?.[1]}</strong>
          </div>
          <span className="public-label">
            <span className="dot" />
            Public workspace
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="tiny-line" /> TURTLE DETECTION & MONITORING
              </div>
              <h1>{titles[page][0]}</h1>
              <p>{titles[page][1]}</p>
            </div>
            {page !== "upload" && (
              <button
                className="button primary"
                onClick={() => navigate("upload")}
              >
                <UploadCloud size={17} /> Upload media
              </button>
            )}
          </div>
          {error && (
            <div className="error" role="alert">
              {error}
              <button className="button secondary" onClick={load}>
                Retry
              </button>
            </div>
          )}
          {health?.error && (
            <div className="error" role="alert">
              {health.error} Ask the administrator to check dashboard/best.pt
              and restart the server.
            </div>
          )}
          {page === "dashboard" && (
            <>
              <div className="stats-grid">
                {[
                  [
                    "Total detections",
                    stats?.total,
                    ScanLine,
                    "Model candidates across all media",
                  ],
                  [
                    "Images processed",
                    stats?.images,
                    FileImage,
                    "Completed image uploads",
                  ],
                  [
                    "Videos processed",
                    stats?.videos,
                    Film,
                    "Completed video uploads",
                  ],
                  [
                    "Verified sightings",
                    stats?.verified,
                    ShieldCheck,
                    "Confirmed by an administrator",
                  ],
                ].map(([label, value, Icon, note]) => (
                  <div className="stat panel" key={label}>
                    <div className="between">
                      <span>{label}</span>
                      <div className="stat-icon">
                        <Icon size={19} />
                      </div>
                    </div>
                    <strong>
                      {value == null ? "—" : value.toLocaleString()}
                    </strong>
                    <small>{note}</small>
                  </div>
                ))}
              </div>
              <div className="overview-grid">
                <section className="panel activity-panel">
                  <div className="between">
                    <div>
                      <h2>Detection activity</h2>
                      <p>Detections by processing date · UTC</p>
                    </div>
                    <Activity size={19} />
                  </div>
                  {stats?.activity.length ? (
                    <div className="chart">
                      {stats.activity.map((item) => (
                        <div
                          className="chart-column"
                          key={item.date}
                          title={`${item.date}: ${item.count} detections`}
                        >
                          <span>{item.count}</span>
                          <i
                            style={{
                              height: `${Math.max(4, (item.count / Math.max(...stats.activity.map((x) => x.count))) * 125)}px`,
                            }}
                          />
                          <small>{item.date.slice(5)}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="chart-empty">
                      <Activity size={26} />
                      <p>Your detection activity will appear here.</p>
                    </div>
                  )}
                </section>
                <section className="field-note">
                  <span className="eyebrow">FROM THE FIELD</span>
                  <div className="field-art">
                    <Mark />
                  </div>
                  <h2>
                    A little patience.
                    <br />A new perspective.
                  </h2>
                  <p>
                    Turn your field photos and recordings into discoveries worth
                    a closer look.
                  </p>
                  <button onClick={() => navigate("upload")}>
                    Make your first discovery <ArrowRight size={16} />
                  </button>
                </section>
              </div>
              <div className="section-heading">
                <div>
                  <h2>Recent detections</h2>
                  <p>The latest candidates from your media</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => navigate("detections")}
                >
                  View all detections <ArrowRight size={15} />
                </button>
              </div>
              {records.length ? (
                <div className="gallery">
                  {records.slice(0, 3).map((item) => (
                    <Card key={item.id} item={item} onOpen={setSelected} />
                  ))}
                </div>
              ) : (
                <section className="panel">
                  <Empty
                    title={
                      loading
                        ? "Loading discoveries…"
                        : "A fresh start for your fieldwork"
                    }
                  >
                    Upload your first image or video to begin detecting turtles.
                    <br />
                    <button
                      className="button secondary"
                      onClick={() => navigate("upload")}
                    >
                      Upload your first media <ArrowRight size={15} />
                    </button>
                  </Empty>
                </section>
              )}
            </>
          )}
          {page === "upload" && (
            <Upload
              key={uploadRevision}
              health={health}
              onComplete={completed}
              onOpen={setSelected}
            />
          )}
          {["detections", "map"].includes(page) && (
            <>
              <div className="toolbar">
                <div className="search">
                  <Search size={17} />
                  <input
                    aria-label="Search this page"
                    placeholder="Search this page by filename or class"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <select
                  aria-label="Review status"
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value);
                    setOffset(0);
                  }}
                >
                  <option value="">All review statuses</option>
                  <option value="pending">Unverified detections</option>
                  <option value="verified">Verified sightings</option>
                  <option value="rejected">Rejected</option>
                </select>
                <span>
                  {total}{" "}
                  {page === "map" ? "detections with GPS" : "detections"}
                </span>
              </div>
              {loading && <p role="status">Loading detections…</p>}
              {page === "map" ? (
                <section className="panel map-panel">
                  <MapView
                    publicMode
                    records={filtered}
                    onOpen={(id) =>
                      setSelected(records.find((x) => x.id === id))
                    }
                  />
                  <p className="map-caption">
                    <MapPin size={15} />
                    Showing up to 24 GPS detections per page. Detections without
                    GPS are available in the gallery. Unverified locations are
                    not confirmed wildlife sightings.
                  </p>
                </section>
              ) : filtered.length ? (
                <div className="gallery">
                  {filtered.map((item) => (
                    <Card key={item.id} item={item} onOpen={setSelected} />
                  ))}
                </div>
              ) : (
                <section className="panel">
                  <Empty title="No detections in this view">
                    Try another filter or upload new media.
                  </Empty>
                </section>
              )}
              <Pager total={total} offset={offset} onChange={setOffset} />
            </>
          )}
          <footer>
            <span>
              <Mark /> BoxTurtles <span className="footer-divider">/</span>{" "}
              Built for a closer look.
            </span>
            <span>Model detections are candidates. Human review matters.</span>
          </footer>
        </main>
      </div>
      {selected && (
        <Detail
          item={selected}
          adminToken={adminToken}
          onAdminTokenChange={setAdminToken}
          onDeleted={() => {
            setSelected(null);
            setUploadRevision((value) => value + 1);
            load();
          }}
          onClose={() => {
            setSelected(null);
            load();
          }}
        />
      )}
    </div>
  );
}
