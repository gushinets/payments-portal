from __future__ import annotations

from app.core.errors import AppError


class CheckoutError(AppError):
    pass


class PasswordResetError(AppError):
    pass
