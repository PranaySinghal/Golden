#!/usr/bin/env bash
# Run Tidy Lab without Docker: build the page once, then serve it and the API on one port.
#   ./run.sh            → http://localhost:8000
#   PORT=9000 ./run.sh  → another port
set -euo pipefail
cd "$(dirname "$0")"

missing=()
command -v uv >/dev/null 2>&1 || missing+=("uv (https://docs.astral.sh/uv/getting-started/installation/)")
command -v npm >/dev/null 2>&1 || missing+=("Node.js 22+ with npm (https://nodejs.org)")
if ((${#missing[@]})); then
  echo "Tidy Lab needs these installed first:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  echo "Or, with Docker: docker build -t tidylab . && docker run -p 8000:8000 tidylab" >&2
  exit 1
fi

# Optional settings (see .env.example). Nothing in it is required.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

echo "==> Installing the server's dependencies"
(cd backend && uv sync --frozen --no-dev --quiet)

echo "==> Building the page"
(cd frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)

port="${PORT:-8000}"
echo "==> Tidy Lab is starting on http://localhost:${port}  (Ctrl+C to stop)"
cd backend
STATIC_DIR="$(cd ../frontend/dist && pwd)" exec uv run --no-dev uvicorn app.main:app --port "$port"
