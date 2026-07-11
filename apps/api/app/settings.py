"""Compatibility export; new code imports app.core.settings."""

from app.core.settings import Settings, settings

__all__ = ["Settings", "settings"]
