from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse


def parse_absolute_url(value: str):
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("must be an absolute URL")
    return parsed


def is_loopback_hostname(hostname: str) -> bool:
    normalized_hostname = hostname.strip().lower()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized_hostname).is_loopback
    except ValueError:
        return False


def validate_production_public_url(value: str, setting_name: str) -> str:
    parsed = parse_absolute_url(value)
    if parsed.scheme != "https":
        raise ValueError(f"{setting_name} must use https in production")
    if is_loopback_hostname(parsed.hostname or ""):
        raise ValueError(f"{setting_name} must not use a loopback host in production")
    return value


def validate_production_cors_origin(value: str) -> str:
    if value == "*":
        raise ValueError("CORS_ALLOW_ORIGINS contains a forbidden production origin")

    parsed = parse_absolute_url(value)
    if parsed.scheme != "https":
        raise ValueError("CORS_ALLOW_ORIGINS must use https origins in production")
    if is_loopback_hostname(parsed.hostname or ""):
        raise ValueError("CORS_ALLOW_ORIGINS contains a forbidden production origin")
    return value
