from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool
from app.config import settings

_engine_kwargs = {}
if settings.database_url.startswith("sqlite"):
    # The test suite opens a new connection per operation and may use different
    # event loops; keeping pooled SQLite connections would bind them to a loop.
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, echo=False, **_engine_kwargs)
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
        # SQLite (used by the test suite) does not support ADD COLUMN IF NOT EXISTS.
        if engine.dialect.name == "postgresql":
            for table, col in [("clusters", "master_count"), ("cluster_templates", "master_count")]:
                try:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 1"))
                except Exception:
                    pass

async def seed_db():
    from app.models.template import ClusterTemplate
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

    if settings.demo_mode:
        await seed_demo_data()


DEMO_CLUSTERS = [
    {
        "name": "demo-prod",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.medium",
        "worker_flavor": "k8s.node.medium",
        "master_count": 3,
        "worker_count": 3,
        "status": "Ready",
    },
    {
        "name": "demo-staging",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 2,
        "status": "Provisioning",
    },
    {
        "name": "demo-dev",
        "k8s_version": "v1.30.13",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 1,
        "status": "Failed",
    },
]


async def seed_demo_data():
    """Create a deterministic demo tenant, admin user and clusters.

    Only runs when DEMO_MODE=true. It is idempotent so the container can be
    restarted without duplicating rows.
    """
    from app.models.audit import AuditLog
    from app.models.cluster import Cluster
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.auth import hash_password

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Tenant).where(Tenant.name == "demo"))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                name="demo",
                namespace="demo",
                os_cloud="demo-cloud",
                external_network_id="demo-external-network",
                clouds_yaml="# demo clouds.yaml\nclouds:\n  demo-cloud: {}\n",
            )
            session.add(tenant)
            await session.flush()

        result = await session.execute(select(User).where(User.username == "demo"))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                username="demo",
                email="demo@example.com",
                hashed_pw=hash_password("demo"),
                is_admin=True,
                tenant_id=tenant.id,
            )
            session.add(user)
            await session.flush()

        now = datetime.utcnow()
        for index, spec in enumerate(DEMO_CLUSTERS):
            result = await session.execute(select(Cluster).where(Cluster.name == spec["name"]))
            if result.scalar_one_or_none() is None:
                session.add(Cluster(
                    tenant_id=tenant.id,
                    created_at=now - timedelta(days=index + 1),
                    **spec,
                ))

        result = await session.execute(select(AuditLog).where(AuditLog.user_id == user.id))
        if result.first() is None:
            for index, spec in enumerate(DEMO_CLUSTERS):
                session.add(AuditLog(
                    user_id=user.id,
                    action="create",
                    resource=f"cluster/{spec['name']}",
                    details=f"version={spec['k8s_version']} workers={spec['worker_count']} (demo seed)",
                    created_at=now - timedelta(days=index + 1),
                ))

        await session.commit()

async def get_db():
    async with AsyncSessionLocal() as s:
        yield s
