"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# --- Projects ---

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    source_language: str = Field("en", min_length=1, max_length=10)
    # None keeps the legacy behaviour (every language in the system is a target).
    target_languages: list[str] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    key_count: int = 0
    source_language: str = "en"
    target_languages: list[str] = []
    token: str | None = None
    secret: str | None = None  # only returned when a secret is generated
    model_config = {"from_attributes": True}


class ProjectWithStats(ProjectResponse):
    completion: dict[str, float] = {}  # lang_code -> percentage


class ProjectLanguageCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=10)
    name: str | None = None


class ProjectLanguageResponse(BaseModel):
    code: str
    name: str
    localized_name: str
    rtl: bool
    is_source: bool
    plural_categories: list[str]


class CredentialsRotate(BaseModel):
    rotate: Literal["secret", "token", "all"] = "secret"


class CredentialsResponse(BaseModel):
    token: str
    secret: str | None = None
    secret_hint: str | None = None


class JobResponse(BaseModel):
    id: str
    kind: str
    language_code: str | None
    status: str
    total: int
    created: int
    updated: int
    skipped: int
    deleted: int
    failed: int
    errors: list[dict] = []
    options: dict = {}
    client: str
    created_at: datetime
    finished_at: datetime | None


# --- Languages ---

class LanguageCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=10)
    name: str = Field(..., min_length=1, max_length=100)


class LanguageResponse(BaseModel):
    id: int
    code: str
    name: str
    model_config = {"from_attributes": True}


# --- Translation Keys ---

class KeyCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    tags: list[str] = []
    context: str = ""
    character_limit: int | None = Field(None, ge=1)
    occurrences: list[str] = []


class KeyUpdate(BaseModel):
    key: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    context: str | None = None
    character_limit: int | None = Field(None, ge=0)  # 0 removes the limit
    occurrences: list[str] | None = None


class KeyResponse(BaseModel):
    id: int
    project_id: int
    key: str
    description: str | None
    tags: list[str] = []
    context: str = ""
    character_limit: int | None = None
    occurrences: list[str] = []
    created_at: datetime
    translations: dict[str, str] = {}  # lang_code -> value
    model_config = {"from_attributes": True}


# --- Translations ---

TranslationStatus = Literal["translated", "reviewed", "proofread"]


class TranslationUpdate(BaseModel):
    value: str
    status: TranslationStatus | None = None


class TranslationStatusUpdate(BaseModel):
    status: TranslationStatus


class TranslationResponse(BaseModel):
    id: int
    key_id: int
    language_id: int
    value: str
    status: str = "translated"
    updated_at: datetime
    model_config = {"from_attributes": True}


class BulkTranslationItem(BaseModel):
    key: str
    language_code: str
    value: str


class BulkTranslationRequest(BaseModel):
    translations: list[BulkTranslationItem]


# --- Find & Replace ---

class FindReplaceRequest(BaseModel):
    find: str = Field(..., min_length=1)
    replace: str
    language_code: str | None = None  # None = all languages
    preview: bool = True  # True = dry run, False = apply


class FindReplaceMatch(BaseModel):
    key_id: int
    key: str
    language_code: str
    old_value: str
    new_value: str


class FindReplaceResponse(BaseModel):
    matches: list[FindReplaceMatch]
    total: int
    applied: bool


# --- TM Fill-up ---

class FillUpRequest(BaseModel):
    source_lang: str
    target_lang: str
    match_type: str = "exact"  # "exact" or "contains"


class FillUpResult(BaseModel):
    filled: int
    skipped: int
    total_missing: int


# --- Stats ---

class LanguageStats(BaseModel):
    language_code: str
    language_name: str
    translated: int
    total: int
    percentage: float
    reviewed: int = 0
    is_source: bool = False


class ProjectStats(BaseModel):
    project_id: int
    project_name: str
    total_keys: int
    languages: list[LanguageStats]


# --- Translation Memory ---

class TMEntry(BaseModel):
    id: int
    source_lang: str
    source_text: str
    target_lang: str
    target_text: str
    project_id: int | None
    created_at: datetime
    model_config = {"from_attributes": True}


class TMSuggestion(BaseModel):
    source_text: str
    target_text: str
    match_type: str  # "exact", "contains"
    project_id: int | None
