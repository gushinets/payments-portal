from __future__ import annotations

from app.core.errors import AppError


class InvalidAuthSessionError(AppError):
    pass


class MissingPersonalConsentError(AppError):
    pass


class MissingOfferConsentError(AppError):
    pass


class EmailAlreadyRegisteredError(AppError):
    pass


class InvalidCredentialsError(AppError):
    pass


class PasswordResetError(AppError):
    pass


class PasswordResetRateLimitedError(PasswordResetError):
    pass


class InvalidOrExpiredResetTokenError(PasswordResetError):
    pass
