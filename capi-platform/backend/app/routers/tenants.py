from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantOut
from app.services.auth import require_admin, get_current_user
from kubernetes import client as k8s_client

router = APIRouter()


@router.get("/", response_model=list[TenantOut])
async def list_tenants(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    res = await db.execute(select(Tenant))
    return res.scalars().all()


@router.post("/", response_model=TenantOut)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    # create k8s namespace
    v1 = k8s_client.CoreV1Api()
    try:
        v1.create_namespace(k8s_client.V1Namespace(metadata=k8s_client.V1ObjectMeta(name=body.namespace)))
    except Exception:
        pass
    t = Tenant(**body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@router.post("/{tenant_id}/assign")
async def assign_tenant(
    tenant_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Assign a tenant to a user (admin only)."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(404, "User not found")
    await db.execute(update(User).where(User.id == user_id).values(tenant_id=tenant_id))
    await db.commit()
    return {"assigned": {"user_id": user_id, "tenant_id": tenant_id}}
