"""Translation Memory API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func as sa_func
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
    include_fuzzy: bool = Query(True, description="Include fuzzy matches"),
    min_similarity: float = Query(0.6, ge=0.0, le=1.0, description="Minimum similarity for fuzzy"),
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
            match_type="exact", similarity_score=1.0, project_id=tm.project_id,
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
                match_type="contains", similarity_score=0.9, project_id=tm.project_id,
            )
            for tm in contains
        ])

    # Fuzzy matches (if we still need more and fuzzy is enabled)
    if include_fuzzy and len(results) < limit:
        remaining = limit - len(results)
        used_ids = [tm.id for tm in exact]
        used_ids.extend([tm.id for tm in (contains if 'contains' in dir() else [])])

        # Length pre-filter for performance
        source_len = len(source)
        max_diff = max(int(source_len * 0.3), 10)

        candidates = db.query(TranslationMemory).filter(
            TranslationMemory.source_lang == source_lang,
            TranslationMemory.target_lang == target_lang,
            sa_func.length(TranslationMemory.source_text).between(
                source_len - max_diff, source_len + max_diff
            ),
        ).limit(5000).all()

        # Filter out already matched
        exact_texts = {r.target_text for r in results}
        candidates = [c for c in candidates if c.target_text not in exact_texts]

        from ..fuzzy import find_fuzzy_matches
        fuzzy_matches = find_fuzzy_matches(source, candidates, min_similarity)

        for tm, score in fuzzy_matches[:remaining]:
            results.append(TMSuggestion(
                source_text=tm.source_text, target_text=tm.target_text,
                match_type="fuzzy", similarity_score=round(score, 3),
                project_id=tm.project_id,
            ))

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
        tm_match = None
        if data.match_type == "exact":
            tm_match = db.query(TranslationMemory).filter(
                TranslationMemory.source_lang == data.source_lang,
                TranslationMemory.target_lang == data.target_lang,
                TranslationMemory.source_text == source_translation.value,
            ).first()
        elif data.match_type == "contains":
            tm_match = db.query(TranslationMemory).filter(
                TranslationMemory.source_lang == data.source_lang,
                TranslationMemory.target_lang == data.target_lang,
                TranslationMemory.source_text.ilike(f"%{source_translation.value}%"),
            ).first()
        elif data.match_type == "fuzzy":
            # Fuzzy fill-up
            candidates = db.query(TranslationMemory).filter(
                TranslationMemory.source_lang == data.source_lang,
                TranslationMemory.target_lang == data.target_lang,
            ).limit(5000).all()

            from ..fuzzy import find_fuzzy_matches
            fuzzy_results = find_fuzzy_matches(
                source_translation.value, candidates, data.min_similarity
            )
            if fuzzy_results:
                tm_match = fuzzy_results[0][0]  # Best match

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
