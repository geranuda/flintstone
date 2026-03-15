"""Application configuration."""

import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = os.environ.get("FLINTSTONE_DB", "sqlite:///flintstone.db")
    host: str = os.environ.get("FLINTSTONE_HOST", "0.0.0.0")
    port: int = int(os.environ.get("FLINTSTONE_PORT", "8000"))
    debug: bool = os.environ.get("FLINTSTONE_DEBUG", "").lower() in ("1", "true")


settings = Settings()
