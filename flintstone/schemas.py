"""Pydantic request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Projects ---

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""


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
    model_config = {"from_attributes": True}


class ProjectWithStats(ProjectResponse):
    completion: dict[str, float] = {}  # lang_code -> percentage


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


class KeyUpdate(BaseModel):
    key: str | None = None
    description: str | None = None


class KeyResponse(BaseModel):
    id: int
    project_id: int
    key: str
    description: str | None
    created_at: datetime
    translations: dict[str, str] = {}  # lang_code -> value
    model_config = {"from_attributes": True}


# --- Translations ---

class TranslationUpdate(BaseModel):
    value: str


class TranslationResponse(BaseModel):
    id: int
    key_id: int
    language_id: int
    value: str
    updated_at: datetime
    model_config = {"from_attributes": True}


class BulkTranslationItem(BaseModel):
    key: str
    language_code: str
    value: str


class BulkTranslationRequest(BaseModel):
    translations: list[BulkTranslationItem]


# --- Stats ---

class LanguageStats(BaseModel):
    language_code: str
    language_name: str
    translated: int
    total: int
    percentage: float


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
