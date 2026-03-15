"""Google Translate API v2 backend."""

from .base import MTBackend


class GoogleTranslateBackend(MTBackend):
    name = "google"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        import httpx

        url = "https://translation.googleapis.com/language/translate/v2"
        results = []

        # Batch in groups of 50
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            response = httpx.post(url, json={
                "q": batch,
                "source": source_lang,
                "target": target_lang,
                "key": self.api_key,
                "format": "text",
            }, timeout=30)
            response.raise_for_status()
            data = response.json()
            for t in data["data"]["translations"]:
                results.append(t["translatedText"])

        return results
