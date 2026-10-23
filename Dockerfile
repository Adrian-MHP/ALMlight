# syntax=docker/dockerfile:1
# One image: the API (FastAPI) serves the built single-page frontend.

# --- frontend build ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- python base ------------------------------------------------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install -r requirements.txt
RUN useradd --create-home --uid 10001 almlight && mkdir -p /data && chown almlight /data

# --- test image (backend tests, lint) ----------------------------------------------------------
FROM base AS test
COPY backend/requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY backend/ ./
USER almlight
CMD ["pytest", "-q"]

# --- runtime ------------------------------------------------------------------------------------
FROM base AS runtime
COPY backend/ ./
COPY --from=frontend /web/dist /app/static
USER almlight
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)" || exit 1
ENTRYPOINT ["./entrypoint.sh"]
