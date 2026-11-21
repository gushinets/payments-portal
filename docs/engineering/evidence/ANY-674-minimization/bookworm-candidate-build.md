# Archived Bookworm candidate build recipe

This is the exact recipe used for the rejected, non-shipping comparison image.
It is historical execution evidence, not a supported build entrypoint.
The omitted `--no-build` flags reflect the command actually executed; adding
flags retrospectively would misrepresent the tested recipe. Production build
policy is governed by `apps/api/Dockerfile`, unchanged by this representation.

Original filename: `Dockerfile.bookworm.txt`.
Original LF UTF-8 content SHA-256: `6de67d3825e5fecb5868b44ae70704f6624fa6df91fbeb923f44f01f6deed230`.

```dockerfile
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/api-venv
ENV PATH="/opt/api-venv/bin:$PATH"

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

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

# Create the runtime identity before removing build/account/mount tooling.
# Keep essential/protected packages, dpkg metadata and native runtime libraries.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app \
    && install -d -o app -g app -m 0700 /run/payments-portal \
    && runtime_build_packages="apt libapt-pkg6.0 gpgv debian-archive-keyring adduser passwd mount" \
    && for package in $runtime_build_packages; do \
         test "$(dpkg-query -W -f='${Essential}:${Protected}' "$package")" = "no:no"; \
       done \
    && dpkg --purge $runtime_build_packages \
    && test -z "$(dpkg --audit)"

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --no-access-log --app-dir apps/api"]
```
