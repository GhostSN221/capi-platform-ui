from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog


async def log_action(db: AsyncSession, user_id: int, action: str, resource: str, details: str = "") -> None:
    """Record an audit log entry."""
    entry = AuditLog(user_id=user_id, action=action, resource=resource, details=details or "")
    db.add(entry)
    await db.commit()
