from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.database import Base


class ClusterTemplate(Base):
    __tablename__ = "cluster_templates"
    id:             Mapped[int]      = mapped_column(primary_key=True)
    name:           Mapped[str]      = mapped_column(String(64), unique=True)
    k8s_version:    Mapped[str]      = mapped_column(String(16))
    cp_flavor:      Mapped[str]      = mapped_column(String(64))
    worker_flavor:  Mapped[str]      = mapped_column(String(64))
    worker_count:   Mapped[int]      = mapped_column(Integer, default=3)
    description:    Mapped[str]      = mapped_column(Text, default="")
    created_by:     Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    creator:        Mapped["User"]   = relationship()
