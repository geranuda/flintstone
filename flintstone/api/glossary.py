"""Glossary CRUD API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..glossary_check import check_glossary
from ..models import GlossaryTerm, GlossaryTranslation
from ..schemas import (
    GlossaryCheckRequest,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
    GlossaryTranslationSchema,
    GlossaryViolation,
)

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


def _term_to_response(term: GlossaryTerm, db: Session) -> GlossaryTermResponse:
    translations = {}
    gts = db.query(GlossaryTranslation).filter(
        GlossaryTranslation.term_id == term.id
    ).all()
    for gt in gts:
        translations[gt.language_code] = gt.approved_value
    return GlossaryTermResponse(
        id=term.id,
        source_term=term.source_term,
        source_language=term.source_language,
        description=term.description,
        case_sensitive=bool(term.case_sensitive),
        translations=translations,
        created_at=term.created_at,
    )


@router.get("", response_model=list[GlossaryTermResponse])
def list_glossary_terms(
    q: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(GlossaryTerm)
    if q:
        query = query.filter(GlossaryTerm.source_term.ilike(f"%{q}%"))
    terms = query.order_by(GlossaryTerm.source_term).offset(offset).limit(limit).all()
    return [_term_to_response(t, db) for t in terms]


@router.post("", response_model=GlossaryTermResponse, status_code=201)
def create_glossary_term(data: GlossaryTermCreate, db: Session = Depends(get_db)):
    existing = db.query(GlossaryTerm).filter(
        GlossaryTerm.source_term == data.source_term,
        GlossaryTerm.source_language == data.source_language,
    ).first()
    if existing:
        raise HTTPException(400, f"Glossary term '{data.source_term}' already exists for language '{data.source_language}'")

    term = GlossaryTerm(
        source_term=data.source_term,
        source_language=data.source_language,
        description=data.description,
        case_sensitive=data.case_sensitive,
    )
    db.add(term)
    db.flush()

    for gt in data.translations:
        db.add(GlossaryTranslation(
            term_id=term.id,
            language_code=gt.language_code,
            approved_value=gt.approved_value,
        ))

    db.commit()
    db.refresh(term)
    return _term_to_response(term, db)


@router.get("/{term_id}", response_model=GlossaryTermResponse)
def get_glossary_term(term_id: int, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(404, "Glossary term not found")
    return _term_to_response(term, db)


@router.put("/{term_id}", response_model=GlossaryTermResponse)
def update_glossary_term(term_id: int, data: GlossaryTermUpdate, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(404, "Glossary term not found")
    if data.source_term is not None:
        term.source_term = data.source_term
    if data.description is not None:
        term.description = data.description
    if data.case_sensitive is not None:
        term.case_sensitive = data.case_sensitive
    db.commit()
    db.refresh(term)
    return _term_to_response(term, db)


@router.delete("/{term_id}", status_code=204)
def delete_glossary_term(term_id: int, db: Session = Depends(get_db)):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(404, "Glossary term not found")
    db.delete(term)
    db.commit()


@router.post("/{term_id}/translations", response_model=GlossaryTermResponse)
def add_glossary_translation(
    term_id: int, data: GlossaryTranslationSchema, db: Session = Depends(get_db)
):
    term = db.query(GlossaryTerm).filter(GlossaryTerm.id == term_id).first()
    if not term:
        raise HTTPException(404, "Glossary term not found")

    existing = db.query(GlossaryTranslation).filter(
        GlossaryTranslation.term_id == term_id,
        GlossaryTranslation.language_code == data.language_code,
    ).first()
    if existing:
        existing.approved_value = data.approved_value
    else:
        db.add(GlossaryTranslation(
            term_id=term_id,
            language_code=data.language_code,
            approved_value=data.approved_value,
        ))
    db.commit()
    db.refresh(term)
    return _term_to_response(term, db)


@router.delete("/{term_id}/translations/{language_code}", status_code=204)
def delete_glossary_translation(term_id: int, language_code: str, db: Session = Depends(get_db)):
    gt = db.query(GlossaryTranslation).filter(
        GlossaryTranslation.term_id == term_id,
        GlossaryTranslation.language_code == language_code,
    ).first()
    if not gt:
        raise HTTPException(404, "Glossary translation not found")
    db.delete(gt)
    db.commit()


@router.post("/check", response_model=list[GlossaryViolation])
def check_glossary_endpoint(data: GlossaryCheckRequest, db: Session = Depends(get_db)):
    """Manually check text for glossary compliance."""
    return check_glossary(
        db,
        source_text=data.source_text,
        source_lang=data.source_lang,
        target_text=data.target_text,
        target_lang=data.target_lang,
    )
