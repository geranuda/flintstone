"""Translation Memory API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TranslationMemory
from ..schemas import TMEntry, TMSuggestion

router = APIRouter(prefix="/api/memory", tags=["translation-memory"])


@router.get("/suggest", response_model=list[TMSuggestion])
def suggest_translations(
    source: str = Query(..., min_length=1, description="Source text to match"),
    source_lang: str = Query(..., description="Source language code"),
    target_lang: str = Query(..., description="Target language code"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    # Exact matches first
    exact = db.query(TranslationMemory).filter(
        TranslationMemory.source_lang == source_lang,
        TranslationMemory.target_lang == target_lang,
        TranslationMemory.source_text == source,
    ).limit(limit).all()

    results = [
        TMSuggestion(
            source_text=tm.source_text, target_text=tm.target_text,
            match_type="exact", project_id=tm.project_id,
        )
        for tm in exact
    ]

    # Substring matches (if we need more)
    if len(results) < limit:
        remaining = limit - len(results)
        exact_ids = [tm.id for tm in exact]
        contains = db.query(TranslationMemory).filter(
            TranslationMemory.source_lang == source_lang,
            TranslationMemory.target_lang == target_lang,
            TranslationMemory.source_text.ilike(f"%{source}%"),
            TranslationMemory.id.notin_(exact_ids) if exact_ids else True,
        ).limit(remaining).all()

        results.extend([
            TMSuggestion(
                source_text=tm.source_text, target_text=tm.target_text,
                match_type="contains", project_id=tm.project_id,
            )
            for tm in contains
        ])

    # Deduplicate by target_text
    seen = set()
    unique = []
    for r in results:
        if r.target_text not in seen:
            seen.add(r.target_text)
            unique.append(r)
    return unique


@router.get("", response_model=list[TMEntry])
def list_memory(
    source_lang: str | None = Query(None),
    target_lang: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(TranslationMemory)
    if source_lang:
        query = query.filter(TranslationMemory.source_lang == source_lang)
    if target_lang:
        query = query.filter(TranslationMemory.target_lang == target_lang)
    return query.order_by(TranslationMemory.created_at.desc()).offset(offset).limit(limit).all()


@router.delete("", status_code=204)
def clear_memory(db: Session = Depends(get_db)):
    db.query(TranslationMemory).delete()
    db.commit()
