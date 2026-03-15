"""Web UI routes (HTML pages)."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["ui"])


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.name).all()
    languages = db.query(Language).order_by(Language.code).all()
    project_data = []
    for p in projects:
        key_count = db.query(func.count(TranslationKey.id)).filter(
            TranslationKey.project_id == p.id
        ).scalar()
        completion = {}
        for lang in languages:
            translated = db.query(Translation).join(TranslationKey).filter(
                TranslationKey.project_id == p.id,
                Translation.language_id == lang.id,
            ).count()
            completion[lang.code] = round(translated / key_count * 100, 1) if key_count > 0 else 0
        project_data.append({
            "project": p,
            "key_count": key_count,
            "completion": completion,
        })
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "projects": project_data,
        "languages": languages,
    })


@router.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return templates.TemplateResponse("dashboard.html", {
            "request": request, "projects": [], "languages": [], "error": "Project not found"
        })
    languages = db.query(Language).order_by(Language.code).all()
    key_count = db.query(func.count(TranslationKey.id)).filter(
        TranslationKey.project_id == project_id
    ).scalar()
    stats = []
    for lang in languages:
        translated = db.query(Translation).join(TranslationKey).filter(
            TranslationKey.project_id == project_id,
            Translation.language_id == lang.id,
        ).count()
        stats.append({
            "language": lang,
            "translated": translated,
            "total": key_count,
            "percentage": round(translated / key_count * 100, 1) if key_count > 0 else 0,
        })
    return templates.TemplateResponse("project.html", {
        "request": request,
        "project": project,
        "key_count": key_count,
        "languages": languages,
        "stats": stats,
    })


@router.get("/projects/{project_id}/translate")
def translation_editor(
    project_id: int,
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return templates.TemplateResponse("dashboard.html", {
            "request": request, "projects": [], "languages": [], "error": "Project not found"
        })
    languages = db.query(Language).order_by(Language.code).all()
    query = db.query(TranslationKey).filter(TranslationKey.project_id == project_id)
    if q:
        query = query.filter(TranslationKey.key.ilike(f"%{q}%"))
    keys = query.order_by(TranslationKey.key).limit(200).all()

    rows = []
    for tk in keys:
        trans = {}
        for t in tk.translations:
            lang = db.query(Language).filter(Language.id == t.language_id).first()
            if lang:
                trans[lang.code] = {"id": t.id, "value": t.value, "language_id": lang.id}
        rows.append({"key": tk, "translations": trans})

    return templates.TemplateResponse("translations.html", {
        "request": request,
        "project": project,
        "languages": languages,
        "rows": rows,
        "search_query": q,
    })


@router.get("/projects/{project_id}/import-export")
def import_export_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    languages = db.query(Language).order_by(Language.code).all()
    return templates.TemplateResponse("import_export.html", {
        "request": request,
        "project": project,
        "languages": languages,
    })
