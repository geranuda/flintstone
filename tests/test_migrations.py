"""Databases created by Flintstone 0.1 keep working after the upgrade."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from flintstone import native
from flintstone.app import app
from flintstone.database import Base, get_db, upgrade_schema
from flintstone.models import Project

V01_SCHEMA = [
    "CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, description TEXT, "
    "created_at DATETIME, updated_at DATETIME)",
    "CREATE TABLE languages (id INTEGER PRIMARY KEY, code VARCHAR(10) NOT NULL UNIQUE, name VARCHAR(100) NOT NULL)",
    "CREATE TABLE translation_keys (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) "
    "ON DELETE CASCADE, key VARCHAR(500) NOT NULL, description TEXT, tags TEXT, created_at DATETIME, "
    "CONSTRAINT uq_project_key UNIQUE (project_id, key))",
    "CREATE TABLE translations (id INTEGER PRIMARY KEY, key_id INTEGER NOT NULL REFERENCES translation_keys(id) "
    "ON DELETE CASCADE, language_id INTEGER NOT NULL REFERENCES languages(id) ON DELETE CASCADE, value TEXT NOT NULL, "
    "updated_at DATETIME, CONSTRAINT uq_key_language UNIQUE (key_id, language_id))",
    "CREATE TABLE translation_memory (id INTEGER PRIMARY KEY, source_lang VARCHAR(10) NOT NULL, source_text TEXT NOT NULL, "
    "target_lang VARCHAR(10) NOT NULL, target_text TEXT NOT NULL, project_id INTEGER REFERENCES projects(id) "
    "ON DELETE SET NULL, created_at DATETIME)",
    "INSERT INTO projects (id, name, description) VALUES (1, 'old-app', 'from 0.1')",
    "INSERT INTO languages (id, code, name) VALUES (1, 'en', 'English'), (2, 'es', 'Spanish')",
    "INSERT INTO translation_keys (id, project_id, key, description, tags) VALUES (1, 1, 'hello', 'Greeting', 'ui')",
    "INSERT INTO translations (key_id, language_id, value) VALUES (1, 1, 'Hello'), (1, 2, 'Hola')",
]


def test_upgrade_v01_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        for statement in V01_SCHEMA:
            conn.exec_driver_sql(statement)

    Base.metadata.create_all(bind=engine)
    added = upgrade_schema(engine)
    assert "projects.token" in added and "translations.status" in added
    assert upgrade_schema(engine) == []  # idempotent

    columns = {c["name"] for c in inspect(engine).get_columns("translation_keys")}
    assert {"context", "character_limit", "occurrences", "updated_at"} <= columns
    assert "ix_projects_token" in {i["name"] for i in inspect(engine).get_indexes("projects")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM translations")).scalars().all() == ["translated", "translated"]

    Session = sessionmaker(bind=engine)
    with Session() as db:
        assert native.backfill_tokens(db) == 1
        project = db.get(Project, 1)
        assert project.token and project.source_language_code == "en" and not project.languages_configured
        assert [lang.code for lang in native.target_languages(db, project)] == ["es"]
        token = project.token

    def override():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            res = client.get("/cds/content/es", headers={"Authorization": f"Bearer {token}"})
            assert res.json()["data"] == {"hello": {"string": "Hola"}}
            assert client.get("/projects/1").status_code == 200
            assert client.get("/projects/1/translate").status_code == 200
    finally:
        app.dependency_overrides.clear()
