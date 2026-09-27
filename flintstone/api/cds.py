"""Transifex Native Content Delivery Service (CDS) API.

Wire-compatible with Transifex's open-source CDS (transifex-delivery), so the
official Transifex Native SDKs and CLIs work against Flintstone unchanged:
point their ``cdsHost`` at ``http(s)://<flintstone-host>/cds``.

Authentication follows the CDS convention::

    Authorization: Bearer <project-token>            # read content
    Authorization: Bearer <project-token>:<secret>   # push, jobs, invalidate
"""

import hashlib
import json
import re

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, MutableHeaders

from .. import locales, native
from ..database import get_db
from ..models import ContentJob, Project

PREFIX = "/cds"

router = APIRouter(prefix=PREFIX, tags=["cds (Transifex Native)"])


class CDSError(Exception):
    """Error rendered in the CDS format: ``{"status": 404, "message": "..."}``."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def cds_error_handler(request: Request, exc: CDSError) -> JSONResponse:
    return JSONResponse({"status": exc.status, "message": exc.message}, status_code=exc.status)


class CDSAuth:
    def __init__(self, project: Project, has_secret: bool):
        self.project = project
        self.has_secret = has_secret


def _client(request: Request) -> str:
    return request.headers.get("x-native-sdk") or request.headers.get("user-agent", "")


def authenticate(request: Request, db: Session = Depends(get_db)) -> CDSAuth:
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    credentials = credentials.strip()
    if scheme.lower() != "bearer" or not credentials:
        raise CDSError(401, "Unauthorized")
    token, has_colon, secret = credentials.partition(":")
    project = db.query(Project).filter(Project.token == token).first() if token else None
    if project is None:
        raise CDSError(403, "Forbidden")
    supplied = secret if has_colon else request.headers.get("x-transifex-trust-secret")
    if supplied is not None and not native.check_secret(project, supplied):
        raise CDSError(403, "Forbidden")
    return CDSAuth(project, supplied is not None)


def require_secret(auth: CDSAuth = Depends(authenticate)) -> CDSAuth:
    if not auth.has_secret:
        raise CDSError(403, "Forbidden: this endpoint requires the project secret")
    return auth


async def _json_body(request: Request) -> dict:
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise CDSError(400, "Request body must be valid JSON")
    if not isinstance(payload, dict):
        raise CDSError(400, "Request body must be a JSON object")
    return payload


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    candidates = [c.strip().removeprefix("W/") for c in header.split(",")]
    return "*" in candidates or etag in candidates


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/languages")
def get_languages(request: Request, auth: CDSAuth = Depends(authenticate), db: Session = Depends(get_db)):
    project = auth.project
    data = []
    for lang in native.project_languages(db, project):
        info = locales.locale_info(lang.code)
        data.append({"name": lang.name, "code": lang.code, "localized_name": info.localized_name, "rtl": info.rtl})
    src = native.source_language(db, project)
    native.record_activity(project.id, "languages", _client(request), count=len(data))
    return {"data": data, "meta": {"source_lang_code": src.code if src else project.source_language_code}}


@router.get("/content/{lang_code}")
def get_content(lang_code: str, request: Request, auth: CDSAuth = Depends(authenticate),
                db: Session = Depends(get_db)):
    """Translations for one language: ``{"data": {key: {"string": value}}}``.

    Supports ``filter[tags]=a,b`` (strings having all tags) and
    ``filter[status]=translated|reviewed|proofread|finalized``.
    """
    project = auth.project
    client = _client(request)
    language = native.find_project_language(db, project, lang_code)
    if language is None:
        native.record_activity(project.id, "content", client, lang_code, status=404)
        raise CDSError(404, f"Language '{lang_code}' is not enabled for this project")
    tags = [t.strip() for t in request.query_params.get("filter[tags]", "").split(",") if t.strip()]
    status = request.query_params.get("filter[status]") or None
    if status and status not in native.STATUS_FILTERS:
        raise CDSError(400, f"Invalid status filter '{status}'; use one of {', '.join(native.STATUS_FILTERS)}")

    data = native.build_content(db, project, language, tags=tags, status=status)
    body = json.dumps({"data": data, "meta": {}}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    etag = '"' + hashlib.sha1(body).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        native.record_activity(project.id, "content", client, language.code, status=304, count=len(data))
        return Response(status_code=304, headers=headers)
    native.record_activity(project.id, "content", client, language.code, count=len(data))
    return Response(body, media_type="application/json", headers=headers)


def _job_created(job: ContentJob) -> JSONResponse:
    return JSONResponse({"data": {"id": job.id, "links": {"job": f"/jobs/content/{job.id}"}}}, status_code=202)


@router.post("/content", status_code=202)
async def push_content(request: Request, auth: CDSAuth = Depends(require_secret), db: Session = Depends(get_db)):
    """Push source strings. Meta flags: purge, override_tags, override_occurrences,
    keep_translations (default true) and dry_run."""
    payload = await _json_body(request)
    try:
        job = await run_in_threadpool(
            native.push_source, db, auth.project, payload.get("data"), payload.get("meta"), _client(request)
        )
    except native.PushInProgress:
        raise CDSError(409, "Another content upload is already in progress")
    except ValueError as exc:
        raise CDSError(400, str(exc))
    native.record_activity(auth.project.id, "push", _client(request), count=job.total)
    return _job_created(job)


@router.post("/content/{lang_code}", status_code=202)
async def push_translations(lang_code: str, request: Request, auth: CDSAuth = Depends(require_secret),
                            db: Session = Depends(get_db)):
    """Flintstone extension: import existing translations for one language.

    Body: ``{"data": {key: {"string": "...", "status": "translated"}}, "meta":
    {"override_translations": false, "dry_run": false}}``. Useful when moving an
    app that is already localized (e.g. String Catalogs) to Flintstone.
    """
    payload = await _json_body(request)

    def run():
        language = native.find_project_language(db, auth.project, lang_code)
        if language is None:
            raise CDSError(404, f"Language '{lang_code}' is not enabled for this project")
        src = native.source_language(db, auth.project)
        if src and src.id == language.id:
            raise CDSError(400, "Use POST /content to push source strings")
        return native.push_translations(
            db, auth.project, language, payload.get("data"), payload.get("meta"), _client(request)
        )

    try:
        job = await run_in_threadpool(run)
    except native.PushInProgress:
        raise CDSError(409, "Another content upload is already in progress")
    except ValueError as exc:
        raise CDSError(400, str(exc))
    native.record_activity(auth.project.id, "push", _client(request), job.language_code or "", count=job.total)
    return _job_created(job)


@router.get("/jobs/content/{job_id}")
def get_job(job_id: str, auth: CDSAuth = Depends(require_secret), db: Session = Depends(get_db)):
    job = db.query(ContentJob).filter(ContentJob.id == job_id, ContentJob.project_id == auth.project.id).first()
    if job is None:
        raise CDSError(404, "Job not found")
    return native.job_payload(job)


def _refresh(action: str, request: Request, auth: CDSAuth, db: Session, lang_code: str | None) -> dict:
    project = auth.project
    if lang_code:
        language = native.find_project_language(db, project, lang_code)
        if language is None:
            raise CDSError(404, f"Language '{lang_code}' is not enabled for this project")
        count = 1
    else:
        count = len(native.project_languages(db, project))
    # Content is always served fresh from the database, so there is nothing
    # stale to drop; report the number of language resources as the CDS does.
    native.record_activity(project.id, action, _client(request), lang_code or "", count=count)
    return {"data": {"status": "success", "token": project.token, "count": count}}


@router.post("/invalidate")
@router.post("/invalidate/{lang_code}")
def invalidate(request: Request, lang_code: str | None = None, auth: CDSAuth = Depends(require_secret),
               db: Session = Depends(get_db)):
    return _refresh("invalidate", request, auth, db, lang_code)


@router.post("/purge")
@router.post("/purge/{lang_code}")
def purge(request: Request, lang_code: str | None = None, auth: CDSAuth = Depends(require_secret),
          db: Session = Depends(get_db)):
    return _refresh("purge", request, auth, db, lang_code)


_ALLOWED_HEADERS = "Authorization, Content-Type, Accept-Version, X-NATIVE-SDK, If-None-Match, X-TRANSIFEX-TRUST-SECRET"


class CDSMiddleware:
    """ASGI middleware for ``/cds``: CORS for browser SDKs and '//' tolerance.

    Browser SDKs call the CDS cross-origin, so CDS routes (and only those) allow
    any origin. SDKs build URLs by concatenation, so a ``cdsHost`` configured
    with a trailing slash produces ``/cds//content/...``; collapse those.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = re.sub(r"/{2,}", "/", scope["path"])
        if path != PREFIX and not path.startswith(PREFIX + "/"):
            await self.app(scope, receive, send)
            return
        if path != scope["path"]:
            scope = dict(scope, path=path, raw_path=path.encode())

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if scope["method"] == "OPTIONS" and origin and headers.get("access-control-request-method"):
            preflight = Response(status_code=204, headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": headers.get("access-control-request-headers") or _ALLOWED_HEADERS,
                "Access-Control-Max-Age": "86400",
            })
            await preflight(scope, receive, send)
            return
        if not origin:
            await self.app(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Access-Control-Allow-Origin"] = "*"
                response_headers["Access-Control-Expose-Headers"] = "ETag"
            await send(message)

        await self.app(scope, receive, send_with_cors)
