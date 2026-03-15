"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import export, languages, memory, projects, tmx, translations
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

# API routers
app.include_router(projects.router)
app.include_router(languages.router)
app.include_router(translations.router)
app.include_router(export.router)
app.include_router(memory.router)
app.include_router(tmx.router)

# UI router
app.include_router(views.router)
