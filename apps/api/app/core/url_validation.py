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


def validate_https_origin_url(
    value: str,
    setting_name: str,
    *,
    allowed_hostname: str | None = None,
) -> str:
    parsed = parse_absolute_url(value)
    if parsed.scheme != "https":
        raise ValueError(f"{setting_name} must use https")
    if parsed.username or parsed.password:
        raise ValueError(f"{setting_name} must not include credentials")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{setting_name} must be an origin URL")
    if parsed.path not in ("", "/"):
        raise ValueError(f"{setting_name} must be an origin URL")
    if parsed.port is not None and parsed.port != 443:
        raise ValueError(f"{setting_name} must use the default https port")
    if allowed_hostname is not None and (parsed.hostname or "").casefold() != allowed_hostname.casefold():
        raise ValueError(f"{setting_name} must use {allowed_hostname}")
    return value
