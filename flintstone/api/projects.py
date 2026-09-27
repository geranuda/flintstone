"""Projects API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import locales, native
from ..database import get_db
from ..models import ContentJob, Project, TranslationKey
from ..schemas import (
    CredentialsResponse,
    CredentialsRotate,
    JobResponse,
    ProjectCreate,
    ProjectLanguageCreate,
    ProjectLanguageResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _to_response(project: Project, db: Session, secret: str | None = None) -> ProjectResponse:
    key_count = db.query(func.count(TranslationKey.id)).filter(
        TranslationKey.project_id == project.id
    ).scalar()
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        created_at=project.created_at, updated_at=project.updated_at,
        key_count=key_count,
        source_language=project.source_language_code or "en",
        target_languages=[lang.code for lang in native.target_languages(db, project)],
        token=project.token,
        secret=secret,
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.name).all()
    return [_to_response(p, db) for p in projects]


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project. The response includes the CDS token and secret; the
    secret is shown only once (only its hash is stored)."""
    existing = db.query(Project).filter(Project.name == data.name).first()
    if existing:
        raise HTTPException(400, f"Project '{data.name}' already exists")
    project = Project(
        name=data.name,
        description=data.description,
        source_language_code=locales.normalize_code(data.source_language),
    )
    native.issue_token(project)
    secret = native.issue_secret(project)
    db.add(project)
    db.flush()
    if data.target_languages is not None:
        try:
            native.configure_languages(db, project, data.source_language, data.target_languages)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(project)
    return _to_response(project, db, secret=secret)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _to_response(_get_project_or_404(project_id, db), db)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    db.commit()
    db.refresh(project)
    return _to_response(project, db)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)
    db.delete(project)
    db.commit()


# --- Project languages ---

def _language_response(lang, is_source: bool) -> ProjectLanguageResponse:
    info = locales.locale_info(lang.code)
    return ProjectLanguageResponse(
        code=lang.code, name=lang.name, localized_name=info.localized_name, rtl=info.rtl,
        is_source=is_source, plural_categories=list(info.plural_categories),
    )


@router.get("/{project_id}/languages", response_model=list[ProjectLanguageResponse])
def list_project_languages(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)
    src = native.source_language(db, project)
    return [
        _language_response(lang, bool(src and lang.id == src.id))
        for lang in native.project_languages(db, project)
    ]


@router.post("/{project_id}/languages", response_model=ProjectLanguageResponse, status_code=201)
def add_project_language(project_id: int, data: ProjectLanguageCreate, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)
    try:
        lang = native.add_target_language(db, project, data.code, data.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _language_response(lang, False)


@router.delete("/{project_id}/languages/{code}", status_code=204)
def remove_project_language(project_id: int, code: str, db: Session = Depends(get_db)):
    """Stop translating into a language. Existing translations are kept."""
    project = _get_project_or_404(project_id, db)
    if not native.remove_target_language(db, project, code):
        raise HTTPException(404, f"Language '{code}' is not a target of this project")
    db.commit()


# --- Native credentials and push history ---

@router.post("/{project_id}/credentials", response_model=CredentialsResponse)
def rotate_credentials(project_id: int, data: CredentialsRotate, db: Session = Depends(get_db)):
    """Generate a new secret, token, or both. The secret is returned once.

    The JSON body is required: browsers cannot send it cross-site without a
    CORS preflight, which keeps other websites from rotating credentials.
    """
    project = _get_project_or_404(project_id, db)
    rotate = data.rotate
    secret = None
    if rotate in ("token", "all"):
        native.issue_token(project)
    if rotate in ("secret", "all"):
        secret = native.issue_secret(project)
    db.commit()
    return CredentialsResponse(token=project.token, secret=secret, secret_hint=project.secret_hint)


@router.get("/{project_id}/jobs", response_model=list[JobResponse])
def list_jobs(project_id: int, limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    jobs = (
        db.query(ContentJob)
        .filter(ContentJob.project_id == project_id)
        .order_by(ContentJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        JobResponse(
            id=j.id, kind=j.kind, language_code=j.language_code, status=j.status, total=j.total,
            created=j.created, updated=j.updated, skipped=j.skipped, deleted=j.deleted, failed=j.failed,
            errors=j.error_list, options=j.option_dict, client=j.client,
            created_at=j.created_at, finished_at=j.finished_at,
        )
        for j in jobs
    ]
