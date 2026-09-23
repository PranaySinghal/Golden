# One image: the built frontend, served by the FastAPI app beside the API.
#   docker build -t tidylab . && docker run -p 8000:8000 tidylab

# --- 1. Build the frontend -------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. The server ---------------------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    LLM_PROVIDER=none \
    PORT=8000

WORKDIR /app/backend
# Dependencies first, so a code change doesn't reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY --from=frontend /src/frontend/dist /app/static

# Datasets live in temporary folders for the life of the process; nothing needs root.
RUN useradd --create-home --uid 1000 tidylab
USER tidylab

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"

# Hosts like Render pass PORT; locally it's 8000.
CMD ["sh", "-c", "exec /app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
