from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"
    id:        Mapped[int]  = mapped_column(primary_key=True)
    username:  Mapped[str]  = mapped_column(String(64), unique=True, index=True)
    email:     Mapped[str]  = mapped_column(String(128), unique=True)
    hashed_pw: Mapped[str]  = mapped_column(String(128))
    is_admin:  Mapped[bool] = mapped_column(Boolean, default=False)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    tenant:    Mapped["Tenant"] = relationship(back_populates="users")
