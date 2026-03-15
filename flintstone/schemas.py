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
    tags: list[str] = []


class KeyUpdate(BaseModel):
    key: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class KeyResponse(BaseModel):
    id: int
    project_id: int
    key: str
    description: str | None
    tags: list[str] = []
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
    match_type: str = "exact"  # "exact", "contains", or "fuzzy"
    min_similarity: float = Field(0.6, ge=0.0, le=1.0)


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
    match_type: str  # "exact", "contains", "fuzzy"
    similarity_score: float = 1.0
    project_id: int | None


# --- Auth ---

class LoginRequest(BaseModel):
    api_key: str


# --- Revision History ---

class RevisionResponse(BaseModel):
    id: int
    project_id: int | None
    entity_type: str
    entity_id: int
    action: str
    field_name: str | None
    old_value: str | None
    new_value: str | None
    actor: str
    meta: dict | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


# --- Glossary ---

class GlossaryTranslationSchema(BaseModel):
    language_code: str
    approved_value: str


class GlossaryTermCreate(BaseModel):
    source_term: str = Field(..., min_length=1, max_length=500)
    source_language: str = Field(..., min_length=1, max_length=10)
    description: str = ""
    case_sensitive: bool = False
    translations: list[GlossaryTranslationSchema] = []


class GlossaryTermUpdate(BaseModel):
    source_term: str | None = None
    description: str | None = None
    case_sensitive: bool | None = None


class GlossaryTermResponse(BaseModel):
    id: int
    source_term: str
    source_language: str
    description: str | None
    case_sensitive: bool
    translations: dict[str, str] = {}  # lang_code -> approved_value
    created_at: datetime
    model_config = {"from_attributes": True}


class GlossaryViolation(BaseModel):
    term_id: int
    source_term: str
    expected_value: str
    severity: str = "warning"


class GlossaryCheckRequest(BaseModel):
    source_text: str
    source_lang: str
    target_text: str
    target_lang: str


# --- Webhooks ---

class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)
    events: list[str]
    secret: str | None = None
    project_id: int | None = None


class WebhookUpdate(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None
    secret: str | None = None


class WebhookResponse(BaseModel):
    id: int
    url: str
    secret: str | None
    events: list[str]
    project_id: int | None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: int
    webhook_id: int
    event: str
    payload: str
    status_code: int | None
    success: bool
    attempts: int
    last_attempt_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


# --- Machine Translation ---

class MTTranslateRequest(BaseModel):
    source_lang: str
    target_lang: str
    texts: list[str] = Field(..., max_length=100)
    backend: str | None = None


class MTTranslateResponse(BaseModel):
    translations: list[str]
    backend: str
    character_count: int


class MTPreTranslateRequest(BaseModel):
    source_lang: str
    target_lang: str
    overwrite: bool = False
    backend: str | None = None


class MTPreTranslateResponse(BaseModel):
    translated: int
    skipped: int
    total: int
    backend: str
    character_count: int


class MTConfigResponse(BaseModel):
    available_backends: list[str]
    default_backend: str | None
    backends: dict[str, bool]
