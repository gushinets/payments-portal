from __future__ import annotations

import hashlib
import time

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    product: str | None = None
    region: str = "ru"


class VerifyRequest(BaseModel):
    email: EmailStr
    token: str


def make_demo_token(email: str) -> str:
    raw = f"{email.lower()}:{int(time.time() // 3600)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@router.post("/request-login")
def request_login(payload: LoginRequest):
    token = make_demo_token(payload.email)
    return {
        "status": "demo_link_generated",
        "mode": "demo",
        "email": payload.email,
        "product": payload.product,
        "region": payload.region,
        "demo_token": token,
        "demo_link": f"/api/auth/verify?token={token}",
    }


@router.post("/verify")
def verify(payload: VerifyRequest):
    return {
        "status": "verified",
        "mode": "demo",
        "email": payload.email,
        "email_verified": True,
    }
