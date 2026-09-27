"""FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import cds, export, languages, memory, projects, tmx, translations
from .database import init_db
from .ui import views

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Flintstone",
    version=__version__,
    description=(
        "Lightweight Translation Management System with a Transifex Native compatible "
        "Content Delivery Service under `/cds`."
    ),
    docs_url="/api/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Transifex Native CDS: CORS for browser SDKs, tolerant URL joining
app.add_middleware(cds.CDSMiddleware)
app.add_exception_handler(cds.CDSError, cds.cds_error_handler)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# API routers
app.include_router(projects.router)
app.include_router(languages.router)
app.include_router(translations.router)
app.include_router(export.router)
app.include_router(memory.router)
app.include_router(tmx.router)
app.include_router(cds.router)

# UI router
app.include_router(views.router)
