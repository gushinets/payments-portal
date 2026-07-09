from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.cloudpayments import router as cloudpayments_router
from app.legal import router as legal_router
from app.settings import settings

app = FastAPI(title="AnytoolAI Payments API", version="0.1.0")

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
