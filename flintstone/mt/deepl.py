"""DeepL API v2 backend."""

from .base import MTBackend


class DeepLBackend(MTBackend):
    name = "deepl"

    def __init__(self, api_key: str):
        self.api_key = api_key
        # DeepL free API uses a different base URL
        if api_key.endswith(":fx"):
            self.base_url = "https://api-free.deepl.com/v2"
        else:
            self.base_url = "https://api.deepl.com/v2"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        import httpx

        results = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i + 50]
            response = httpx.post(
                f"{self.base_url}/translate",
                data={
                    "text": batch,
                    "source_lang": source_lang.upper(),
                    "target_lang": target_lang.upper(),
                },
                headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            for t in data["translations"]:
                results.append(t["text"])

        return results
