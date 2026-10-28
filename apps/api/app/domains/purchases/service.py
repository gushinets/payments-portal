"""Synchronous transaction owner for purchase acceptance and historical evidence.

Every public function owns and closes its complete DB unit. Integration I/O is
composed outside these units. A financial claim is permanent even if its commit
acknowledgement or the caller disappears. Only original fenced point proof binds.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customers import authenticate, lock_user, reserve_customer_in_transaction
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer
from app.domains.catalog.publication import SessionFactory
from app.domains.legal.acceptance_text import (
    ACCEPTANCE_KIND_BY_DOC_TYPE,
    REGISTRATION_DOCUMENT_TYPES,
    build_acceptance_text,
    expected_acceptance_text_hash,
)
from app.domains.legal.service import create_document_acceptance
from app.domains.purchases.contracts import (
    AcceptedPurchase,
    FinancialOperation,
    MAX_PURCHASE_LEGAL_DOCUMENTS,
    LegalEvidence,
    Purchase,
    PurchaseMeaning,
    PurchaseRefused,
)
from app.infrastructure.persistence.commercial_mappings import lock_mapping_scope
from app.infrastructure.queries.billing_customers import (
    customer_operation,
    lock_customer,
    recovery_work,
    open_customer_reviews,
    diagnostic_user,
)
from app.infrastructure.queries import purchases as queries
from app.models import (
    AcceptanceKind,
    BillingPurchaseScopeHold,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    LegalAcceptanceEvent,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)


def legal_evidence(
    db: Session, configuration: Settings, *, pin: bool = False, effective_at: datetime | None = None
) -> tuple[LegalEvidence, ...]:
    documents = queries.required_documents(
        db, configuration.instance_tenant_id, configuration.instance_region, pin=pin, effective_at=effective_at
    )
    if len(documents) > MAX_PURCHASE_LEGAL_DOCUMENTS or not set(REGISTRATION_DOCUMENT_TYPES).issubset(
        {doc.doc_type for doc in documents}
    ):
        raise PurchaseRefused("purchase_legal_unavailable", 503)
    return tuple(
        LegalEvidence(
            document_version_id=doc.id,
            doc_type=doc.doc_type,
            version=doc.version,
            content_hash=doc.content_hash,
            title=doc.title,
            url_path=doc.url_path,
            acceptance_text=build_acceptance_text(doc),
            acceptance_text_hash=expected_acceptance_text_hash(doc),
        )
        for doc in sorted(documents, key=lambda doc: str(doc.id))
    )


def read_legal(factory: SessionFactory, configuration: Settings, token: str) -> tuple[LegalEvidence, ...]:
    with factory() as db:
        authenticate(db, configuration, token)
        return legal_evidence(db, configuration)


def accepted(row: PurchaseIntent) -> AcceptedPurchase:
    try:
        result = AcceptedPurchase.model_validate_json(json.dumps(row.accepted_snapshot))
    except (ValueError, TypeError):
        raise PurchaseRefused("purchase_history_unproven", 409) from None
    if (
        row.accepted_snapshot_schema_version != result.schema_version
        or row.product_id != result.meaning.product_id
        or row.mapping_revision_id != result.meaning.revision_id
        or row.accepted_commercial_fingerprint != result.offer.fingerprint
        or result.meaning.expected_fingerprint != result.offer.fingerprint
        or row.billing_offer_id != result.selection.billing_offer_id
        or result.selection.product_id != row.product_id
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    return result


def _verify_original_consent(db: Session, row: PurchaseIntent, evidence: AcceptedPurchase) -> None:
    rows = queries.original_consent(db, row, limit=MAX_PURCHASE_LEGAL_DOCUMENTS + 1)
    expected = {
        (doc.document_version_id, doc.acceptance_text_hash, doc.doc_type, doc.version, doc.content_hash)
        for doc in evidence.documents
    }
    actual = {
        (document.id, acceptance.acceptance_text_hash, document.doc_type, document.version, document.content_hash)
        for acceptance, document in rows
    }
    if (
        actual != expected
        or len(rows) != len(expected)
        or any(
            acceptance.acceptance_kind
            != ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, AcceptanceKind.TERMS_ACCEPTANCE)
            for acceptance, document in rows
        )
    ):
        raise PurchaseRefused("purchase_consent_unproven", 409)


def verify_original_consent(factory: SessionFactory, purchase: Purchase) -> None:
    with factory() as db:
        row = queries.owned(db, purchase.user_id, purchase.id)
        if row is None:
            raise PurchaseRefused("purchase_not_found", 404)
        _verify_original_consent(db, row, purchase.accepted)


def _operation(db: Session, operation: ExternalCreateOperation, *, may_send: bool = False) -> FinancialOperation:
    agreement_date = None
    if operation.operation_kind == Kind.AGREEMENT and operation.recovery_hint_schema_version == "financial-create:v1":
        try:
            agreement_date = date.fromisoformat(operation.recovery_hint_document["request"]["create_date"])
        except (KeyError, TypeError, ValueError):
            raise PurchaseRefused("purchase_history_unproven", 409) from None
    work = recovery_work(db, operation.create_operation_id)
    candidate = work.payload_document.get("candidate_id") if work else None
    for value in (candidate, operation.bound_external_object_id):
        if value is not None and (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or len(value) > 20
            or not 0 < int(value) < 10**20
            or str(int(value)) != value
        ):
            raise PurchaseRefused("purchase_history_unproven", 409)
    failure = work.payload_document.get("last_failure") if work else None
    safe_failure = None
    failure_code = None
    if isinstance(failure, dict):
        failure_code = failure.get("code")
        if not isinstance(failure_code, str) or failure_code not in {
            "lbx_create_not_sent",
            "lbx_response_invalid",
            "lbx_provider_rejected",
            "lbx_unavailable",
            "lbx_timeout",
            "lbx_scope_mismatch",
            "lbx_authentication_failed",
            "lbx_scope_forbidden",
            "lbx_rate_limited",
            "lbx_attempts_exhausted",
            "preflight_deadline_exceeded",
            "preflight_closed",
            "preflight_saturated",
        }:
            failure_code = "financial_source_failure"
        status, code, reason = failure.get("http_status"), failure.get("lbx_code"), failure.get("reason")
        safe_failure = (
            status if type(status) is int and 100 <= status <= 599 else None,
            code if type(code) is int and -(2**31) <= code < 2**31 else None,
            reason
            if isinstance(reason, str)
            and reason
            in {
                "provider_rejected",
                "email_not_unique",
                "credentials_denied",
                "schema_invalid",
                "network",
                "timeout",
                "unknown",
            }
            else "unknown",
        )
    return FinancialOperation(
        operation.create_operation_id,
        operation.operation_kind,
        operation.operation_state,
        operation.request_correlation_key,
        operation.send_fence,
        operation.bound_external_object_id,
        candidate,
        queries.financial_recovery_deadline(operation, work),
        may_send,
        safe_failure,
        failure_code,
        agreement_date,
    )


def _snapshot(db: Session, row: PurchaseIntent) -> Purchase:
    scope = queries.hold(db, row.user_id, row.product_id)
    operations = queries.operations(db, row.purchase_intent_id)
    reasons = {
        case.reason_code
        for operation in operations
        for case in open_customer_reviews(db, operation.create_operation_id)
    }
    reason = None
    if row.state == IntentState.FAILED_BEFORE_EXTERNAL_EFFECT:
        reason = "terms_changed"
    elif row.state == IntentState.MANUAL_REVIEW:
        reason = (
            "purchase_binding_conflict"
            if "financial_binding_conflict" in reasons
            else "purchase_terms_changed_after_preparation"
            if "accepted_terms_changed_after_preparation" in reasons
            else "purchase_outcome_unknown"
            if any(value.startswith("external_create_outcome_unknown:") for value in reasons)
            else "purchase_review_required"
        )
    elif row.state in {IntentState.PREPARING, IntentState.AWAITING_EXTERNAL_RESULT}:
        reason = "purchase_pending"
    return Purchase(
        row.purchase_intent_id,
        row.user_id,
        row.customer_id,
        row.external_billing_account_id,
        row.state,
        accepted(row),
        row.created_at,
        bool(scope and scope.purchase_intent_id == row.purchase_intent_id),
        tuple(_operation(db, op) for op in operations),
        reason,
    )


def authenticate_user(factory: SessionFactory, configuration: Settings, token: str) -> UUID:
    with factory() as db:
        return authenticate(db, configuration, token).id


def read_purchase(factory: SessionFactory, user_id: UUID, purchase_id: UUID) -> Purchase:
    with factory() as db:
        row = queries.owned(db, user_id, purchase_id)
        if row is None:
            raise PurchaseRefused("purchase_not_found", 404)
        return _snapshot(db, row)


def other_inventory_purchase(
    factory: SessionFactory, purchase: Purchase, provider_id: int, agreement_id: int
) -> Purchase | None:
    """A tariff is not product identity; require the original permanent local binding."""
    with factory() as db:
        row = queries.subscription_purchase(
            db,
            user_id=purchase.user_id,
            customer_id=purchase.customer_id,
            account_id=purchase.account_id,
            provider_id=str(provider_id),
            agreement_id=str(agreement_id),
        )
        if row is None or row.product_id == purchase.accepted.selection.product_id:
            return None
        other = _snapshot(db, row)
        bindings = {op.kind: op for op in other.operations}
        if (
            other.state != IntentState.LINKED
            or not other.held
            or other.accepted.provider_origin != purchase.accepted.provider_origin
            or not {Kind.AGREEMENT, Kind.SUBSCRIPTION}.issubset(bindings)
            or any(op.state != State.BOUND for op in bindings.values())
            or bindings[Kind.AGREEMENT].bound_id != str(agreement_id)
            or bindings[Kind.SUBSCRIPTION].bound_id != str(provider_id)
        ):
            return None
        return other


def inspect_purchase(factory: SessionFactory, configuration: Settings, user_id: UUID, purchase_id: UUID) -> Purchase:
    with factory() as db:
        if (
            diagnostic_user(
                db, user_id=user_id, tenant_id=configuration.instance_tenant_id, region=configuration.instance_region
            )
            is None
        ):
            raise PurchaseRefused("purchase_not_found", 404)
        row = queries.owned(db, user_id, purchase_id)
        if row is None:
            raise PurchaseRefused("purchase_not_found", 404)
        return _snapshot(db, row)


def current_purchase(factory: SessionFactory, configuration: Settings, token: str, product_id: str) -> Purchase | None:
    with factory() as db:
        user = authenticate(db, configuration, token)
        scope = queries.hold(db, user.id, product_id)
        return _snapshot(db, queries.owned(db, user.id, scope.purchase_intent_id)) if scope else None


def prior_request(
    factory: SessionFactory, configuration: Settings, token: str, key: str, meaning: PurchaseMeaning
) -> Purchase | None:
    with factory() as db:
        user = authenticate(db, configuration, token)
        # Accepted meaning is immutable; a replay does not need the mutation lock.
        return _prior_request(db, user.id, key, meaning)


def _prior_request(db: Session, user_id: UUID, key: str, meaning: PurchaseMeaning) -> Purchase | None:
    candidates = queries.by_key(db, user_id, key)
    if len(candidates) > 1:
        raise PurchaseRefused("purchase_idempotency_conflict", 409)
    if candidates:
        previous = candidates[0]
        if accepted(previous).meaning != meaning:
            raise PurchaseRefused("purchase_idempotency_conflict", 409)
        return _snapshot(db, previous)
    if queries.hold(db, user_id, meaning.product_id) is not None:
        raise PurchaseRefused("purchase_scope_occupied", 409)
    return None


def pin_purchase(
    factory: SessionFactory,
    configuration: Settings,
    token: str,
    key: str,
    meaning: PurchaseMeaning,
    link: StoredProductLink,
    offer: CurrentOffer,
    documents: tuple[LegalEvidence, ...],
) -> Purchase:
    with factory() as db:
        user = authenticate(db, configuration, token)
        lock_user(db, user.id)
        # A concurrent acceptance may have committed since the initial replay read.
        previous = _prior_request(db, user.id, key, meaning)
        if previous is not None:
            return previous
        account = link.document.scope.external_billing_account_id
        # Same advisory boundary used by publication, then exact pointer recheck.
        lock_mapping_scope(db, account_id=account, offer_id="product-head:v2:" + meaning.product_id)
        head = queries.current_head(db, account, meaning.product_id)
        now = utc_now()
        current_documents = legal_evidence(db, configuration, pin=True, effective_at=now)
        selected = tuple((doc.document_version_id, doc.acceptance_text_hash) for doc in current_documents)
        if (
            head is None
            or head.mapping_revision_id != meaning.revision_id
            or head.provider_origin != configuration.lbx_provider_origin
            or link.mapping_revision_id != meaning.revision_id
            or offer.fingerprint != meaning.expected_fingerprint
            or current_documents != documents
            or selected != tuple((doc.document_version_id, doc.acceptance_text_hash) for doc in meaning.documents)
        ):
            raise PurchaseRefused("terms_changed", 409)
        customer = reserve_customer_in_transaction(db, configuration, user)
        slot = lock_customer(db, customer.customer_id)
        if slot.external_billing_account_id != account:
            raise PurchaseRefused("billing_connection_conflict", 409)
        if slot.binding_state == Binding.IDENTITY_CONFLICT:
            raise PurchaseRefused("billing_identity_conflict", 409)
        evidence = AcceptedPurchase(
            meaning=meaning,
            selection=link.document.selection,
            offer=offer,
            documents=documents,
            provider_origin=configuration.lbx_provider_origin,
            seller_id=int(configuration.lbx_seller_organization_id),
        )
        event = LegalAcceptanceEvent(
            id=uuid4(),
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            external_billing_account_id=account,
            billing_offer_id=link.document.selection.billing_offer_id,
            accepted_commercial_fingerprint=offer.fingerprint,
            accepted_at=now,
        )
        db.add(event)
        db.flush()
        rows = queries.required_documents(db, user.tenant_id, user.region, effective_at=now)
        for document in rows:
            create_document_acceptance(
                db,
                document=document,
                acceptance_event=event,
                acceptance_text_hash=expected_acceptance_text_hash(document),
            )
        row = PurchaseIntent(
            purchase_intent_id=uuid4(),
            user_id=user.id,
            customer_id=customer.customer_id,
            external_billing_account_id=account,
            product_id=meaning.product_id,
            billing_offer_id=link.document.selection.billing_offer_id,
            mapping_revision_id=meaning.revision_id,
            accepted_commercial_fingerprint=offer.fingerprint,
            client_idempotency_key=key,
            accepted_snapshot_schema_version=evidence.schema_version,
            accepted_snapshot=evidence.model_dump(mode="json"),
            legal_acceptance_event_id=event.id,
            state=IntentState.CREATED,
            created_at=now,
            state_updated_at=now,
        )
        db.add(row)
        db.flush()
        db.add(
            BillingPurchaseScopeHold(
                user_id=user.id,
                product_id=row.product_id,
                external_billing_account_id=account,
                purchase_intent_id=row.purchase_intent_id,
            )
        )
        for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
            operation_id = uuid4()
            db.add(
                ExternalCreateOperation(
                    create_operation_id=operation_id,
                    operation_kind=kind,
                    customer_id=customer.customer_id,
                    external_billing_account_id=account,
                    purchase_intent_id=row.purchase_intent_id,
                    request_correlation_key="portal-" + operation_id.hex,
                    operation_state=State.PENDING,
                )
            )
        db.flush()
        result = _snapshot(db, row)
        db.commit()  # Unknown acknowledgement is resolved by same-key lookup, never replayed here.
        return result


def customer_for_purchase(factory: SessionFactory, configuration: Settings, purchase: Purchase) -> CustomerOpen:
    with factory() as db:
        customer = lock_customer(db, purchase.customer_id)
        operation = customer_operation(db, customer.customer_id)
        if (
            customer.user_id != purchase.user_id
            or customer.external_billing_account_id != purchase.account_id
            or customer.provider_origin != configuration.lbx_provider_origin
            or customer.binding_state != Binding.BOUND
            or customer.provider_customer_id is None
            or operation is None
            or operation.operation_state != State.BOUND
            or operation.bound_external_object_id != customer.provider_customer_id
        ):
            raise PurchaseRefused("billing_identity_unproven", 409)
        return CustomerOpen(
            customer.customer_id,
            operation.create_operation_id,
            operation.send_fence,
            customer.billing_customer_key,
            customer.provider_customer_id,
        )


def _locked(db: Session, purchase: Purchase) -> PurchaseIntent:
    lock_user(db, purchase.user_id)
    row = queries.owned(db, purchase.user_id, purchase.id, lock=True)
    if row is None:
        raise PurchaseRefused("purchase_not_found", 404)
    if (
        not (scope := queries.hold(db, row.user_id, row.product_id))
        or scope.purchase_intent_id != row.purchase_intent_id
    ):
        raise PurchaseRefused("purchase_scope_released", 409)
    return row


def recheck_payment_purchase(factory: SessionFactory, configuration: Settings, token: str, expected: Purchase) -> None:
    """Last local auth/ownership/fence check after all asynchronous Widget work."""
    with factory() as db:
        user = authenticate(db, configuration, token)
        if user.id != expected.user_id:
            raise PurchaseRefused("purchase_not_found", 404)
        row = _locked(db, expected)
        _verify_original_consent(db, row, expected.accepted)
        current = _snapshot(db, row)
        if current.state != IntentState.LINKED or current.operations != expected.operations:
            raise PurchaseRefused("purchase_not_prepared", 409)
