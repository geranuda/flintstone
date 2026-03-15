"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import export, languages, memory, projects, tmx, translations
from .api import revisions as revisions_api
from .api import glossary as glossary_api
from .api import webhooks as webhooks_api
from .api import mt as mt_api
from .auth import require_auth
from .database import init_db
from .ui import views

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Flintstone",
    version="0.1.0",
    description="Lightweight Translation Management System",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Templates
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Auth dependency applied to all protected routers
auth_dep = [Depends(require_auth)]

# API routers
app.include_router(projects.router, dependencies=auth_dep)
app.include_router(languages.router, dependencies=auth_dep)
app.include_router(translations.router, dependencies=auth_dep)
app.include_router(export.router, dependencies=auth_dep)
app.include_router(memory.router, dependencies=auth_dep)
app.include_router(tmx.router, dependencies=auth_dep)
app.include_router(revisions_api.router, dependencies=auth_dep)
app.include_router(glossary_api.router, dependencies=auth_dep)
app.include_router(webhooks_api.router, dependencies=auth_dep)
app.include_router(mt_api.router, dependencies=auth_dep)

# UI router (includes its own auth handling for login/logout)
app.include_router(views.router)
