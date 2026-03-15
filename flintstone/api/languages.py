"""Languages API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Language
from ..schemas import LanguageCreate, LanguageResponse

router = APIRouter(prefix="/api/languages", tags=["languages"])


@router.get("", response_model=list[LanguageResponse])
def list_languages(db: Session = Depends(get_db)):
    return db.query(Language).order_by(Language.code).all()


@router.post("", response_model=LanguageResponse, status_code=201)
def create_language(data: LanguageCreate, db: Session = Depends(get_db)):
    existing = db.query(Language).filter(Language.code == data.code).first()
    if existing:
        raise HTTPException(400, f"Language '{data.code}' already exists")
    lang = Language(code=data.code, name=data.name)
    db.add(lang)
    db.commit()
    db.refresh(lang)
    return lang


@router.delete("/{language_id}", status_code=204)
def delete_language(language_id: int, db: Session = Depends(get_db)):
    lang = db.query(Language).filter(Language.id == language_id).first()
    if not lang:
        raise HTTPException(404, "Language not found")
    db.delete(lang)
    db.commit()
