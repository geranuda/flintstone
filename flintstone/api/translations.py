"""Translation keys and translations API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey
from ..schemas import (
    BulkTranslationRequest,
    KeyCreate,
    KeyResponse,
    KeyUpdate,
    LanguageStats,
    ProjectStats,
    TranslationResponse,
    TranslationUpdate,
)

router = APIRouter(tags=["translations"])


def _get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _key_to_response(tk: TranslationKey, db: Session) -> KeyResponse:
    translations = {}
    for t in tk.translations:
        lang = db.query(Language).filter(Language.id == t.language_id).first()
        if lang:
            translations[lang.code] = t.value
    return KeyResponse(
        id=tk.id, project_id=tk.project_id, key=tk.key,
        description=tk.description, created_at=tk.created_at,
        translations=translations,
    )


# --- Translation Keys ---

@router.get("/api/projects/{project_id}/keys", response_model=list[KeyResponse])
def list_keys(
    project_id: int,
    q: str | None = Query(None, description="Search keys"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    _get_project_or_404(project_id, db)
    query = db.query(TranslationKey).filter(TranslationKey.project_id == project_id)
    if q:
        query = query.filter(TranslationKey.key.ilike(f"%{q}%"))
    keys = query.order_by(TranslationKey.key).offset(offset).limit(limit).all()
    return [_key_to_response(k, db) for k in keys]


@router.post("/api/projects/{project_id}/keys", response_model=KeyResponse, status_code=201)
def create_key(project_id: int, data: KeyCreate, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    existing = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id,
        TranslationKey.key == data.key,
    ).first()
    if existing:
        raise HTTPException(400, f"Key '{data.key}' already exists in this project")
    tk = TranslationKey(project_id=project_id, key=data.key, description=data.description)
    db.add(tk)
    db.commit()
    db.refresh(tk)
    return _key_to_response(tk, db)


@router.put("/api/keys/{key_id}", response_model=KeyResponse)
def update_key(key_id: int, data: KeyUpdate, db: Session = Depends(get_db)):
    tk = db.query(TranslationKey).filter(TranslationKey.id == key_id).first()
    if not tk:
        raise HTTPException(404, "Key not found")
    if data.key is not None:
        tk.key = data.key
    if data.description is not None:
        tk.description = data.description
    db.commit()
    db.refresh(tk)
    return _key_to_response(tk, db)


@router.delete("/api/keys/{key_id}", status_code=204)
def delete_key(key_id: int, db: Session = Depends(get_db)):
    tk = db.query(TranslationKey).filter(TranslationKey.id == key_id).first()
    if not tk:
        raise HTTPException(404, "Key not found")
    db.delete(tk)
    db.commit()


# --- Translations ---

@router.get("/api/projects/{project_id}/translations", response_model=list[KeyResponse])
def get_translations(
    project_id: int,
    lang: str | None = Query(None, description="Filter by language code"),
    db: Session = Depends(get_db),
):
    _get_project_or_404(project_id, db)
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).order_by(TranslationKey.key).all()
    return [_key_to_response(k, db) for k in keys]


@router.put("/api/translations/{key_id}/{language_id}", response_model=TranslationResponse)
def set_translation(
    key_id: int, language_id: int, data: TranslationUpdate, db: Session = Depends(get_db)
):
    tk = db.query(TranslationKey).filter(TranslationKey.id == key_id).first()
    if not tk:
        raise HTTPException(404, "Key not found")
    lang = db.query(Language).filter(Language.id == language_id).first()
    if not lang:
        raise HTTPException(404, "Language not found")

    translation = db.query(Translation).filter(
        Translation.key_id == key_id,
        Translation.language_id == language_id,
    ).first()

    if translation:
        translation.value = data.value
    else:
        translation = Translation(key_id=key_id, language_id=language_id, value=data.value)
        db.add(translation)

    db.commit()
    db.refresh(translation)
    return translation


@router.post("/api/projects/{project_id}/translations/bulk")
def bulk_update_translations(
    project_id: int, data: BulkTranslationRequest, db: Session = Depends(get_db)
):
    _get_project_or_404(project_id, db)
    updated = 0
    created = 0

    for item in data.translations:
        tk = db.query(TranslationKey).filter(
            TranslationKey.project_id == project_id,
            TranslationKey.key == item.key,
        ).first()
        if not tk:
            tk = TranslationKey(project_id=project_id, key=item.key)
            db.add(tk)
            db.flush()

        lang = db.query(Language).filter(Language.code == item.language_code).first()
        if not lang:
            continue

        translation = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == lang.id,
        ).first()

        if translation:
            translation.value = item.value
            updated += 1
        else:
            translation = Translation(key_id=tk.id, language_id=lang.id, value=item.value)
            db.add(translation)
            created += 1

    db.commit()
    return {"updated": updated, "created": created}


@router.get("/api/projects/{project_id}/translations/search", response_model=list[KeyResponse])
def search_translations(
    project_id: int,
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    _get_project_or_404(project_id, db)
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).outerjoin(Translation).filter(
        or_(
            TranslationKey.key.ilike(f"%{q}%"),
            Translation.value.ilike(f"%{q}%"),
        )
    ).distinct().order_by(TranslationKey.key).all()
    return [_key_to_response(k, db) for k in keys]


# --- Stats ---

@router.get("/api/projects/{project_id}/stats", response_model=ProjectStats)
def get_project_stats(project_id: int, db: Session = Depends(get_db)):
    project = _get_project_or_404(project_id, db)
    total_keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).count()
    languages = db.query(Language).order_by(Language.code).all()

    lang_stats = []
    for lang in languages:
        translated = db.query(Translation).join(TranslationKey).filter(
            TranslationKey.project_id == project_id,
            Translation.language_id == lang.id,
        ).count()
        percentage = (translated / total_keys * 100) if total_keys > 0 else 0.0
        lang_stats.append(LanguageStats(
            language_code=lang.code, language_name=lang.name,
            translated=translated, total=total_keys,
            percentage=round(percentage, 1),
        ))

    return ProjectStats(
        project_id=project.id, project_name=project.name,
        total_keys=total_keys, languages=lang_stats,
    )
