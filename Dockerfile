# ---------- Stage 1: Build frontend ----------
FROM node:20-alpine AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Runtime ----------
FROM python:3.12-slim AS runtime

# Install uv for fast Python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev

# Copy backend source
COPY backend/ ./

# Copy built frontend assets into backend/static so FastAPI can serve them.
# The app should mount this directory as a StaticFiles route (e.g. at "/")
# to serve the SPA without a separate web server.
COPY --from=frontend /src/frontend/dist ./static

# Persistent data volume mount point
RUN mkdir -p /app/data

EXPOSE 5001

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5001"]
