#!/usr/bin/env bash
# Set up Flintstone on this computer and load an iOS app's strings into it, in one go:
#
#   curl -fsSL https://raw.githubusercontent.com/geranuda/flintstone/refs/heads/claude/sweet-davinci-xem524/scripts/quickstart.sh | bash
#
# Pass the Xcode project if it is not found automatically:
#
#   curl -fsSL …/quickstart.sh | bash -s -- ~/code/spoon/Spoon.xcodeproj
#
# What it does:
#   1. Downloads Flintstone into ~/flintstone (or FLINTSTONE_DIR), or updates it
#   2. Installs it in a virtual environment (needs Python 3.10 or newer)
#   3. Starts the server on http://localhost:8000 unless it is already running
#   4. Finds <APP_NAME>.xcodeproj (default: Spoon), creates the project in Flintstone
#      (English -> TARGETS, default es-MX) and pushes its strings and translations
#   5. Opens the project in your browser
#
# Environment: FLINTSTONE_DIR, FLINTSTONE_BRANCH, FLINTSTONE_PORT (default 8000), APP_NAME, TARGETS.
set -euo pipefail

REPO="https://github.com/geranuda/flintstone"
BRANCH="${FLINTSTONE_BRANCH:-claude/sweet-davinci-xem524}"
APP_NAME="${APP_NAME:-Spoon}"
TARGETS="${TARGETS:-es-MX}"
PORT="${FLINTSTONE_PORT:-8000}"
SERVER="http://localhost:$PORT"

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }
healthy() { curl -fsS "$SERVER/cds/health" >/dev/null 2>&1; }

command -v git >/dev/null 2>&1 || die "git is required (install Xcode's command line tools: xcode-select --install)"

# 1. Get the code (use the current folder when run from inside a Flintstone checkout)
if [ -n "${FLINTSTONE_DIR:-}" ]; then
    DIR="$FLINTSTONE_DIR"
elif [ -f pyproject.toml ] && grep -q '^name = "flintstone"' pyproject.toml; then
    DIR="$(pwd)"
else
    DIR="$HOME/flintstone"
fi
if [ -d "$DIR/.git" ]; then
    say "Updating Flintstone in $DIR"
    git -C "$DIR" fetch -q origin "$BRANCH"
    git -C "$DIR" checkout -q "$BRANCH"
    git -C "$DIR" pull -q --ff-only origin "$BRANCH"
else
    say "Downloading Flintstone into $DIR"
    git clone -q --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

# 2. Install into .venv with Python 3.10+ (macOS's built-in python3 is 3.9)
new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && new_enough "$candidate"; then
        PYTHON="$candidate"
        break
    fi
done
[ -n "$PYTHON" ] || die "Flintstone needs Python 3.10 or newer. Install it with 'brew install python@3.12'
(or from https://www.python.org/downloads/), then run this command again."
if ! { [ -x .venv/bin/python ] && new_enough .venv/bin/python; }; then
    rm -rf .venv
    "$PYTHON" -m venv .venv
fi
say "Installing Flintstone ($(.venv/bin/python --version))"
.venv/bin/python -m pip install -q --disable-pip-version-check -e .
export PATH="$DIR/.venv/bin:$PATH"

# 3. Start the server
STARTED=""
if healthy; then
    say "Flintstone is already running at $SERVER"
else
    say "Starting Flintstone at $SERVER"
    FLINTSTONE_PORT="$PORT" nohup .venv/bin/flintstone > "$DIR/flintstone.log" 2>&1 &
    echo $! > "$DIR/.flintstone.pid"
    STARTED=1
    for _ in $(seq 1 60); do healthy && break; sleep 0.5; done
    healthy || die "The server did not start; see $DIR/flintstone.log"
fi

project_id() {
    curl -fsS "$SERVER/api/projects" | .venv/bin/python -c '
import json, sys
print(next((str(p["id"]) for p in json.load(sys.stdin) if p["name"] == sys.argv[1]), ""))' "$APP_NAME"
}

# 4. Create the project and push the app
EXISTING="$(project_id)"
if [ -n "$EXISTING" ]; then
    say "Flintstone already has a \"$APP_NAME\" project; not pushing again"
    echo "    To push changes later: flintstone push --project <path to $APP_NAME.xcodeproj> --token … --secret …"
    echo "    (the project page shows the token and can generate a new secret)"
else
    APP="${1:-}"
    if [ -z "$APP" ]; then
        say "Looking for $APP_NAME.xcodeproj"
        if command -v mdfind >/dev/null 2>&1; then
            APP="$(mdfind "kMDItemFSName == '$APP_NAME.xcodeproj'" 2>/dev/null \
                | grep -v -e '/\.Trash/' -e '/Library/' | head -n 1 || true)"
        fi
        if [ -z "$APP" ]; then
            APP="$(find "$HOME" -maxdepth 6 \
                \( -name Library -o -name .Trash -o -name node_modules -o -name .git -o -name DerivedData \) -prune \
                -o -type d -name "$APP_NAME.xcodeproj" -print 2>/dev/null | head -n 1 || true)"
        fi
    fi
    { [ -n "$APP" ] && [ -e "$APP" ]; } || die "Could not find $APP_NAME.xcodeproj. Run again with its path:
  curl -fsSL https://raw.githubusercontent.com/geranuda/flintstone/refs/heads/$BRANCH/scripts/quickstart.sh | bash -s -- /path/to/$APP_NAME.xcodeproj"
    say "Pushing $APP"
    FLINTSTONE_URL="$SERVER" scripts/demo_push.sh "$APP" "$APP_NAME" "$TARGETS"
fi

# 5. Show it
URL="$SERVER/projects/$(project_id)"
say "Opening $URL"
case "$(uname -s)" in
    Darwin) open "$URL" ;;
    *) command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" >/dev/null 2>&1 || true ;;
esac

echo
echo "Flintstone: $SERVER   (data in $DIR/flintstone.db)"
if [ -n "$STARTED" ]; then
    echo "Stop it:    kill \$(cat \"$DIR/.flintstone.pid\")"
fi
echo "Start it:   cd \"$DIR\" && .venv/bin/flintstone"
