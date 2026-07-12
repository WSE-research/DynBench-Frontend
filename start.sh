#!/usr/bin/env bash
# start.sh — start the DynBench Frontend locally.
#
# Creates/updates a virtual environment in .venv, verifies the required
# configuration (MODEL, DYNBENCH — from the environment or a .env file, see
# README.adoc section "Configuration") and launches the app through run.py so
# that the REST API (/api/transform, /api/transform-benchmark) and the /health
# endpoint are registered alongside the Streamlit UI.
#
# Usage:
#   ./start.sh              # start on http://localhost:8501
#   PORT=8600 ./start.sh    # start on a custom port
#   ./start.sh --dev        # additionally install dev tooling (pytest, ruff)
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN=${PYTHON:-python3}
VENV=${VENV:-.venv}
PORT=${PORT:-8501}

# --- virtual environment -----------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
    echo "Creating virtual environment in $VENV ..."
    "$PYTHON_BIN" -m venv "$VENV"
fi

# (re)install dependencies only when the requirements files changed
REQ_FILES=(requirements.txt)
if [ "${1:-}" = "--dev" ]; then
    REQ_FILES+=(requirements-dev.txt)
fi
STAMP="$VENV/.requirements.sha256"
CHECKSUM=$(cat "${REQ_FILES[@]}" | sha256sum | cut -d' ' -f1)
if [ "$(cat "$STAMP" 2>/dev/null)" != "$CHECKSUM" ]; then
    echo "Installing dependencies (${REQ_FILES[*]}) ..."
    for req in "${REQ_FILES[@]}"; do
        "$VENV/bin/pip" install --quiet -r "$req"
    done
    echo "$CHECKSUM" > "$STAMP"
fi

# --- configuration -----------------------------------------------------------
# MODEL and DYNBENCH may be provided as environment variables or in a .env
# file in the project root (read automatically by python-decouple).
MISSING=0
require() {
    local name=$1 example=$2
    if [ -z "${!name:-}" ] && ! grep -qE "^${name}=" .env 2>/dev/null; then
        echo "ERROR: ${name} is not configured." >&2
        echo "  Set it as an environment variable or add it to .env, e.g.:" >&2
        echo "    echo '${name}=${example}' >> .env" >&2
        MISSING=1
    fi
}
require DYNBENCH "http://your-backend-host:port/transform"
require MODEL "gpt-4o"
if [ "$MISSING" = 1 ]; then
    echo >&2
    echo "See README.adoc (section 'Configuration') for details." >&2
    exit 1
fi

# --- launch ------------------------------------------------------------------
# PORT is read by run.py (flag options take precedence over Streamlit's
# env-based config, so run.py passes the port explicitly)
export PORT
export STREAMLIT_SERVER_HEADLESS=${STREAMLIT_SERVER_HEADLESS:-true}
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

echo "Starting DynBench Frontend on http://localhost:${PORT} (REST API: /api/transform)"
exec "$VENV/bin/python" run.py
