"""Minimal CDS client used by the ``flintstone`` CLI (standard library only).

Speaks the Transifex Native CDS protocol, so it works against Flintstone and
against any other CDS implementation.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

DEFAULT_CDS_HOST = "http://localhost:8000/cds"


class CDSClientError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"CDS responded with {status}: {message}" if status else message)
        self.status = status
        self.message = message


class CDSClient:
    def __init__(self, host: str, token: str, secret: str | None = None, timeout: float = 120.0):
        self.host = host.rstrip("/")
        self.token = token
        self.secret = secret
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None, with_secret: bool = False,
                 params: dict | None = None) -> tuple[int, dict | None]:
        url = self.host + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="[],")
        credentials = f"{self.token}:{self.secret}" if with_secret and self.secret else self.token
        headers = {
            "Authorization": f"Bearer {credentials}",
            "Accept-version": "v2",
            "Content-Type": "application/json; charset=utf-8",
            "X-NATIVE-SDK": f"flintstone/cli/{__version__}",
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                message = json.loads(raw).get("message") or raw.decode("utf-8", "replace")
            except (ValueError, AttributeError):
                message = raw.decode("utf-8", "replace") or exc.reason
            raise CDSClientError(exc.code, str(message))
        except urllib.error.URLError as exc:
            raise CDSClientError(0, f"Cannot reach {url}: {exc.reason}")

    def languages(self) -> dict:
        return self._request("GET", "/languages")[1] or {}

    def content(self, language: str, tags: list[str] | None = None, status: str | None = None,
                retries: int = 20, interval: float = 1.0) -> dict[str, dict]:
        params = {}
        if tags:
            params["filter[tags]"] = ",".join(tags)
        if status:
            params["filter[status]"] = status
        path = "/content/" + urllib.parse.quote(language)
        for _ in range(retries + 1):
            code, payload = self._request("GET", path, params=params)
            if code != 202:
                return (payload or {}).get("data", {})
            time.sleep(interval)  # content is being prepared
        raise CDSClientError(202, f"Content for '{language}' was not ready after {retries} retries")

    def push_source(self, data: dict, meta: dict) -> str:
        _, payload = self._request("POST", "/content", {"data": data, "meta": meta}, with_secret=True)
        return payload["data"]["links"]["job"]

    def push_translations(self, language: str, data: dict, meta: dict) -> str:
        path = "/content/" + urllib.parse.quote(language)
        _, payload = self._request("POST", path, {"data": data, "meta": meta}, with_secret=True)
        return payload["data"]["links"]["job"]

    def job(self, link: str) -> dict:
        return (self._request("GET", link, with_secret=True)[1] or {}).get("data", {})

    def wait(self, link: str, interval: float = 1.0, max_polls: int = 300) -> dict:
        for _ in range(max_polls):
            status = self.job(link)
            if status.get("status") not in ("pending", "processing"):
                return status
            time.sleep(interval)
        raise CDSClientError(0, f"Job {link} did not finish after {max_polls} polls")

    def invalidate(self, language: str | None = None, purge: bool = False) -> dict:
        path = "/purge" if purge else "/invalidate"
        if language:
            path += "/" + urllib.parse.quote(language)
        return (self._request("POST", path, {}, with_secret=True)[1] or {}).get("data", {})
