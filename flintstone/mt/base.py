"""Abstract base class for MT backends."""

from abc import ABC, abstractmethod


class MTBackend(ABC):
    """Base class for machine translation backends."""

    name: str = ""

    @abstractmethod
    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        """Translate a batch of texts."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if this backend has the required configuration."""
        ...
