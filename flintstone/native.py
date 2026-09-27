"""Transifex Native services: credentials, project languages, CDS push and pull.

Every Flintstone project doubles as a Transifex Native "resource": SDKs read
translations with the public project token, and CLIs push source strings with
``token:secret``. The HTTP layer lives in ``api/cds.py``; this module holds the
logic so the web UI and tests can reuse it.
"""

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from . import locales
from .models import (
    ContentJob,
    Language,
    Project,
    ProjectLanguage,
    Translation,
    TranslationKey,
    TranslationMemory,
)

TOKEN_PREFIX = "1/"
STATUSES = ("translated", "reviewed", "proofread")
STATUS_FILTERS = ("translated", "reviewed", "proofread", "finalized")
_STATUS_RANK = {"translated": 1, "reviewed": 2, "proofread": 3}

# Push flags from the CDS protocol and their defaults.
SOURCE_PUSH_FLAGS = {
    "purge": False,
    "override_tags": False,
    "override_occurrences": False,
    "keep_translations": True,
    "dry_run": False,
}
TRANSLATION_PUSH_FLAGS = {
    "override_translations": False,
    "dry_run": False,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _chunks(items: list, size: int = 500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --- Credentials ---

def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_hex(20)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_token(project: Project) -> str:
    project.token = generate_token()
    return project.token


def issue_secret(project: Project) -> str:
    """Create a new secret. Only its hash is stored, so show it to the user now."""
    secret = generate_token()
    project.secret_hash = hash_secret(secret)
    project.secret_hint = secret[-4:]
    return secret


def check_secret(project: Project, secret: str | None) -> bool:
    if not project.secret_hash or not secret:
        return False
    return hmac.compare_digest(project.secret_hash, hash_secret(secret))


def backfill_tokens(db: Session) -> int:
    """Give projects created before Native support a CDS token."""
    projects = db.query(Project).filter(Project.token.is_(None)).all()
    for project in projects:
        issue_token(project)
    if projects:
        db.commit()
    return len(projects)


# --- Languages ---

def find_language(db: Session, code: str) -> Language | None:
    exact = db.query(Language).filter(Language.code == code).first()
    if exact:
        return exact
    wanted = locales.code_key(code)
    for lang in db.query(Language).all():
        if locales.code_key(lang.code) == wanted:
            return lang
    return None


def ensure_language(db: Session, code: str, name: str | None = None) -> Language:
    lang = find_language(db, code)
    if lang:
        return lang
    if not locales.is_valid_code(code):
        raise ValueError(f"'{code}' is not a valid language code (expected e.g. 'fr', 'es-MX', 'zh-Hans')")
    info = locales.locale_info(code)
    lang = Language(code=info.code, name=name or info.name)
    db.add(lang)
    db.flush()
    return lang


def source_language(db: Session, project: Project, create: bool = False) -> Language | None:
    code = project.source_language_code or "en"
    return ensure_language(db, code) if create else find_language(db, code)


def target_languages(db: Session, project: Project) -> list[Language]:
    if project.languages_configured:
        return (
            db.query(Language)
            .join(ProjectLanguage, ProjectLanguage.language_id == Language.id)
            .filter(ProjectLanguage.project_id == project.id)
            .order_by(Language.code)
            .all()
        )
    # Legacy projects translate into every language known to the system.
    src = source_language(db, project)
    return [
        lang for lang in db.query(Language).order_by(Language.code).all()
        if src is None or lang.id != src.id
    ]


def project_languages(db: Session, project: Project) -> list[Language]:
    """Source language (if known) followed by the target languages."""
    src = source_language(db, project)
    return ([src] if src else []) + target_languages(db, project)


def find_project_language(db: Session, project: Project, code: str) -> Language | None:
    for lang in project_languages(db, project):
        if locales.same_code(lang.code, code):
            return lang
    return None


def _materialize_targets(db: Session, project: Project) -> None:
    """Switch a legacy project to an explicit target-language list."""
    if project.languages_configured:
        return
    for lang in target_languages(db, project):
        db.add(ProjectLanguage(project_id=project.id, language_id=lang.id))
    project.languages_configured = True
    db.flush()


def add_target_language(db: Session, project: Project, code: str, name: str | None = None) -> Language:
    _materialize_targets(db, project)
    lang = ensure_language(db, code, name)
    src = source_language(db, project)
    if src and src.id == lang.id:
        raise ValueError(f"'{lang.code}' is the source language of this project")
    exists = db.query(ProjectLanguage).filter_by(project_id=project.id, language_id=lang.id).first()
    if not exists:
        db.add(ProjectLanguage(project_id=project.id, language_id=lang.id))
        db.flush()
    return lang


def remove_target_language(db: Session, project: Project, code: str) -> bool:
    _materialize_targets(db, project)
    lang = find_language(db, code)
    if not lang:
        return False
    removed = db.query(ProjectLanguage).filter_by(project_id=project.id, language_id=lang.id).delete()
    db.flush()
    return bool(removed)


def configure_languages(db: Session, project: Project, source: str, targets: list[str]) -> None:
    project.source_language_code = locales.normalize_code(source)
    src = ensure_language(db, project.source_language_code)
    project.languages_configured = True
    db.flush()
    for code in targets:
        lang = ensure_language(db, code)
        if lang.id != src.id and not db.query(ProjectLanguage).filter_by(
            project_id=project.id, language_id=lang.id
        ).first():
            db.add(ProjectLanguage(project_id=project.id, language_id=lang.id))
            db.flush()


# --- Tags and occurrences ---

def clean_list(value, forbidden: str = "") -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for item in value:
        text_value = str(item)
        for ch in forbidden:
            text_value = text_value.replace(ch, " ")
        text_value = text_value.strip()
        if text_value and text_value not in out:
            out.append(text_value)
    return out


def merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    return existing + [item for item in incoming if item not in existing]


# --- Stats ---

def language_stats(db: Session, project: Project) -> list[dict]:
    total = db.query(func.count(TranslationKey.id)).filter(TranslationKey.project_id == project.id).scalar() or 0
    rows = (
        db.query(
            Translation.language_id,
            func.count(Translation.id),
            func.sum(case((Translation.status.in_(("reviewed", "proofread")), 1), else_=0)),
        )
        .join(TranslationKey, Translation.key_id == TranslationKey.id)
        .filter(TranslationKey.project_id == project.id, Translation.value != "")
        .group_by(Translation.language_id)
        .all()
    )
    counts = {lang_id: (translated, reviewed or 0) for lang_id, translated, reviewed in rows}
    src = source_language(db, project)
    stats = []
    for lang in project_languages(db, project):
        translated, reviewed = counts.get(lang.id, (0, 0))
        stats.append({
            "language": lang,
            "is_source": bool(src and src.id == lang.id),
            "translated": translated,
            "reviewed": reviewed,
            "total": total,
            "percentage": round(translated / total * 100, 1) if total else 0.0,
            "reviewed_percentage": round(reviewed / total * 100, 1) if total else 0.0,
        })
    return stats


# --- Content delivery (pull) ---

def status_matches(actual: str | None, wanted: str) -> bool:
    if wanted == "finalized":
        wanted = "reviewed"
    return _STATUS_RANK.get(actual or "translated", 1) >= _STATUS_RANK[wanted]


def build_content(
    db: Session,
    project: Project,
    language: Language,
    tags: list[str] | None = None,
    status: str | None = None,
) -> dict[str, dict[str, str]]:
    """Strings for one language in CDS format: ``{key: {"string": value}}``.

    Untranslated strings are included with an empty value (SDKs then fall back
    to their missing-translation policy), unless a status filter is given.
    """
    src = source_language(db, project)
    is_source = bool(src and src.id == language.id)
    keys = (
        db.query(TranslationKey.id, TranslationKey.key, TranslationKey.tags)
        .filter(TranslationKey.project_id == project.id)
        .order_by(TranslationKey.key)
        .all()
    )
    if tags:
        wanted = set(tags)
        keys = [k for k in keys if wanted <= set(clean_list((k.tags or "").split(",")))]
    values = {
        key_id: (value, st)
        for key_id, value, st in db.query(Translation.key_id, Translation.value, Translation.status)
        .join(TranslationKey, Translation.key_id == TranslationKey.id)
        .filter(TranslationKey.project_id == project.id, Translation.language_id == language.id)
    }
    data: dict[str, dict[str, str]] = {}
    for key_id, key, _ in keys:
        value, st = values.get(key_id, ("", None))
        if status and not is_source and (not value or not status_matches(st, status)):
            continue
        data[key] = {"string": value or ""}
    return data


# --- Content push ---

class PushInProgress(Exception):
    """Another push for the same project is still running."""


_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _project_lock(project_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks[project_id]


def parse_flags(meta, defaults: dict[str, bool]) -> dict[str, bool]:
    meta = meta if isinstance(meta, dict) else {}
    flags = {}
    for name, default in defaults.items():
        value = meta.get(name, default)
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        flags[name] = bool(value)
    return flags


def _job_error(key, detail: str, code: str = "invalid", title: str = "Invalid string") -> dict:
    # Every field is a string: the iOS SDK decodes errors as [String: String].
    return {"status": "400", "code": code, "title": title, "detail": detail, "source": {"key": str(key)}}


def _context_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value if str(v))
    return str(value)


def _char_limit(value) -> int | None:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def _finish_job(db: Session, project: Project, kind: str, started: datetime, counts: dict,
                errors: list, options: dict, client: str, total: int,
                language_code: str | None = None) -> ContentJob:
    succeeded = counts["created"] + counts["updated"] + counts["skipped"] + counts["deleted"]
    job = ContentJob(
        id=uuid.uuid4().hex,
        project_id=project.id,
        kind=kind,
        language_code=language_code,
        status="failed" if counts["failed"] and not succeeded else "completed",
        total=total,
        errors=json.dumps(errors, ensure_ascii=False),
        options=json.dumps(options),
        client=(client or "")[:255],
        created_at=started,
        finished_at=_utcnow(),
        **counts,
    )
    db.add(job)
    db.commit()
    return job


def push_source(db: Session, project: Project, data, meta=None, client: str = "") -> ContentJob:
    """Apply a ``POST /content`` payload (source strings) to a project."""
    if not isinstance(data, dict):
        raise ValueError("'data' must be an object mapping keys to source strings")
    options = parse_flags(meta, SOURCE_PUSH_FLAGS)
    lock = _project_lock(project.id)
    if not lock.acquire(blocking=False):
        raise PushInProgress()
    try:
        return _push_source(db, project, data, options, client)
    finally:
        lock.release()


def _push_source(db: Session, project: Project, data: dict, options: dict, client: str) -> ContentJob:
    started = _utcnow()
    counts = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0, "failed": 0}
    errors: list[dict] = []
    src = source_language(db, project, create=True)

    existing = {tk.key: tk for tk in db.query(TranslationKey).filter(TranslationKey.project_id == project.id)}
    original_keys = set(existing)
    source_rows = {
        t.key_id: t
        for t in db.query(Translation)
        .join(TranslationKey, Translation.key_id == TranslationKey.id)
        .filter(TranslationKey.project_id == project.id, Translation.language_id == src.id)
    }
    source_changed: list[int] = []

    for key, entry in data.items():
        if key == "":
            counts["failed"] += 1
            errors.append(_job_error(key, "Empty key", code="empty_key"))
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("string"), str):
            counts["failed"] += 1
            errors.append(_job_error(key, "Each entry must be an object with a 'string' field"))
            continue
        string = entry["string"]
        meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
        tags = clean_list(meta.get("tags"), forbidden=",")
        occurrences = clean_list(meta.get("occurrences"), forbidden="\n")

        tk = existing.get(key)
        if tk is None:
            tk = TranslationKey(
                project_id=project.id,
                key=key,
                description=str(meta.get("developer_comment") or ""),
                tags=",".join(tags),
                context=_context_text(meta.get("context")),
                character_limit=_char_limit(meta.get("character_limit")),
                occurrences="\n".join(occurrences),
            )
            tk.translations.append(Translation(language_id=src.id, value=string))
            db.add(tk)
            existing[key] = tk
            counts["created"] += 1
            continue

        changed = False
        row = source_rows.get(tk.id)
        if row is None:
            db.add(Translation(key_id=tk.id, language_id=src.id, value=string))
            changed = True
        elif row.value != string:
            row.value = string
            source_changed.append(tk.id)
            changed = True
        if "developer_comment" in meta:
            comment = str(meta.get("developer_comment") or "")
            if (tk.description or "") != comment:
                tk.description = comment
                changed = True
        if "character_limit" in meta:
            limit = _char_limit(meta.get("character_limit"))
            if tk.character_limit != limit:
                tk.character_limit = limit
                changed = True
        if "context" in meta:
            context = _context_text(meta.get("context"))
            if (tk.context or "") != context:
                tk.context = context
                changed = True
        if "tags" in meta or options["override_tags"]:
            new_tags = tags if options["override_tags"] else merge_unique(tk.tag_list, tags)
            if new_tags != tk.tag_list:
                tk.tags = ",".join(new_tags)
                changed = True
        if "occurrences" in meta or options["override_occurrences"]:
            new_occurrences = (
                occurrences if options["override_occurrences"]
                else merge_unique(tk.occurrence_list, occurrences)
            )
            if new_occurrences != tk.occurrence_list:
                tk.occurrences = "\n".join(new_occurrences)
                changed = True
        counts["updated" if changed else "skipped"] += 1

    db.flush()
    for ids in _chunks(source_changed):
        translations = db.query(Translation).filter(
            Translation.key_id.in_(ids), Translation.language_id != src.id
        )
        if options["keep_translations"]:
            # The source moved on, so earlier reviews no longer vouch for it.
            translations.filter(Translation.status != "translated").update(
                {"status": "translated"}, synchronize_session=False
            )
        else:
            translations.delete(synchronize_session=False)

    if options["purge"]:
        stale_ids = [existing[k].id for k in original_keys if k not in data]
        for ids in _chunks(stale_ids):
            db.query(Translation).filter(Translation.key_id.in_(ids)).delete(synchronize_session=False)
            db.query(TranslationKey).filter(TranslationKey.id.in_(ids)).delete(synchronize_session=False)
        counts["deleted"] = len(stale_ids)

    if options["dry_run"]:
        db.rollback()
    else:
        project.updated_at = _utcnow()
        db.commit()
    return _finish_job(db, project, "source", started, counts, errors, options, client, len(data))


