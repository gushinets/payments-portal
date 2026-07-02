FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY apps/api/requirements.txt ./apps/api/requirements.txt
COPY apps/api/requirements-dev.txt ./apps/api/requirements-dev.txt

RUN pip install --no-cache-dir -r apps/api/requirements-dev.txt

COPY apps/api ./apps/api

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic -c apps/api/alembic.ini upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir apps/api"]
