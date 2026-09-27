#!/usr/bin/env bash
# Create a Flintstone project for an app and push its strings (and existing translations) into it.
#
#   scripts/demo_push.sh ~/code/spoon/Spoon.xcodeproj Spoon es-MX
#
# Needs a running server (run `flintstone` in another terminal) and the flintstone CLI on PATH.
# Environment: FLINTSTONE_URL (default http://localhost:8000), FLINTSTONE_SOURCE_LANGUAGE (default en).
set -euo pipefail

APP="${1:?usage: scripts/demo_push.sh <app folder or .xcodeproj> [project name] [target languages, comma-separated]}"
NAME="${2:-$(basename "${APP%/}" .xcodeproj)}"
TARGETS="${3:-es-MX}"
SERVER="${FLINTSTONE_URL:-http://localhost:8000}"
SOURCE="${FLINTSTONE_SOURCE_LANGUAGE:-en}"

if ! curl -fsS "$SERVER/cds/health" >/dev/null 2>&1; then
    echo "Flintstone is not running at $SERVER. Start it with: flintstone" >&2
    exit 1
fi

payload=$(python3 -c 'import json, sys
name, source, targets = sys.argv[1:4]
print(json.dumps({"name": name, "source_language": source,
                  "target_languages": [t.strip() for t in targets.split(",") if t.strip()]}))' "$NAME" "$SOURCE" "$TARGETS")
response=$(curl -sS -X POST "$SERVER/api/projects" -H 'Content-Type: application/json' -d "$payload")
if ! fields=$(python3 -c 'import json, sys; p = json.load(sys.stdin); print(p["id"], p["token"], p["secret"])' <<<"$response" 2>/dev/null); then
    echo "Could not create project \"$NAME\": $response" >&2
    exit 1
fi
read -r id token secret <<<"$fields"

flintstone push --project "$APP" --with-translations --token "$token" --secret "$secret" --cds-host "$SERVER/cds"

cat <<EOF

Project "$NAME" is ready: $SERVER/projects/$id
  CDS host: $SERVER/cds
  Token:    $token
  Secret:   $secret   (shown once; keep it for future pushes)
EOF
