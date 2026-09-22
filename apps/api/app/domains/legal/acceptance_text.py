"""Canonical legal acceptance statements and hashes."""

from __future__ import annotations

import hashlib

from app.domains.legal.errors import RegistrationLegalPackInvalidError
from app.models import AcceptanceKind, DocumentVersion


ACCEPTANCE_KIND_BY_DOC_TYPE = {
    "privacy": AcceptanceKind.PRIVACY_CONSENT,
    "pd_consent": AcceptanceKind.PRIVACY_CONSENT,
    "offer": AcceptanceKind.TERMS_ACCEPTANCE,
    "recurring_consent": AcceptanceKind.RECURRING_CONSENT,
    "cookies": AcceptanceKind.COOKIES,
}

REGISTRATION_PERSONAL_CONSENT_TEXT = (
    "Я даю согласие на обработку персональных данных в соответствии с "
    "Согласием на обработку персональных данных и Политикой в отношении "
    "обработки персональных данных."
)
REGISTRATION_OFFER_CONSENT_TEXT = (
    "Я принимаю условия Публичной оферты и ознакомлен(а) с Условиями отмены "
    "подписки и возврата денежных средств."
)
REGISTRATION_DOCUMENT_TYPES = ("privacy", "pd_consent", "offer")
REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE = {
    "privacy": REGISTRATION_PERSONAL_CONSENT_TEXT,
    "pd_consent": REGISTRATION_PERSONAL_CONSENT_TEXT,
    "offer": REGISTRATION_OFFER_CONSENT_TEXT,
}


def hash_acceptance_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_acceptance_text(document: DocumentVersion) -> str:
    return f"Я принимаю документ «{document.title}»."


def expected_acceptance_text_hash(document: DocumentVersion) -> str:
    return hash_acceptance_text(build_acceptance_text(document))


def expected_registration_acceptance_text_hash(document: DocumentVersion) -> str:
    acceptance_text = REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE.get(document.doc_type)
    if acceptance_text is None:
        raise RegistrationLegalPackInvalidError()
    return hash_acceptance_text(acceptance_text)


def valid_acceptance_text_hashes(document: DocumentVersion) -> frozenset[str]:
    hashes = {expected_acceptance_text_hash(document)}
    registration_text = REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE.get(document.doc_type)
    if registration_text is not None:
        hashes.add(hash_acceptance_text(registration_text))
    return frozenset(hashes)


def present_required_document(document: DocumentVersion) -> dict[str, str]:
    return {
        "document_version_id": str(document.id),
        "doc_type": document.doc_type,
        "version": document.version,
        "title": document.title,
        "url_path": document.url_path,
        "acceptance_text": build_acceptance_text(document),
        "acceptance_text_hash": expected_acceptance_text_hash(document),
    }
