"""Web UI routes (HTML pages)."""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import _sign_key, get_current_user, require_auth, verify_key
from ..config import settings
from ..database import get_db
from ..models import GlossaryTerm, GlossaryTranslation, Language, Project, Revision, Translation, TranslationKey

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["ui"])


def _parse_tags(tk: TranslationKey) -> list[str]:
    if not tk.tags:
        return []
    return [t.strip() for t in tk.tags.split(",") if t.strip()]


def _get_project_tags(project_id: int, db: Session) -> list[dict]:
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id,
        TranslationKey.tags != "",
    ).all()
    tag_counts: dict[str, int] = {}
    for tk in keys:
        for tag in _parse_tags(tk):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(tag_counts.items())]


# --- Auth routes (no auth dependency) ---

@router.get("/login")
def login_page(request: Request):
    if not settings.auth_keys:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    api_key = form.get("api_key", "")
    if not verify_key(api_key):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Invalid API key"
        })
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=_sign_key(api_key),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.auth_cookie_name)
    return response


# --- Protected UI routes ---

@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
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
        "auth_enabled": bool(settings.auth_keys),
    })


@router.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
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
    tags = _get_project_tags(project_id, db)
    return templates.TemplateResponse("project.html", {
        "request": request,
        "project": project,
        "key_count": key_count,
        "languages": languages,
        "stats": stats,
        "tags": tags,
    })


@router.get("/projects/{project_id}/translate")
def translation_editor(
    project_id: int,
    request: Request,
    q: str = "",
    tag: str = "",
    db: Session = Depends(get_db),
    _=Depends(require_auth),
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
    if tag:
        query = query.filter(TranslationKey.tags.ilike(f"%{tag}%"))
    keys = query.order_by(TranslationKey.key).limit(200).all()

    # Post-filter for exact tag match
    if tag:
        keys = [k for k in keys if tag in _parse_tags(k)]

    rows = []
    for tk in keys:
        trans = {}
        for t in tk.translations:
            lang = db.query(Language).filter(Language.id == t.language_id).first()
            if lang:
                trans[lang.code] = {"id": t.id, "value": t.value, "language_id": lang.id}
        rows.append({"key": tk, "translations": trans, "tags": _parse_tags(tk)})

    all_tags = _get_project_tags(project_id, db)

    return templates.TemplateResponse("translations.html", {
        "request": request,
        "project": project,
        "languages": languages,
        "rows": rows,
        "search_query": q,
        "active_tag": tag,
        "all_tags": all_tags,
    })


@router.get("/projects/{project_id}/import-export")
def import_export_page(project_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    project = db.query(Project).filter(Project.id == project_id).first()
    languages = db.query(Language).order_by(Language.code).all()
    return templates.TemplateResponse("import_export.html", {
        "request": request,
        "project": project,
        "languages": languages,
    })


# --- New UI pages ---

@router.get("/projects/{project_id}/history")
def revision_history(project_id: int, request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return RedirectResponse("/", status_code=303)
    revisions = db.query(Revision).filter(
        Revision.project_id == project_id
    ).order_by(Revision.created_at.desc()).limit(100).all()
    return templates.TemplateResponse("revisions.html", {
        "request": request,
        "project": project,
        "revisions": revisions,
    })


@router.get("/glossary")
def glossary_page(request: Request, db: Session = Depends(get_db), _=Depends(require_auth)):
    terms = db.query(GlossaryTerm).order_by(GlossaryTerm.source_term).all()
    languages = db.query(Language).order_by(Language.code).all()
    term_data = []
    for term in terms:
        translations = {}
        for gt in db.query(GlossaryTranslation).filter(GlossaryTranslation.term_id == term.id).all():
            translations[gt.language_code] = gt.approved_value
        term_data.append({"term": term, "translations": translations})
    return templates.TemplateResponse("glossary.html", {
        "request": request,
        "terms": term_data,
        "languages": languages,
    })
