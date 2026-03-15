"""Translation keys and translations API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey, TranslationMemory
from ..schemas import (
    BulkTranslationRequest,
    FindReplaceMatch,
    FindReplaceRequest,
    FindReplaceResponse,
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


def _parse_tags(tk: TranslationKey) -> list[str]:
    if not tk.tags:
        return []
    return [t.strip() for t in tk.tags.split(",") if t.strip()]


def _key_to_response(tk: TranslationKey, db: Session) -> KeyResponse:
    translations = {}
    for t in tk.translations:
        lang = db.query(Language).filter(Language.id == t.language_id).first()
        if lang:
            translations[lang.code] = t.value
    return KeyResponse(
        id=tk.id, project_id=tk.project_id, key=tk.key,
        description=tk.description, created_at=tk.created_at,
        tags=_parse_tags(tk),
        translations=translations,
    )


# --- Translation Keys ---

@router.get("/api/projects/{project_id}/keys", response_model=list[KeyResponse])
def list_keys(
    project_id: int,
    q: str | None = Query(None, description="Search keys"),
    tag: str | None = Query(None, description="Filter by tag"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    _get_project_or_404(project_id, db)
    query = db.query(TranslationKey).filter(TranslationKey.project_id == project_id)
    if q:
        query = query.filter(TranslationKey.key.ilike(f"%{q}%"))
    if tag:
        query = query.filter(TranslationKey.tags.ilike(f"%{tag}%"))
    keys = query.order_by(TranslationKey.key).offset(offset).limit(limit).all()
    # Post-filter for exact tag match (ILIKE is approximate)
    if tag:
        keys = [k for k in keys if tag in _parse_tags(k)]
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
    tags_str = ",".join(t.strip() for t in data.tags if t.strip())
    tk = TranslationKey(project_id=project_id, key=data.key, description=data.description, tags=tags_str)
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
    if data.tags is not None:
        tk.tags = ",".join(t.strip() for t in data.tags if t.strip())
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


# --- Tags ---

@router.get("/api/projects/{project_id}/tags")
def list_tags(project_id: int, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id,
        TranslationKey.tags != "",
    ).all()
    tag_counts: dict[str, int] = {}
    for tk in keys:
        for tag in _parse_tags(tk):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(tag_counts.items())]


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

    # Auto-populate translation memory
    other_translations = db.query(Translation).join(Language, Translation.language_id == Language.id).filter(
        Translation.key_id == key_id,
        Translation.language_id != language_id,
    ).all()
    for other in other_translations:
        other_lang = db.query(Language).filter(Language.id == other.language_id).first()
        if other_lang:
            for src_l, src_t, tgt_l, tgt_t in [
                (other_lang.code, other.value, lang.code, data.value),
                (lang.code, data.value, other_lang.code, other.value),
            ]:
                existing_tm = db.query(TranslationMemory).filter(
                    TranslationMemory.source_lang == src_l,
                    TranslationMemory.source_text == src_t,
                    TranslationMemory.target_lang == tgt_l,
                    TranslationMemory.target_text == tgt_t,
                ).first()
                if not existing_tm:
                    db.add(TranslationMemory(
                        source_lang=src_l, source_text=src_t,
                        target_lang=tgt_l, target_text=tgt_t,
                        project_id=tk.project_id,
                    ))

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


# --- Find & Replace ---

@router.post("/api/projects/{project_id}/translations/find-replace", response_model=FindReplaceResponse)
def find_replace(
    project_id: int, data: FindReplaceRequest, db: Session = Depends(get_db)
):
    _get_project_or_404(project_id, db)

    query = db.query(Translation).join(TranslationKey).filter(
        TranslationKey.project_id == project_id,
        Translation.value.ilike(f"%{data.find}%"),
    )

    if data.language_code:
        lang = db.query(Language).filter(Language.code == data.language_code).first()
        if not lang:
            raise HTTPException(404, f"Language '{data.language_code}' not found")
        query = query.filter(Translation.language_id == lang.id)

    translations = query.all()
    matches = []

    for t in translations:
        tk = db.query(TranslationKey).filter(TranslationKey.id == t.key_id).first()
        lang = db.query(Language).filter(Language.id == t.language_id).first()
        if not tk or not lang:
            continue

        new_value = t.value.replace(data.find, data.replace)
        matches.append(FindReplaceMatch(
            key_id=tk.id, key=tk.key,
            language_code=lang.code,
            old_value=t.value, new_value=new_value,
        ))

        if not data.preview:
            t.value = new_value

    if not data.preview:
        db.commit()

    return FindReplaceResponse(
        matches=matches, total=len(matches), applied=not data.preview,
    )


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
