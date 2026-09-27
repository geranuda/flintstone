"""``flintstone`` command line: run the server, push/pull content like Transifex's CLIs.

    flintstone                      # run the server (same as `flintstone serve`)
    flintstone push --project MyApp.xcodeproj
    flintstone pull --translated-locales en es-MX --output MyApp/
    flintstone invalidate

Credentials come from --token/--secret or the FLINTSTONE_TOKEN/FLINTSTONE_SECRET
environment variables (TRANSIFEX_TOKEN/TRANSIFEX_SECRET also work, so existing
Transifex Native scripts can switch by changing the CDS host only).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, catalogs, locales
from .client import DEFAULT_CDS_HOST, CDSClient, CDSClientError

STRINGS_FILENAME = "txstrings.json"  # the bundled cache file the Transifex iOS SDK looks for


def _env(*names: str) -> str | None:
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return None


def _print(message: str = "", *, err: bool = False) -> None:
    print(message, file=sys.stderr if err else sys.stdout, flush=True)


def _fail(message: str) -> int:
    _print(f"error: {message}", err=True)
    return 1


def _client(args, need_secret: bool) -> CDSClient:
    token = args.token or _env("FLINTSTONE_TOKEN", "TRANSIFEX_TOKEN")
    secret = args.secret or _env("FLINTSTONE_SECRET", "TRANSIFEX_SECRET")
    host = args.cds_host or _env("FLINTSTONE_CDS_HOST", "TRANSIFEX_CDS_HOST") or DEFAULT_CDS_HOST
    if not token:
        raise SystemExit(_fail("missing token (use --token or FLINTSTONE_TOKEN)"))
    if need_secret and not secret:
        raise SystemExit(_fail("missing secret (use --secret or FLINTSTONE_SECRET)"))
    if args.verbose:
        _print(f"Using CDS host {host}")
    return CDSClient(host, token, secret)


def _summary(details: dict) -> str:
    return ", ".join(f"{details.get(k, 0)} {k}" for k in ("created", "updated", "skipped", "deleted", "failed"))


def _report_job(client: CDSClient, link: str, label: str, verbose: bool) -> bool:
    result = client.wait(link)
    errors = result.get("errors") or []
    for error in errors[: (None if verbose else 10)]:
        where = (error.get("source") or {}).get("key", "")
        _print(f"  ! {where}: {error.get('detail') or error.get('title')}", err=True)
    if len(errors) > 10 and not verbose:
        _print(f"  ! ... and {len(errors) - 10} more (use --verbose)", err=True)
    if result.get("status") != "completed":
        _print(f"✗ {label} failed ({result.get('status')})", err=True)
        return False
    _print(f"✓ {label}: {_summary(result.get('details') or {})}")
    return True


def _collect(args) -> tuple[dict, list[catalogs.Catalog]]:
    """Discover, parse and merge the localization files of all --project paths."""
    loaded: list[catalogs.Catalog] = []
    for project in args.project:
        root, files = catalogs.discover(project, include_unsupported=args.include_unsupported,
                                        excluded=args.excluded_files)
        found = catalogs.load(files, root, args.source_locale)
        if Path(project).is_dir() or Path(project).suffix in (".xcodeproj", ".xcworkspace"):
            # The biggest catalog (usually the main app target) wins key conflicts.
            found.sort(key=lambda c: -len(c.strings))
        loaded.extend(found)
    merged, warnings = catalogs.consolidate(loaded)
    return {"strings": merged, "warnings": warnings}, loaded


def cmd_push(args) -> int:
    try:
        collected, loaded = _collect(args)
    except catalogs.CatalogError as exc:
        return _fail(str(exc))
    strings = collected["strings"]
    if not strings:
        return _fail("no localizable strings found (looked for .xcstrings, .strings, .stringsdict files)")

    _print(f"Found {len(strings)} source strings in {len(loaded)} file(s):")
    for catalog in loaded:
        _print(f"  {catalog.rel}  ({len(catalog.strings)} strings)")
    warnings = collected["warnings"]
    if warnings:
        conflicting = len({key for key, _ in warnings})
        _print(f"Warning: {conflicting} key(s) have different source text in different files; "
               f"the first file listed wins.", err=True)
        for _, warning in warnings[: (None if args.verbose else 5)]:
            _print(f"  {warning}", err=True)
        if len(warnings) > 5 and not args.verbose:
            _print("  ... (use --verbose to list all)", err=True)

    data = {key: s.payload(args.append_tags) for key, s in strings.items()}
    meta = {
        "purge": args.purge,
        "override_tags": args.override_tags,
        "override_occurrences": args.override_occurrences,
        "keep_translations": not args.delete_translations,
        "dry_run": args.dry_run,
    }
    client = _client(args, need_secret=True)
    _print(f"Pushing {len(data)} source strings to {client.host} "
           f"(purge: {'yes' if args.purge else 'no'}{', dry run' if args.dry_run else ''})...")
    try:
        ok = _report_job(client, client.push_source(data, meta), "Source strings pushed", args.verbose)
        if not ok:
            return 1
        if args.with_translations:
            ok = _push_translations(args, client, strings) and ok
    except CDSClientError as exc:
        return _fail(str(exc))
    return 0 if ok else 1


def _push_translations(args, client: CDSClient, strings: dict) -> bool:
    by_lang: dict[str, dict] = {}
    for key, s in strings.items():
        for lang, value in s.translations.items():
            by_lang.setdefault(lang, {})[key] = {"string": value}
    if not by_lang:
        _print("No existing translations found to upload.")
        return True
    enabled = {entry.get("code") for entry in client.languages().get("data", [])}
    meta = {"override_translations": args.override_translations, "dry_run": args.dry_run}
    ok = True
    for lang, data in sorted(by_lang.items()):
        if not any(locales.same_code(lang, code) for code in enabled if code):
            _print(f"Skipping {len(data)} '{lang}' translations: language is not enabled in the project.", err=True)
            continue
        _print(f"Uploading {len(data)} existing '{lang}' translations...")
        ok = _report_job(client, client.push_translations(lang, data, meta), f"{lang} translations", args.verbose) and ok
    return ok


def cmd_pull(args) -> int:
    client = _client(args, need_secret=False)
    try:
        locales_to_fetch = args.translated_locales or [
            entry["code"] for entry in client.languages().get("data", []) if entry.get("code")
        ]
        translations: dict[str, dict[str, dict]] = {}
        failed = []
        for code in locales_to_fetch:
            try:
                translations[code] = client.content(code, tags=args.with_tags_only, status=args.with_status_only)
                filled = sum(1 for v in translations[code].values() if v.get("string"))
                _print(f"✓ {code}: {filled} translated strings")
            except CDSClientError as exc:
                if exc.status == 404 and args.ignore_missing_locales:
                    _print(f"Skipping {code}: {exc.message}", err=True)
                    continue
                failed.append(code)
                _print(f"✗ {code}: {exc}", err=True)
    except CDSClientError as exc:
        return _fail(str(exc))
    if failed:
        return 1

    if args.update_catalogs:
        flat = {lang: {k: v.get("string", "") for k, v in data.items()} for lang, data in translations.items()}
        for project in args.project:
            try:
                _, files = catalogs.discover(project, include_unsupported=True)
            except catalogs.CatalogError as exc:
                return _fail(str(exc))
            for path in files:
                if path.suffix != ".xcstrings":
                    continue
                changed = catalogs.update_xcstrings(path, flat)
                summary = ", ".join(f"{lang}: {n}" for lang, n in sorted(changed.items())) or "no changes"
                _print(f"  {path}: {summary}")

    if args.output or not args.update_catalogs:
        folder = Path(args.output or ".")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / STRINGS_FILENAME
        target.write_text(json.dumps(translations, ensure_ascii=False, indent=2), encoding="utf-8")
        _print(f"✓ Wrote {target} — add it to your app's 'Copy Bundle Resources' so the SDK "
               f"has translations offline on first launch.")
    return 0


def cmd_invalidate(args) -> int:
    client = _client(args, need_secret=True)
    try:
        result = client.invalidate(purge=args.purge)
    except CDSClientError as exc:
        return _fail(str(exc))
    _print(f"✓ CDS cache {'purged' if args.purge else 'invalidated'} ({result.get('count', 0)} languages)")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .config import settings

    uvicorn.run(
        "flintstone.app:app",
        host=getattr(args, "host", None) or settings.host,
        port=getattr(args, "port", None) or settings.port,
        reload=getattr(args, "reload", False) or settings.debug,
    )
    return 0


def _add_credentials(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="project token (env: FLINTSTONE_TOKEN or TRANSIFEX_TOKEN)")
    parser.add_argument("--secret", help="project secret (env: FLINTSTONE_SECRET or TRANSIFEX_SECRET)")
    parser.add_argument("--cds-host", help=f"CDS URL, default {DEFAULT_CDS_HOST} "
                                           "(env: FLINTSTONE_CDS_HOST or TRANSIFEX_CDS_HOST)")
    parser.add_argument("--verbose", action="store_true", help="extra output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flintstone",
        description="Flintstone TMS: run the server, or push/pull content through its "
                    "Transifex Native compatible CDS.",
    )
    parser.add_argument("--version", action="version", version=f"flintstone {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the web server (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    push = sub.add_parser(
        "push", help="push source strings (like `txios-cli push`)",
        description="Collect source strings from String Catalogs (.xcstrings), .strings/.stringsdict, "
                    "XLIFF or JSON files and push them to the CDS.",
    )
    _add_credentials(push)
    push.add_argument("--project", nargs="+", default=["."], metavar="PATH",
                      help="Xcode project, folder or localization file(s); default: current folder")
    push.add_argument("--source-locale", default="en", help="source locale (default: en)")
    push.add_argument("--append-tags", nargs="+", default=[], metavar="TAG", help="tags added to every string")
    push.add_argument("--excluded-files", nargs="+", default=[], metavar="FILE", help="file names to skip")
    push.add_argument("--include-unsupported", action="store_true",
                      help="also push InfoPlist/Root.strings content, which SDKs cannot serve over the air")
    push.add_argument("--purge", action="store_true", help="delete strings that are not in this push")
    push.add_argument("--override-tags", action="store_true", help="replace tags instead of appending")
    push.add_argument("--override-occurrences", action="store_true", help="replace occurrences instead of appending")
    push.add_argument("--delete-translations", action="store_true",
                      help="delete translations of strings whose source text changed")
    push.add_argument("--dry-run", action="store_true", help="report what would change without changing it")
    push.add_argument("--with-translations", action="store_true",
                      help="also upload translations already in the files (to migrate a localized app)")
    push.add_argument("--override-translations", action="store_true",
                      help="with --with-translations: replace translations that differ in Flintstone")
    push.set_defaults(func=cmd_push)

    pull = sub.add_parser(
        "pull", help="download translations (like `txios-cli pull`)",
        description="Download translations to txstrings.json (the Transifex iOS SDK bundle cache) "
                    "and/or write them back into String Catalogs.",
    )
    _add_credentials(pull)
    pull.add_argument("--translated-locales", nargs="+", metavar="LOCALE",
                      help="locales to download; default: every language of the project")
    pull.add_argument("--output", help=f"folder for {STRINGS_FILENAME} (default: current folder)")
    pull.add_argument("--with-tags-only", nargs="+", metavar="TAG", help="only strings with all these tags")
    pull.add_argument("--with-status-only", choices=["translated", "reviewed", "proofread", "finalized"],
                      help="only strings with at least this status")
    pull.add_argument("--ignore-missing-locales", action="store_true", help="skip locales the project lacks")
    pull.add_argument("--update-catalogs", action="store_true",
                      help="write translations into the .xcstrings files found under --project")
    pull.add_argument("--project", nargs="+", default=["."], metavar="PATH",
                      help="where to look for .xcstrings files with --update-catalogs")
    pull.set_defaults(func=cmd_pull)

    invalidate = sub.add_parser("invalidate", help="force CDS cache invalidation")
    _add_credentials(invalidate)
    invalidate.add_argument("--purge", action="store_true", help="purge instead of invalidate")
    invalidate.set_defaults(func=cmd_invalidate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_serve(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
