from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import text
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

SEED_TEMPLATES = [
    {
        "name": "Dev - Small",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 1,
        "description": "Cluster dev léger — 1 master, 1 worker",
    },
    {
        "name": "Dev - Medium",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 2,
        "description": "Cluster dev standard — 1 master, 2 workers",
    },
    {
        "name": "Prod - Standard",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.medium",
        "worker_flavor": "k8s.node.medium",
        "master_count": 1,
        "worker_count": 3,
        "description": "Cluster production — 1 master, 3 workers HA",
    },
    {
        "name": "Prod - Large",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.medium",
        "worker_flavor": "k8s.node.large",
        "master_count": 1,
        "worker_count": 5,
        "description": "Cluster production haute capacité — 1 master, 5 workers",
    },
    {
        "name": "Database Cluster",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.large",
        "worker_flavor": "k8s.node.xlarge",
        "master_count": 3,
        "worker_count": 7,
        "description": "Cluster dédié bases de données — 3 masters HA, 7 workers",
    },
]

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, col in [("clusters", "master_count"), ("cluster_templates", "master_count")]:
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 1"))
            except Exception:
                pass

async def seed_db():
    from sqlalchemy import select
    from app.models.template import ClusterTemplate
    from datetime import datetime
    async with AsyncSessionLocal() as session:
        for tpl in SEED_TEMPLATES:
            result = await session.execute(
                select(ClusterTemplate).where(ClusterTemplate.name == tpl["name"])
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(ClusterTemplate(**tpl, created_by=None, created_at=datetime.utcnow()))
            else:
                existing.cp_flavor = tpl["cp_flavor"]
                existing.worker_flavor = tpl["worker_flavor"]
                existing.master_count = tpl.get("master_count", 1)
                existing.worker_count = tpl.get("worker_count", existing.worker_count)
        await session.commit()

async def get_db():
    async with AsyncSessionLocal() as s:
        yield s
