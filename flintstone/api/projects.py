"""Projects API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, TranslationKey
from ..schemas import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.name).all()
    result = []
    for p in projects:
        key_count = db.query(func.count(TranslationKey.id)).filter(
            TranslationKey.project_id == p.id
        ).scalar()
        result.append(ProjectResponse(
            id=p.id, name=p.name, description=p.description,
            created_at=p.created_at, updated_at=p.updated_at,
            key_count=key_count,
        ))
    return result


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.query(Project).filter(Project.name == data.name).first()
    if existing:
        raise HTTPException(400, f"Project '{data.name}' already exists")
    project = Project(name=data.name, description=data.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        created_at=project.created_at, updated_at=project.updated_at, key_count=0,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    key_count = db.query(func.count(TranslationKey.id)).filter(
        TranslationKey.project_id == project.id
    ).scalar()
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        created_at=project.created_at, updated_at=project.updated_at,
        key_count=key_count,
    )


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    db.commit()
    db.refresh(project)
    key_count = db.query(func.count(TranslationKey.id)).filter(
        TranslationKey.project_id == project.id
    ).scalar()
    return ProjectResponse(
        id=project.id, name=project.name, description=project.description,
        created_at=project.created_at, updated_at=project.updated_at,
        key_count=key_count,
    )


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    db.delete(project)
    db.commit()
