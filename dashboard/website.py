"""Build the local React UI if needed, then serve it with the Python API."""
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8000


def existing_server(host=HOST, port=PORT):
    """Recognize the dashboard before importing its app or touching its storage."""
    try:
        # Binding without listening checks availability without waiting for
        # Windows to reject a connection to a free port. Never share a live
        # listener's address on Windows; Unix reuse only avoids TIME_WAIT.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
        return None
    except OSError:
        pass
    try:
        # This is a loopback check; never send it through a configured proxy.
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://{host}:{port}/openapi.json", timeout=2) as response:
            schema = json.loads(response.read(2 * 1024 * 1024))
        if (schema.get("info", {}).get("title") == "Asian Baddies · Turtle Survey API"
                and {"/api/health", "/api/detections", "/api/settings"}.issubset(schema.get("paths", {}))):
            return "dashboard"
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return "other"


def main():
    os.chdir(ROOT)
    occupied = existing_server()
    if occupied == "dashboard":
        print(f"\nAsian Baddies is already running at http://{HOST}:{PORT}", flush=True)
        print("Open or refresh that page; another server is not needed.", flush=True)
        print("If you changed Python backend code, stop the existing server before restarting it.\n", flush=True)
        return 0
    if occupied:
        print(f"Port {PORT} is already in use by another application or an unresponsive server.", flush=True)
        print("Stop that application, then run website.py again. No server was stopped automatically.", flush=True)
        return 1
    try:
        import uvicorn
        import fastapi
        import sqlalchemy
    except ImportError:
        print("Install dependencies first: python -m pip install -r requirements.txt")
        return 1
    frontend = ROOT / "frontend"
    built = frontend / "dist-legacy" / "index.html"
    inputs = [frontend / "package.json", frontend / "package-lock.json", frontend / "index.html", frontend / "vite.config.js"]
    inputs += list((frontend / "src").rglob("*")) + list((frontend / "public").rglob("*"))
    stale = not built.exists() or any(p.is_file() and p.stat().st_mtime > built.stat().st_mtime for p in inputs)
    if stale:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm and os.name == "nt":
            portable = sorted((ROOT / ".tools").glob("node-*-win-x64/npm.cmd"))
            if portable:
                npm = str(portable[-1])
                os.environ["PATH"] = str(portable[-1].parent) + os.pathsep + os.environ.get("PATH", "")
        if not npm:
            print("Install Node.js 22 LTS, then run npm ci and npm run build inside frontend/.")
            return 1
        if not (frontend / "node_modules").exists():
            print("Frontend dependencies are missing. Run npm ci inside frontend/, then restart.")
            return 1
        print("Building the React dashboard…", flush=True)
        result = subprocess.run([npm, "run", "build:legacy"], cwd=frontend)
        if result.returncode:
            return result.returncode
    print("\nAsian Baddies is available at http://127.0.0.1:8000", flush=True)
    print("API docs: http://127.0.0.1:8000/docs · Press Ctrl+C to stop.\n", flush=True)
    # Import after building so FastAPI finds the production frontend.
    from backend.app.main import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
