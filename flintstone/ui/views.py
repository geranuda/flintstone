"""Web UI routes (HTML pages)."""

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import editor, locales, native
from ..database import get_db
from ..models import ContentJob, Language, Project, TranslationKey

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["ui"], include_in_schema=False)

_PLACEHOLDER = re.compile(
    r"%(?:\d+\$)?#@[^@\s]+@"  # String Catalog / stringsdict substitution tokens
    r"|%%"
    r"|%(?:\d+\$)?[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|q|L|z|t|j)?[@dDiuUxXoOfFeEgGcCsSpaA]"
    r"|\{[A-Za-z_][A-Za-z0-9_]*\}"
)


def _blank(text: str) -> Markup | None:
    """Whitespace-only strings (e.g. the String Catalog key " ") rendered visibly."""
    if text.strip():
        return None
    return Markup('<span class="ph" title="whitespace">{}</span>').format("␣" * len(text) if text else "empty")


def highlight_placeholders(text) -> Markup:
    text = text or ""
    blank = _blank(text)
    if blank is not None:
        return blank
    escaped = str(escape(text))
    return Markup(_PLACEHOLDER.sub(lambda m: f'<span class="ph">{m.group(0)}</span>', escaped))


def show_key(key) -> Markup:
    return _blank(key or "") or Markup(escape(key))


def format_number(value) -> str:
    return f"{value or 0:,}"


def time_ago(value: datetime | None) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - value).total_seconds())
    if seconds < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return ""


def short_file(path: str) -> str:
    parts = path.split("/")
    return path if len(parts) <= 2 else f"{parts[0]}/…/{parts[-1]}"


templates.env.filters["ph"] = highlight_placeholders
templates.env.filters["key"] = show_key
templates.env.filters["num"] = format_number
templates.env.filters["ago"] = time_ago
templates.env.filters["short_file"] = short_file


def _get_project_tags(project_id: int, db: Session) -> list[dict]:
    tag_counts: dict[str, int] = {}
    for (tags,) in db.query(TranslationKey.tags).filter(
        TranslationKey.project_id == project_id, TranslationKey.tags != ""
    ):
        for tag in native.clean_list((tags or "").split(",")):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(tag_counts.items())]


def _not_found(request: Request, message: str = "Project not found"):
    return templates.TemplateResponse(request, "not_found.html", {"message": message}, status_code=404)


def _cds_host(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/cds"


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    cards = []
    for project in db.query(Project).order_by(Project.name).all():
        stats = native.language_stats(db, project)
        key_count = stats[0]["total"] if stats else db.query(func.count(TranslationKey.id)).filter(
            TranslationKey.project_id == project.id
        ).scalar()
        last_job = (
            db.query(ContentJob).filter(ContentJob.project_id == project.id)
            .order_by(ContentJob.created_at.desc()).first()
        )
        cards.append({
            "project": project,
            "key_count": key_count,
            "targets": [s for s in stats if not s["is_source"]],
            "last_job": last_job,
        })
    return templates.TemplateResponse(request, "dashboard.html", {
        "projects": cards,
        "languages": db.query(Language).order_by(Language.code).all(),
        "catalog": locales.catalog(),
    })


@router.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return _not_found(request)
    stats = native.language_stats(db, project)
    targets = [s for s in stats if not s["is_source"]]
    enabled = {locales.code_key(s["language"].code) for s in stats} | {locales.code_key(project.source_language_code)}
    jobs = (
        db.query(ContentJob).filter(ContentJob.project_id == project.id)
        .order_by(ContentJob.created_at.desc()).limit(10).all()
    )
    return templates.TemplateResponse(request, "project.html", {
        "project": project,
        "key_count": stats[0]["total"] if stats else 0,
        "source_stat": next((s for s in stats if s["is_source"]), None),
        "source_info": locales.locale_info(project.source_language_code),
        "targets": targets,
        "app_locales": [project.source_language_code] + [s["language"].code for s in targets],
        "tags": _get_project_tags(project.id, db),
        "files": editor.project_files(db, project),
        "jobs": jobs,
        "activity": native.recent_activity(project.id)[:10],
        "cds_host": _cds_host(request),
        "catalog": [info for info in locales.catalog() if locales.code_key(info.code) not in enabled],
    })


def _page_links(page: int, pages: int) -> list[int | None]:
    wanted = {1, pages, page - 1, page, page + 1, page - 2, page + 2}
    out: list[int | None] = []
    for n in sorted(p for p in wanted if 1 <= p <= pages):
        if out and out[-1] is not None and n - out[-1] > 1:
            out.append(None)
        out.append(n)
    return out


@router.get("/projects/{project_id}/translate")
def translation_editor(
    project_id: int,
    request: Request,
    lang: str = "",
    q: str = "",
    tag: str = "",
    status: str = "",
    file: str = "",
    sort: str = "key",
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return _not_found(request)
    targets = native.target_languages(db, project)
    source = native.source_language(db, project)
    context = {
        "project": project, "targets": targets, "source": source,
        "q": q, "tag": tag, "status": status, "file": file, "sort": sort,
        "status_filters": editor.STATUS_FILTERS, "sorts": editor.SORTS,
    }
    if not targets:
        return templates.TemplateResponse(request, "translations.html", {**context, "target": None})

    target = next((t for t in targets if locales.same_code(t.code, lang)), targets[0]) if lang else targets[0]
    status = status if status in editor.STATUS_FILTERS else ""
    sort = sort if sort in editor.SORTS else "key"
    per_page = min(max(per_page, 10), 200)
    rows, total = editor.query_strings(
        db, project, target, source, q=q, tag=tag, status=status, file=file,
        sort=sort, page=max(page, 1), per_page=per_page,
    )
    pages = max(math.ceil(total / per_page), 1)
    page = min(max(page, 1), pages)

    stat = next((s for s in native.language_stats(db, project) if s["language"].id == target.id), None)
    counts = editor.status_counts(db, project, target, source, q=q, tag=tag, file=file)
    base_params = {"lang": target.code, "q": q, "tag": tag, "status": status, "file": file, "sort": sort}

    def url(**overrides) -> str:
        params = {**base_params, **overrides}
        return f"/projects/{project.id}/translate?" + urlencode({k: v for k, v in params.items() if v not in ("", None)})

    return templates.TemplateResponse(request, "translations.html", {
        **context,
        "status": status, "sort": sort,
        "target": target,
        "target_info": locales.locale_info(target.code),
        "stat": stat,
        "counts": counts,
        "rows": [editor.row_view(r, target) for r in rows],
        "total": total,
        "page": page, "pages": pages, "per_page": per_page,
        "page_links": _page_links(page, pages),
        "first_index": (page - 1) * per_page + 1 if total else 0,
        "last_index": min(page * per_page, total),
        "url": url,
        "files": editor.project_files(db, project),
        "all_tags": _get_project_tags(project.id, db),
        "languages": [source, *targets] if source else targets,
    })


@router.get("/projects/{project_id}/import-export")
def import_export_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return _not_found(request)
    return templates.TemplateResponse(request, "import_export.html", {
        "project": project,
        "languages": native.project_languages(db, project),
    })
