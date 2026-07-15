FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements.txt ./apps/api/requirements.txt

FROM base AS development

COPY apps/api/requirements-dev.txt ./apps/api/requirements-dev.txt

RUN pip install --no-cache-dir -r apps/api/requirements-dev.txt

COPY apps/api ./apps/api

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api"]

FROM base AS production

RUN pip install --no-cache-dir -r apps/api/requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY --chown=app:app apps/api ./apps/api

USER app

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir apps/api"]
