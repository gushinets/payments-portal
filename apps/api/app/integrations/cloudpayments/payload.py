from __future__ import annotations

import re
from typing import Any


def get_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not re.fullmatch(r"[+-]?\d+", normalized):
        return None
    try:
        return int(normalized)
    except (OverflowError, TypeError, ValueError):
        return None


def normalized_recurrent_status(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return {
        "active": "active",
        "pastdue": "past_due",
        "past_due": "past_due",
        "cancelled": "canceled",
        "canceled": "canceled",
        "rejected": "rejected",
        "expired": "expired",
    }.get(normalized, "unknown")
