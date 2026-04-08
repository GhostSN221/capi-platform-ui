from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

SEED_TEMPLATES = [
    {
        "name": "Dev - Small",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master",
        "worker_flavor": "k8s.node",
        "worker_count": 1,
        "description": "Cluster dev léger — 1 worker",
    },
    {
        "name": "Dev - Medium",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master",
        "worker_flavor": "k8s.node",
        "worker_count": 2,
        "description": "Cluster dev standard — 2 workers",
    },
    {
        "name": "Prod - Standard",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master",
        "worker_flavor": "k8s.node",
        "worker_count": 3,
        "description": "Cluster production — 3 workers HA",
    },
    {
        "name": "Prod - Large",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master",
        "worker_flavor": "sow-flavor",
        "worker_count": 5,
        "description": "Cluster production haute capacité — 5 workers",
    },
]

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def seed_db():
    from sqlalchemy import select, text
    from app.models.template import ClusterTemplate
    from datetime import datetime
    async with AsyncSessionLocal() as session:
        for tpl in SEED_TEMPLATES:
            exists = await session.execute(
                select(ClusterTemplate).where(ClusterTemplate.name == tpl["name"])
            )
            if exists.scalar_one_or_none() is None:
                session.add(ClusterTemplate(**tpl, created_by=None, created_at=datetime.utcnow()))
        await session.commit()

async def get_db():
    async with AsyncSessionLocal() as s:
        yield s
