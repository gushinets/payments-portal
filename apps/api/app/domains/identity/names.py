"""Optional, unverified personal-name input. No display-name synthesis."""

import unicodedata

from app.core.errors import AppError


class InvalidPersonalNameError(AppError):
    pass


def normalize_optional_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or any(unicodedata.category(char).startswith("C") for char in value):
        raise InvalidPersonalNameError()
    normalized = value.strip()
    if len(normalized) > 256:
        raise InvalidPersonalNameError()
    return normalized or None
