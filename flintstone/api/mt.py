"""Machine Translation API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Language, MTUsageLog, Project, Translation, TranslationKey
from ..mt.factory import get_available_backends, get_backend
from ..schemas import (
    MTConfigResponse,
    MTPreTranslateRequest,
    MTPreTranslateResponse,
    MTTranslateRequest,
    MTTranslateResponse,
)

router = APIRouter(tags=["machine-translation"])


@router.get("/api/mt/config", response_model=MTConfigResponse)
def mt_config():
    available = get_available_backends()
    backends = {
        "google": bool(settings.mt_google_api_key),
        "deepl": bool(settings.mt_deepl_api_key),
        "libretranslate": bool(settings.mt_libretranslate_url),
    }
    return MTConfigResponse(
        available_backends=available,
        default_backend=settings.mt_default_backend or None,
        backends=backends,
    )


@router.post("/api/mt/translate", response_model=MTTranslateResponse)
def mt_translate(data: MTTranslateRequest, db: Session = Depends(get_db)):
    try:
        backend = get_backend(data.backend)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        translations = backend.translate(data.texts, data.source_lang, data.target_lang)
    except Exception as e:
        raise HTTPException(502, f"MT backend error: {e}")

    char_count = sum(len(t) for t in data.texts)

    # Log usage
    db.add(MTUsageLog(
        backend=backend.name,
        source_lang=data.source_lang,
        target_lang=data.target_lang,
        character_count=char_count,
    ))
    db.commit()

    return MTTranslateResponse(
        translations=translations,
        backend=backend.name,
        character_count=char_count,
    )


@router.post("/api/projects/{project_id}/mt/pre-translate", response_model=MTPreTranslateResponse)
def mt_pre_translate(
    project_id: int, data: MTPreTranslateRequest, db: Session = Depends(get_db)
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    source_lang = db.query(Language).filter(Language.code == data.source_lang).first()
    target_lang = db.query(Language).filter(Language.code == data.target_lang).first()
    if not source_lang or not target_lang:
        raise HTTPException(404, "Language not found")

    try:
        backend = get_backend(data.backend)
    except ValueError as e:
        raise HTTPException(400, str(e))

    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).all()

    # Collect untranslated keys
    to_translate = []
    for tk in keys:
        existing = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == target_lang.id,
        ).first()
        if existing and not data.overwrite:
            continue

        source_t = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == source_lang.id,
        ).first()
        if not source_t:
            continue

        to_translate.append({"key": tk, "source_text": source_t.value, "existing": existing})

    if not to_translate:
        return MTPreTranslateResponse(
            translated=0, skipped=len(keys), total=len(keys),
            backend=backend.name, character_count=0,
        )

    # Batch translate
    source_texts = [item["source_text"] for item in to_translate]
    try:
        translated_texts = backend.translate(source_texts, data.source_lang, data.target_lang)
    except Exception as e:
        raise HTTPException(502, f"MT backend error: {e}")

    translated_count = 0
    char_count = sum(len(t) for t in source_texts)

    for item, translated_text in zip(to_translate, translated_texts):
        if item["existing"]:
            item["existing"].value = translated_text
        else:
            db.add(Translation(
                key_id=item["key"].id,
                language_id=target_lang.id,
                value=translated_text,
            ))
        translated_count += 1

    db.add(MTUsageLog(
        backend=backend.name,
        source_lang=data.source_lang,
        target_lang=data.target_lang,
        character_count=char_count,
        project_id=project_id,
    ))
    db.commit()

    return MTPreTranslateResponse(
        translated=translated_count,
        skipped=len(keys) - translated_count,
        total=len(keys),
        backend=backend.name,
        character_count=char_count,
    )


@router.get("/api/mt/usage")
def mt_usage(db: Session = Depends(get_db)):
    logs = db.query(MTUsageLog).order_by(MTUsageLog.created_at.desc()).limit(100).all()
    total_chars = sum(log.character_count for log in logs)
    by_backend: dict[str, int] = {}
    for log in logs:
        by_backend[log.backend] = by_backend.get(log.backend, 0) + log.character_count
    return {
        "total_character_count": total_chars,
        "by_backend": by_backend,
        "recent_entries": len(logs),
    }
