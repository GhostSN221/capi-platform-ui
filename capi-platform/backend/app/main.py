import os, subprocess
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.routers import auth, clusters, tenants, templates, setup
from app.routers import cluster_templates, admin
from app.database import init_db, seed_db

# Import all models so SQLAlchemy registers them with Base.metadata before create_all
import app.models  # noqa: F401

app = FastAPI(title="CAPI Platform", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
jinja = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

try:
    _git_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
    ).decode().strip()
except Exception:
    _git_hash = "1"

jinja.env.globals["asset_v"] = _git_hash

@app.on_event("startup")
async def startup():
    await init_db()
    await seed_db()

app.include_router(auth.router,              prefix="/api/auth",              tags=["auth"])
app.include_router(clusters.router,          prefix="/api/clusters",          tags=["clusters"])
app.include_router(tenants.router,           prefix="/api/tenants",           tags=["tenants"])
app.include_router(templates.router,         prefix="/api/templates",         tags=["templates"])
app.include_router(setup.router,             prefix="/api/setup",             tags=["setup"])
app.include_router(cluster_templates.router, prefix="/api/cluster-templates", tags=["cluster-templates"])
app.include_router(admin.router,             prefix="/api/admin",             tags=["admin"])

@app.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/dashboard")

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return jinja.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return jinja.TemplateResponse("dashboard.html", {"request": request})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    return jinja.TemplateResponse("setup.html", {"request": request})

@app.get("/clusters/new", response_class=HTMLResponse)
async def cluster_create(request: Request):
    return jinja.TemplateResponse("cluster_create.html", {"request": request})

@app.get("/clusters/{name}", response_class=HTMLResponse)
async def cluster_detail(request: Request, name: str):
    return jinja.TemplateResponse("cluster_detail.html", {"request": request, "cluster_name": name})

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return jinja.TemplateResponse("admin.html", {"request": request})

@app.get("/cluster-templates", response_class=HTMLResponse)
async def cluster_templates_page(request: Request):
    return jinja.TemplateResponse("templates_list.html", {"request": request})

@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request):
    return jinja.TemplateResponse("audit.html", {"request": request})

@app.get("/healthz")
def health():
    return {"status": "ok"}
