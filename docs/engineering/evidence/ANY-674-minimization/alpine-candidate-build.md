# Archived Alpine candidate build recipe

This is the exact recipe used for the rejected, non-shipping comparison image.
It is historical execution evidence, not a supported build entrypoint.
The omitted `--no-build` flags reflect the command actually executed; adding
flags retrospectively would misrepresent the tested recipe. Production build
policy is governed by `apps/api/Dockerfile`, unchanged by this representation.

Original filename: `Dockerfile.alpine.txt`.
Original LF UTF-8 content SHA-256: `fd3ddc37de6cfcaec82bb864e0875e77bedf4a78a13ca3afd4d8623ae29d4726`.

```dockerfile
FROM python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89 AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/api-venv
ENV PATH="/opt/api-venv/bin:$PATH"

RUN apk upgrade --no-cache && apk add --no-cache libstdc++ tzdata

# The pinned Debian base supplies system tzdata for both runtime targets.
RUN python -c 'from zoneinfo import ZoneInfo; ZoneInfo("Europe/Moscow")'

WORKDIR /app

FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv-source

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
COPY config/development ./config/development

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log --app-dir apps/api"]

FROM base AS production

COPY --from=production-dependencies /opt/api-venv /opt/api-venv

# Non-shipping musl comparison; adoption requires an explicit architecture decision.
RUN addgroup -S -g 1000 app \
    && adduser -S -D -H -u 999 -G app app \
    && mkdir -p /run/payments-portal \
    && chown app:app /run/payments-portal \
    && chmod 0700 /run/payments-portal

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --no-access-log --app-dir apps/api"]
```
