"""Translation Memory API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language, Project, Translation, TranslationKey, TranslationMemory
from ..schemas import FillUpRequest, FillUpResult, TMEntry, TMSuggestion

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


# --- TM Fill-up ---

@router.post("/fillup/{project_id}", response_model=FillUpResult)
def tm_fillup(
    project_id: int, data: FillUpRequest, db: Session = Depends(get_db)
):
    """Auto-fill untranslated keys from translation memory matches."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    source_lang = db.query(Language).filter(Language.code == data.source_lang).first()
    target_lang = db.query(Language).filter(Language.code == data.target_lang).first()
    if not source_lang or not target_lang:
        raise HTTPException(404, "Language not found")

    # Find all keys in the project
    keys = db.query(TranslationKey).filter(
        TranslationKey.project_id == project_id
    ).all()

    filled = 0
    skipped = 0
    total_missing = 0

    for tk in keys:
        # Check if target translation already exists
        existing_target = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == target_lang.id,
        ).first()
        if existing_target:
            continue  # already translated

        # Get source translation
        source_translation = db.query(Translation).filter(
            Translation.key_id == tk.id,
            Translation.language_id == source_lang.id,
        ).first()
        if not source_translation:
            total_missing += 1
            skipped += 1
            continue

        total_missing += 1

        # Look up TM for a match
        if data.match_type == "exact":
            tm_match = db.query(TranslationMemory).filter(
                TranslationMemory.source_lang == data.source_lang,
                TranslationMemory.target_lang == data.target_lang,
                TranslationMemory.source_text == source_translation.value,
            ).first()
        else:
            tm_match = db.query(TranslationMemory).filter(
                TranslationMemory.source_lang == data.source_lang,
                TranslationMemory.target_lang == data.target_lang,
                TranslationMemory.source_text.ilike(f"%{source_translation.value}%"),
            ).first()

        if tm_match:
            new_translation = Translation(
                key_id=tk.id, language_id=target_lang.id, value=tm_match.target_text,
            )
            db.add(new_translation)
            filled += 1
        else:
            skipped += 1

    db.commit()
    return FillUpResult(filled=filled, skipped=skipped, total_missing=total_missing)
