from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.models.audit import AuditLog
from app.models.tenant import Tenant
from app.services.auth import require_admin
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()


class UserWithTenant(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    tenant_id: int | None
    tenant_name: str | None
    tenant_namespace: str | None
    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: int
    user_id: int
    username: str
    action: str
    resource: str
    details: str
    created_at: datetime
    model_config = {"from_attributes": True}


@router.get("/users", response_model=list[UserWithTenant])
async def list_users(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    res = await db.execute(select(User))
    users = res.scalars().all()
    result = []
    for u in users:
        tenant_name = None
        tenant_namespace = None
        if u.tenant_id:
            t = await db.get(Tenant, u.tenant_id)
            if t:
                tenant_name = t.name
                tenant_namespace = t.namespace
        result.append(UserWithTenant(
            id=u.id,
            username=u.username,
            email=u.email,
            is_admin=u.is_admin,
            tenant_id=u.tenant_id,
            tenant_name=tenant_name,
            tenant_namespace=tenant_namespace,
        ))
    return result


@router.get("/audit", response_model=list[AuditLogOut])
async def audit_log(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    res = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)
    )
    entries = res.scalars().all()
    result = []
    for e in entries:
        u = await db.get(User, e.user_id)
        result.append(AuditLogOut(
            id=e.id,
            user_id=e.user_id,
            username=u.username if u else "unknown",
            action=e.action,
            resource=e.resource,
            details=e.details,
            created_at=e.created_at,
        ))
    return result