def push_translations(db: Session, project: Project, language: Language, data, meta=None,
                      client: str = "") -> ContentJob:
    """Import existing translations for one target language (Flintstone extension).

    ``data`` maps keys to ``{"string": ..., "status": ...}`` (or plain strings).
    Unknown keys are skipped; existing translations are only replaced when
    ``override_translations`` is set.
    """
    if not isinstance(data, dict):
        raise ValueError("'data' must be an object mapping keys to translations")
    options = parse_flags(meta, TRANSLATION_PUSH_FLAGS)
    lock = _project_lock(project.id)
    if not lock.acquire(blocking=False):
        raise PushInProgress()
    try:
        return _push_translations(db, project, language, data, options, client)
    finally:
        lock.release()


def _push_translations(db: Session, project: Project, language: Language, data: dict,
                       options: dict, client: str) -> ContentJob:
    started = _utcnow()
    counts = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0, "failed": 0}
    errors: list[dict] = []
    src = source_language(db, project)

    key_ids = dict(
        db.query(TranslationKey.key, TranslationKey.id).filter(TranslationKey.project_id == project.id)
    )
    base = (
        db.query(Translation)
        .join(TranslationKey, Translation.key_id == TranslationKey.id)
        .filter(TranslationKey.project_id == project.id)
    )
    current = {t.key_id: t for t in base.filter(Translation.language_id == language.id)}
    sources = {t.key_id: t.value for t in base.filter(Translation.language_id == src.id)} if src else {}
    tm_pairs = set()
    if src:
        tm_pairs = set(
            db.query(TranslationMemory.source_lang, TranslationMemory.source_text,
                     TranslationMemory.target_lang, TranslationMemory.target_text)
            .filter(TranslationMemory.source_lang.in_((src.code, language.code)),
                    TranslationMemory.target_lang.in_((src.code, language.code)))
        )

    for key, entry in data.items():
        if isinstance(entry, str):
            value, status = entry, None
        elif isinstance(entry, dict):
            value, status = entry.get("string"), entry.get("status")
        else:
            value, status = None, None
        if not isinstance(value, str):
            counts["failed"] += 1
            errors.append(_job_error(key, "Each entry must be an object with a 'string' field"))
            continue
        if status is not None and status not in STATUSES:
            counts["failed"] += 1
            errors.append(_job_error(key, f"Unknown status '{status}'", code="invalid_status"))
            continue
        key_id = key_ids.get(key)
        if key_id is None or not value:
            counts["skipped"] += 1
            continue
        row = current.get(key_id)
        if row is None:
            row = Translation(key_id=key_id, language_id=language.id, value=value, status=status or "translated")
            db.add(row)
            current[key_id] = row
            counts["created"] += 1
        elif row.value == value:
            if status and row.status != status:
                row.status = status
                counts["updated"] += 1
            else:
                counts["skipped"] += 1
            continue
        elif options["override_translations"]:
            row.value = value
            row.status = status or "translated"
            counts["updated"] += 1
        else:
            counts["skipped"] += 1
            continue

        source_text = sources.get(key_id)
        if source_text:
            for pair in ((src.code, source_text, language.code, value),
                         (language.code, value, src.code, source_text)):
                if pair not in tm_pairs:
                    tm_pairs.add(pair)
                    db.add(TranslationMemory(source_lang=pair[0], source_text=pair[1], target_lang=pair[2],
                                             target_text=pair[3], project_id=project.id))

    if options["dry_run"]:
        db.rollback()
    else:
        project.updated_at = _utcnow()
        db.commit()
    return _finish_job(db, project, "translations", started, counts, errors, options, client,
                       len(data), language_code=language.code)


def job_payload(job: ContentJob) -> dict:
    """``GET /jobs/content/{id}`` body."""
    data: dict = {"status": job.status, "errors": job.error_list}
    if job.status in ("completed", "failed"):
        data["details"] = {
            "created": job.created,
            "updated": job.updated,
            "skipped": job.skipped,
            "deleted": job.deleted,
            "failed": job.failed,
        }
    return {"data": data}


# --- SDK activity (kept in memory, shown on the project page) ---

_activity: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))


def record_activity(project_id: int, action: str, client: str, language: str = "",
                    status: int = 200, count: int | None = None) -> None:
    _activity[project_id].appendleft({
        "at": _utcnow(),
        "action": action,
        "language": language,
        "client": client,
        "status": status,
        "count": count,
    })


def recent_activity(project_id: int) -> list[dict]:
    return list(_activity[project_id])
