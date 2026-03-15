"""Revision history API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, Revision
from ..schemas import RevisionResponse

router = APIRouter(tags=["revisions"])


def record_revision(
    db: Session,
    project_id: int | None,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str = "anonymous",
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    meta: dict | None = None,
):
    """Record an immutable revision entry."""
    rev = Revision(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        actor=actor,
        meta=json.dumps(meta) if meta else None,
    )
    db.add(rev)


@router.get("/api/projects/{project_id}/revisions", response_model=list[RevisionResponse])
def list_project_revisions(
    project_id: int,
    entity_type: str | None = Query(None),
    action: str | None = Query(None),
    actor: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")

    query = db.query(Revision).filter(Revision.project_id == project_id)
    if entity_type:
        query = query.filter(Revision.entity_type == entity_type)
    if action:
        query = query.filter(Revision.action == action)
    if actor:
        query = query.filter(Revision.actor == actor)

    revisions = query.order_by(Revision.created_at.desc()).offset(offset).limit(limit).all()
    return [_revision_to_response(r) for r in revisions]


@router.get("/api/revisions/{revision_id}", response_model=RevisionResponse)
def get_revision(revision_id: int, db: Session = Depends(get_db)):
    rev = db.query(Revision).filter(Revision.id == revision_id).first()
    if not rev:
        raise HTTPException(404, "Revision not found")
    return _revision_to_response(rev)


@router.get("/api/keys/{key_id}/revisions", response_model=list[RevisionResponse])
def list_key_revisions(
    key_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    revisions = db.query(Revision).filter(
        Revision.entity_type.in_(["key", "translation"]),
        Revision.entity_id == key_id,
    ).order_by(Revision.created_at.desc()).offset(offset).limit(limit).all()
    return [_revision_to_response(r) for r in revisions]


@router.get("/api/translations/{key_id}/{language_id}/revisions", response_model=list[RevisionResponse])
def list_translation_revisions(
    key_id: int,
    language_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    # Filter by meta containing matching key_id and language_id
    revisions = db.query(Revision).filter(
        Revision.entity_type == "translation",
        Revision.meta.ilike(f'%"key_id": {key_id}%'),
        Revision.meta.ilike(f'%"language_id": {language_id}%'),
    ).order_by(Revision.created_at.desc()).offset(offset).limit(limit).all()
    return [_revision_to_response(r) for r in revisions]


def _revision_to_response(rev: Revision) -> RevisionResponse:
    meta = None
    if rev.meta:
        try:
            meta = json.loads(rev.meta)
        except (json.JSONDecodeError, TypeError):
            meta = None
    return RevisionResponse(
        id=rev.id,
        project_id=rev.project_id,
        entity_type=rev.entity_type,
        entity_id=rev.entity_id,
        action=rev.action,
        field_name=rev.field_name,
        old_value=rev.old_value,
        new_value=rev.new_value,
        actor=rev.actor,
        meta=meta,
        created_at=rev.created_at,
    )
