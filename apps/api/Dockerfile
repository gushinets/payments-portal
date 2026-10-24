FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/api-venv
ENV PATH="/opt/api-venv/bin:$PATH"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv-source

FROM base AS dependency-builder

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

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log --app-dir apps/api"]

FROM base AS production

COPY --from=production-dependencies /opt/api-venv /opt/api-venv

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --no-access-log --app-dir apps/api"]
