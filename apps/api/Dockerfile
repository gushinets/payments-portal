FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV VIRTUAL_ENV=/opt/api-venv
ENV PATH="/opt/api-venv/bin:$PATH"

WORKDIR /app

FROM base AS dependency-builder

ARG POETRY_VERSION=1.8.4

ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_CREATE=false

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && python -m venv "$VIRTUAL_ENV"

COPY apps/api/pyproject.toml apps/api/poetry.lock ./apps/api/

FROM dependency-builder AS production-dependencies

RUN poetry --directory apps/api install --only main --no-root

FROM production-dependencies AS development-dependencies

RUN poetry --directory apps/api install --with dev --no-root

FROM base AS development

COPY --from=development-dependencies /opt/api-venv /opt/api-venv

COPY apps/api ./apps/api

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api"]

FROM base AS production

COPY --from=production-dependencies /opt/api-venv /opt/api-venv

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY apps/api/alembic.ini ./apps/api/alembic.ini
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/app ./apps/api/app

USER app

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --app-dir apps/api"]
