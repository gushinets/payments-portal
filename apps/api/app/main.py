from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.cloudpayments import router as cloudpayments_router
from app.database import SessionLocal
from app.legal import router as legal_router
from app.legal_seed import seed_legal_documents
from app.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SKIP_LEGAL_SEED") != "true":
        with SessionLocal() as db:
            seed_legal_documents(db)

    yield


app = FastAPI(title="AnytoolAI Payments API", version="0.1.0", lifespan=lifespan)

default_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

for origin in settings.cors_allow_origins:
    if origin not in default_cors_origins:
        default_cors_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=default_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(legal_router)
app.include_router(cloudpayments_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "cloudpayments_enabled": settings.cloudpayments_enabled,
        "cloudpayments_public_id_configured": bool(settings.cloudpayments_public_id),
    }
