"""LibreTranslate backend."""

from .base import MTBackend


class LibreTranslateBackend(MTBackend):
    name = "libretranslate"

    def __init__(self, url: str, api_key: str = ""):
        self.url = url.rstrip("/") if url else ""
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.url)

    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        import httpx

        results = []
        for text in texts:
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
            }
            if self.api_key:
                payload["api_key"] = self.api_key

            response = httpx.post(
                f"{self.url}/translate",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            results.append(data["translatedText"])

        return results
