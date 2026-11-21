FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS base

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

RUN uv sync --directory apps/api --locked --no-dev --no-install-project --no-build

FROM production-dependencies AS development-dependencies

RUN uv sync --directory apps/api --locked --dev --no-install-project --no-build

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
# API runtime has no OS account-switching/PAM-login contract; retain commands
# but track removal of unnecessary setid privileges through dpkg overrides.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app \
    && install -d -o app -g app -m 0700 /run/payments-portal \
    && runtime_build_packages="apt libapt-pkg7.0 sqv debian-archive-keyring adduser passwd mount libbsd0 libhogweed6t64 libnettle8t64 liblz4-1 libxxhash0 libseccomp2 libsemanage2 libsemanage-common libsepol2" \
    && for package in $runtime_build_packages; do \
         test "$(dpkg-query -W -f='${Essential}:${Protected}' "$package")" = "no:no" || { \
           echo "Refusing removal of essential/protected or unknown package: $package" >&2; exit 1; \
         }; \
       done \
    && dpkg --purge $runtime_build_packages \
    && package_audit=$(dpkg --audit) \
    && test -z "$package_audit"

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "PYTHONPATH=apps/api python -c 'from app.core.settings import settings' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --no-access-log --app-dir apps/api"]
