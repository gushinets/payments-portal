FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/api-venv
ENV PATH="/opt/api-venv/bin:$PATH"

FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv-source

FROM base AS dependency-builder

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_PROJECT_ENVIRONMENT=/opt/api-venv
ENV UV_PYTHON_DOWNLOADS=never

COPY --from=uv-source /uv /uvx /bin/
COPY apps/api/pyproject.toml apps/api/uv.lock ./apps/api/

FROM dependency-builder AS production-dependencies

RUN uv sync --directory apps/api --locked --no-dev --no-install-project

FROM production-dependencies AS development-dependencies

RUN uv sync --directory apps/api --locked --dev --no-install-project

FROM base AS development

COPY --from=development-dependencies /opt/api-venv /opt/api-venv

COPY apps/api ./apps/api

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api"]

FROM base AS production

COPY --from=production-dependencies /opt/api-venv /opt/api-venv

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --app-dir apps/api"]
