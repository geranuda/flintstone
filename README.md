# Flintstone

**The smoothest, fastest translation management system you can self-host.**

Flintstone is a lightweight, single-process TMS that gets out of your way. No Docker compose files, no external databases, no JavaScript build steps. Install it with pip, run one command, and start translating.

```bash
pip install -e .
python -m flintstone
# → http://localhost:8000
```

That's it. Your translations live in a single SQLite file. Back it up by copying one file. Deploy it on a $5 VPS, a Raspberry Pi, or a free-tier cloud instance.

---

## Why Flintstone?

Every TMS out there makes you choose: pay for a hosted service, or spend a week setting up an open-source behemoth with PostgreSQL, Redis, Elasticsearch, and a Node.js frontend.

Flintstone rejects that tradeoff. It's built on three principles:

1. **Zero friction** — One install command, one run command, zero configuration. No `.env` files to fill out, no databases to provision, no build steps to run.

2. **Speed over ceremony** — Inline editing with instant save. Translation memory suggestions appear as you type. Find and replace across thousands of translations in milliseconds. TM fill-up auto-translates your missing keys in one click.

3. **Small footprint, full power** — ~30MB RAM, single SQLite file, single Python process. But it has everything a real TMS needs: multi-project management, TMX import/export, translation memory, tagging, bulk operations, and a complete REST API.

---

## Features

### Translation Editor
A grid-based editor where you translate directly in the browser. Click a cell, type, and it saves instantly — green flash confirms, no page reload. Keyboard shortcut `Ctrl+S` saves the focused cell.

### Translation Memory
Every translation you save is automatically stored in the translation memory. When you focus on an empty cell, Flintstone suggests translations from your TM — exact matches first, then substring matches. The TM is bidirectional: translate English→Spanish and you also get Spanish→English suggestions for free.

### TM Fill-up
Got a partially translated project? Hit the TM Fill-up button, pick your source and target languages, and Flintstone auto-fills every untranslated key that has an exact match in your translation memory. One click to leverage all your past work.

### Find & Replace
Global find and replace across all translations in a project. Preview matches with a before/after diff before applying. Filter by language to replace only in specific translations.

### Tagging
Organize translation keys with tags like `ui`, `emails`, `errors`. Filter the editor by tag. See a tag cloud on the project overview with counts. Tags travel with your keys through import/export.

### Import & Export
Move translations in and out with industry-standard formats:

| Format | Import | Export | Use Case |
|--------|--------|--------|----------|
| **JSON** | Per language | Per language | Developer integration, i18n libraries |
| **CSV** | All languages | All languages | Spreadsheet editing, bulk review |
| **TMX 1.4** | Project or TM | Project or TM | CAT tool interop, translation memory exchange |

Import a TMX file from OmegaT, Trados, or any CAT tool. Export your project as JSON files ready to drop into your React, Vue, or mobile app.

### REST API
Every feature is available through the API. The web UI is just a client. Build your own integrations, CI/CD pipelines, or custom workflows.

Full interactive API docs at `/api/docs` (Swagger UI) and `/redoc` (ReDoc).

### Multi-Project
Manage multiple translation projects from one dashboard. Each project has its own keys, translations, and completion stats. Translation memory is shared across projects — translate "Save" once, and every project benefits.

---

## Architecture

```
Python 3.10+ / FastAPI / SQLAlchemy / SQLite
Jinja2 templates / htmx / Pico CSS
No npm. No webpack. No Docker required.
```

| Component | Choice | Why |
|-----------|--------|-----|
| Web framework | FastAPI | Async, fast, auto-generates API docs |
| Database | SQLite (WAL mode) | Zero setup, single file, surprisingly fast |
| ORM | SQLAlchemy 2.0 | Industry standard, type-safe |
| Templates | Jinja2 + htmx | Server-rendered, no JS build step, instant interactions |
| CSS | Pico CSS | Classless, minimal, looks good by default |
| Server | uvicorn | Production-grade ASGI server |

Total runtime dependencies: 5 packages. Total frontend dependencies: 0 (CDN links for Pico CSS and htmx).

