from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id:         Mapped[int]      = mapped_column(primary_key=True)
    user_id:    Mapped[int]      = mapped_column(ForeignKey("users.id"))
    action:     Mapped[str]      = mapped_column(String(64))
    resource:   Mapped[str]      = mapped_column(String(128))
    details:    Mapped[str]      = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user:       Mapped["User"]   = relationship()
