"""Public submission provenance is isolated from legacy and demo records."""
from sqlalchemy import ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now


class Submission(Base):
    __tablename__ = "public_submissions"
    id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), primary_key=True)
    client: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    metadata_info: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now, index=True)
