"""MT backend factory."""

from ..config import settings
from .base import MTBackend
from .deepl import DeepLBackend
from .google import GoogleTranslateBackend
from .libretranslate import LibreTranslateBackend


def _all_backends() -> list[MTBackend]:
    """Return all backend instances."""
    return [
        GoogleTranslateBackend(settings.mt_google_api_key),
        DeepLBackend(settings.mt_deepl_api_key),
        LibreTranslateBackend(settings.mt_libretranslate_url, settings.mt_libretranslate_api_key),
    ]


def get_available_backends() -> list[str]:
    """Return names of configured backends."""
    return [b.name for b in _all_backends() if b.is_configured()]


def get_backend(name: str | None = None) -> MTBackend:
    """Get a specific backend by name, or the default configured backend."""
    target = name or settings.mt_default_backend
    for b in _all_backends():
        if b.name == target and b.is_configured():
            return b

    # Fallback: return the first configured backend
    for b in _all_backends():
        if b.is_configured():
            return b

    raise ValueError("No MT backend configured. Set FLINTSTONE_MT_BACKEND and provide API keys.")
