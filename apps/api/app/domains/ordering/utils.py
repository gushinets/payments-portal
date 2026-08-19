from __future__ import annotations

import hashlib


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_required_document_acceptance_text(*, title: str) -> str:
    return f"Я принимаю документ «{title}»."
