"""Environment-only production settings. Legacy demo settings are not consulted."""
from pathlib import Path
from pydantic import Field
from .config import Config, ROOT


class PublicConfig(Config):
    data_dir: Path = ROOT / "public-data"
    seed_demo: bool = False
    model_path: Path = ROOT / "best.pt"
    device: str = "cpu"
    confidence: float = Field(0.35, ge=0.01, le=1)
    max_upload_mb: int = Field(100, ge=0, le=1024)
    max_video_seconds: float = Field(300, ge=0, le=3600)
    max_video_pixels: int = Field(3840 * 2160, ge=0, le=3840 * 2160)
    frame_interval: float = Field(3, ge=0.25, le=3600)
    max_frames: int = Field(100, ge=0, le=1000)
    workers: int = Field(2, ge=1, le=4)
    torch_threads: int = Field(2, ge=1, le=16)
    max_queue: int = Field(10, ge=0, le=100)
    client_active_jobs: int = Field(2, ge=0, le=20)
    client_daily_uploads: int = Field(30, ge=0)
    requests_per_minute: int = Field(120, ge=0)
    max_disk_mb: int = Field(10240, ge=0)
    retention_days: int = Field(0, ge=0)
    admin_token: str = ""
    client_hash_salt: str = ""
