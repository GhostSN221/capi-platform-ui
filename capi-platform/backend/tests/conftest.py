import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_FILE = ROOT / ".pytest-capi.db"

# Configure the app before any app module is imported.
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["POD_CIDR"] = "100.64.0.0/16"
os.environ["SERVICE_CIDR"] = "10.96.0.0/12"
os.environ.pop("KUBECONFIG", None)
os.environ.pop("OS_CLOUDS_YAML", None)

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def prepared_app():
    if DB_FILE.exists():
        DB_FILE.unlink()

    from app.config import settings
    from app.database import engine, init_db, seed_db
    from app.services.demo import enable_demo

    assert settings.demo_mode is True
    enable_demo()
    await init_db()
    await seed_db()

    yield

    await engine.dispose()
    if DB_FILE.exists():
        DB_FILE.unlink()


@pytest_asyncio.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def auth_headers(client):
    response = await client.post(
        "/api/auth/login",
        json={"username": "demo", "password": "demo"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
