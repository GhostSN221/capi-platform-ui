from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Tenant(Base):
    __tablename__ = "tenants"
    id:        Mapped[int] = mapped_column(primary_key=True)
    name:      Mapped[str] = mapped_column(String(64), unique=True)
    namespace: Mapped[str] = mapped_column(String(64), unique=True)
    os_cloud:            Mapped[str] = mapped_column(String(64))
    external_network_id: Mapped[str] = mapped_column(String(64), default="")
    clouds_yaml:         Mapped[str | None] = mapped_column(Text, nullable=True)
    users:     Mapped[list["User"]]    = relationship(back_populates="tenant")
    clusters:  Mapped[list["Cluster"]] = relationship(back_populates="tenant")
