"""SQLAlchemy ORM models."""

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Transifex Native: every project is a resource served by the CDS.
    source_language_code: Mapped[str] = mapped_column(String(35), default="en", server_default="en")
    # False = legacy project that uses every language in the system as a target.
    languages_configured: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    secret_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)

    keys: Mapped[list["TranslationKey"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    language_links: Mapped[list["ProjectLanguage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["ContentJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Language(Base):
    __tablename__ = "languages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    translations: Mapped[list["Translation"]] = relationship(
        back_populates="language", cascade="all, delete-orphan"
    )
    project_links: Mapped[list["ProjectLanguage"]] = relationship(
        back_populates="language", cascade="all, delete-orphan", passive_deletes=True
    )


class ProjectLanguage(Base):
    """A target language enabled for a project."""

    __tablename__ = "project_languages"

    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    language_id: Mapped[int] = mapped_column(Integer, ForeignKey("languages.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    project: Mapped["Project"] = relationship(back_populates="language_links")
    language: Mapped["Language"] = relationship(back_populates="project_links")


class TranslationKey(Base):
    __tablename__ = "translation_keys"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_project_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default="")  # developer comment
    tags: Mapped[str] = mapped_column(Text, default="")  # comma-separated tags
    context: Mapped[str] = mapped_column(Text, default="", server_default="")
    character_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurrences: Mapped[str] = mapped_column(Text, default="", server_default="")  # newline-separated
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="keys")
    translations: Mapped[list["Translation"]] = relationship(
        back_populates="translation_key", cascade="all, delete-orphan"
    )

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    @property
    def occurrence_list(self) -> list[str]:
        return [o for o in (self.occurrences or "").split("\n") if o]


class Translation(Base):
    __tablename__ = "translations"
    __table_args__ = (UniqueConstraint("key_id", "language_id", name="uq_key_language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[int] = mapped_column(Integer, ForeignKey("translation_keys.id", ondelete="CASCADE"), nullable=False)
    language_id: Mapped[int] = mapped_column(Integer, ForeignKey("languages.id", ondelete="CASCADE"), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="translated", server_default="translated")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    translation_key: Mapped["TranslationKey"] = relationship(back_populates="translations")
    language: Mapped["Language"] = relationship(back_populates="translations")


class TranslationMemory(Base):
    __tablename__ = "translation_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_lang: Mapped[str] = mapped_column(String(10), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_lang: Mapped[str] = mapped_column(String(10), nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ContentJob(Base):
    """A content push received through the CDS (``POST /cds/content``)."""

    __tablename__ = "content_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="source")  # "source" or "translations"
    language_code: Mapped[str | None] = mapped_column(String(35), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    total: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    options: Mapped[str] = mapped_column(Text, default="{}")  # JSON push meta
    client: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="jobs")

    @property
    def error_list(self) -> list[dict]:
        return json.loads(self.errors or "[]")

    @property
    def option_dict(self) -> dict:
        return json.loads(self.options or "{}")