---

## Quick Start

### Install

```bash
git clone <repo-url> && cd flintstone
pip install -e ".[dev]"
```

### Run

```bash
python -m flintstone
```

Server starts at `http://localhost:8000`. The database file `flintstone.db` is created automatically.

### Configure (optional)

All settings via environment variables:

```bash
FLINTSTONE_DB="sqlite:///path/to/data.db"  # Database location
FLINTSTONE_HOST="0.0.0.0"                   # Bind address
FLINTSTONE_PORT="8000"                       # Port
FLINTSTONE_DEBUG="true"                      # Auto-reload on code changes
```

### Test

```bash
python -m pytest tests/ -v
```

50 tests covering all API endpoints, import/export round-trips, translation memory, find & replace, tagging, and TM fill-up.

---

## API Overview

### Projects
```
GET    /api/projects              List projects
POST   /api/projects              Create project
GET    /api/projects/{id}         Get project
PUT    /api/projects/{id}         Update project
DELETE /api/projects/{id}         Delete project
```

### Languages
```
GET    /api/languages             List languages
POST   /api/languages             Add language
DELETE /api/languages/{id}        Remove language
```

### Translation Keys
```
GET    /api/projects/{id}/keys         List keys (?q=search&tag=ui)
POST   /api/projects/{id}/keys         Create key (with tags)
PUT    /api/keys/{id}                  Update key
DELETE /api/keys/{id}                  Delete key
GET    /api/projects/{id}/tags         List all tags
```

### Translations
```
GET    /api/projects/{id}/translations          List all translations
PUT    /api/translations/{key_id}/{lang_id}     Set translation
POST   /api/projects/{id}/translations/bulk     Bulk update
GET    /api/projects/{id}/translations/search   Search keys and values
POST   /api/projects/{id}/translations/find-replace  Find & replace
```

### Import / Export
```
GET    /api/projects/{id}/export           Export (JSON or CSV)
POST   /api/projects/{id}/import           Import (JSON or CSV)
GET    /api/projects/{id}/export/tmx       Export as TMX
POST   /api/projects/{id}/import/tmx       Import TMX
```

### Translation Memory
```
GET    /api/memory/suggest                 Get TM suggestions
GET    /api/memory                         List TM entries
DELETE /api/memory                         Clear TM
POST   /api/memory/fillup/{project_id}     Auto-fill from TM
POST   /api/memory/import/tmx              Import TMX to TM
GET    /api/memory/export/tmx              Export TM as TMX
```

### Stats
```
GET    /api/projects/{id}/stats            Per-language completion stats
```

---

## Project Structure

```
flintstone/
├── __init__.py              # Version
├── __main__.py              # Entry point
├── app.py                   # FastAPI app with lifespan
├── config.py                # Settings from env vars
├── database.py              # SQLite + SQLAlchemy setup
├── models.py                # 5 ORM models
├── schemas.py               # Pydantic request/response schemas
├── api/
│   ├── projects.py          # Project CRUD
│   ├── languages.py         # Language CRUD
│   ├── translations.py      # Keys, translations, find & replace, tags
│   ├── export.py            # JSON/CSV import & export
│   ├── tmx.py               # TMX import & export
│   └── memory.py            # Translation memory + TM fill-up
├── ui/
│   └── views.py             # HTML page routes
├── templates/               # Jinja2 templates (6 pages + 3 partials)
└── static/
    └── app.js               # Keyboard shortcuts, flash messages
```

---

## Roadmap

Flintstone is built to be extended. Potential future additions:

- **Authentication** — API key or basic auth for team use
- **Revision history** — Track who changed what and when
- **Glossary** — Enforce consistent terminology across projects
- **Webhook notifications** — Notify when translations are updated
- **PO/XLIFF format support** — More CAT tool interoperability
- **Fuzzy TM matching** — Levenshtein distance for smarter suggestions
- **Machine translation integration** — Optional MT pre-translation via external APIs

---

## License

MIT

---

*Flintstone — because translation management shouldn't require a DevOps team.*
