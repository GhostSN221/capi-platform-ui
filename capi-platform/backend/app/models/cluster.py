from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.database import Base

class Cluster(Base):
    __tablename__ = "clusters"
    id:             Mapped[int]      = mapped_column(primary_key=True)
    name:           Mapped[str]      = mapped_column(String(64))
    tenant_id:      Mapped[int]      = mapped_column(ForeignKey("tenants.id"))
    k8s_version:    Mapped[str]      = mapped_column(String(16))
    cp_flavor:      Mapped[str]      = mapped_column(String(64))
    worker_flavor:  Mapped[str]      = mapped_column(String(64))
    worker_count:   Mapped[int]      = mapped_column(Integer, default=3)
    status:         Mapped[str]      = mapped_column(String(32), default="Provisioning")
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tenant:         Mapped["Tenant"] = relationship(back_populates="clusters")
