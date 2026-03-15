"""Application configuration."""

import os
from dataclasses import dataclass, field


def _parse_auth_keys() -> list[str]:
    raw = os.environ.get("FLINTSTONE_AUTH_KEYS", "")
    return [k.strip() for k in raw.split(",") if k.strip()] if raw else []


@dataclass
class Settings:
    database_url: str = os.environ.get("FLINTSTONE_DB", "sqlite:///flintstone.db")
    host: str = os.environ.get("FLINTSTONE_HOST", "0.0.0.0")
    port: int = int(os.environ.get("FLINTSTONE_PORT", "8000"))
    debug: bool = os.environ.get("FLINTSTONE_DEBUG", "").lower() in ("1", "true")

    # Authentication
    auth_keys: list[str] = field(default_factory=_parse_auth_keys)
    auth_cookie_secret: str = os.environ.get("FLINTSTONE_SECRET_KEY", "flintstone-dev-secret")
    auth_cookie_name: str = "flintstone_session"

    # Glossary
    glossary_strict: bool = os.environ.get("FLINTSTONE_GLOSSARY_STRICT", "").lower() in ("1", "true")

    # Machine Translation
    mt_default_backend: str = os.environ.get("FLINTSTONE_MT_BACKEND", "")
    mt_google_api_key: str = os.environ.get("FLINTSTONE_MT_GOOGLE_KEY", "")
    mt_deepl_api_key: str = os.environ.get("FLINTSTONE_MT_DEEPL_KEY", "")
    mt_libretranslate_url: str = os.environ.get("FLINTSTONE_MT_LIBRETRANSLATE_URL", "")
    mt_libretranslate_api_key: str = os.environ.get("FLINTSTONE_MT_LIBRETRANSLATE_KEY", "")
    mt_rate_limit: int = int(os.environ.get("FLINTSTONE_MT_RATE_LIMIT", "10"))


settings = Settings()
