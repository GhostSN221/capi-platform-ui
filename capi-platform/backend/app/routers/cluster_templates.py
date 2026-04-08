from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sq_delete
from app.database import get_db
from app.models.template import ClusterTemplate
from app.schemas.cluster_template import ClusterTemplateCreate, ClusterTemplateOut
from app.services.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/", response_model=list[ClusterTemplateOut])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    res = await db.execute(select(ClusterTemplate).order_by(ClusterTemplate.created_at.desc()))
    return res.scalars().all()


@router.post("/", response_model=ClusterTemplateOut)
async def create_template(
    body: ClusterTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = ClusterTemplate(**body.model_dump(), created_by=user.id)
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = await db.get(ClusterTemplate, template_id)
    if not tpl:
        raise HTTPException(404, "Template not found")
    # Only the creator or an admin can delete
    if tpl.created_by != user.id and not user.is_admin:
        raise HTTPException(403, "Not allowed")
    await db.execute(sq_delete(ClusterTemplate).where(ClusterTemplate.id == template_id))
    await db.commit()
    return {"deleted": template_id}
