"""Bounded GET-only customer diagnosis. Never binds, resets, CREATEs or mints JWTs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

import httpx
from starlette.concurrency import run_in_threadpool

from app.composition.sources import source_resources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.customer_diagnostics import diagnostic_owner_conflict, load_customer_diagnostics
from app.domains.catalog.publication import SessionFactory
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.errors import LbxError
from app.models import ExternalBillingCustomerBindingState as Binding, ExternalCreateOperationState as State


async def diagnose_customer(
    configuration: Settings,
    *,
    factory: SessionFactory,
    user_id: UUID,
    lbx_transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    state = await run_in_threadpool(load_customer_diagnostics, factory, configuration, user_id)
    report = {
        **state.report,
        "observed_at": datetime.now(UTC).isoformat(),
        "lbx_checked": False,
        "lbx_error": None,
        "lbx_response_facts": None,
        "key_candidates": [],
        "email_candidates": [],
        "identity_verified_ids": [],
        "writes_performed": False,
        "create_performed": False,
        "retry_authorized": False,
        "widget_checked": False,
    }
    diagnosis = state.local_problem or (
        "email_verification_required" if not report["email_verified"] else "create_outcome_unknown"
    )
    if not state.local_problem and report["email_verified"]:
        if configuration.lbx_configuration_error:
            report["lbx_error"] = configuration.lbx_configuration_error
        else:
            try:
                async with source_resources(configuration, lbx_transport=lbx_transport) as sources:
                    with customer_diagnostics(str(state.operation_id)):
                        async with sources.billing.operation() as budget:
                            client = sources.require_lbx()
                            report["lbx_checked"] = True
                            key_ids = await client.discover_users(outer_id=state.outer_key, budget=budget)
                            email_ids = set()
                            for email in dict.fromkeys((state.email, state.email_normalized)):
                                email_ids.update(await client.discover_users_by_email(email=email, budget=budget))
                            report.update(
                                lbx_checked=True, key_candidates=list(key_ids), email_candidates=sorted(email_ids)
                            )
                            candidates = sorted({int(value) for value in state.provider_ids} | set(key_ids) | email_ids)
                            if len(candidates) > 5:
                                diagnosis = "candidates_ambiguous"
                            else:
                                verified = []
                                for candidate in candidates:
                                    point = await client.get_user(user_id=candidate, budget=budget)
                                    if point.outer_id == state.outer_key:
                                        verified.append(candidate)
                                report["identity_verified_ids"] = verified
                                if len(key_ids) > 1 or len(verified) > 1:
                                    diagnosis = "candidates_ambiguous"
                                elif (
                                    state.provider_ids
                                    and set(map(int, state.provider_ids)) != set(verified)
                                    or set(key_ids) - set(verified)
                                    or report["binding_state"] == Binding.IDENTITY_CONFLICT
                                ):
                                    diagnosis = "identity_conflict"
                                elif verified and report["binding_state"] == Binding.BOUND:
                                    diagnosis = (
                                        "binding_verified"
                                        if report.get("operation_state") == State.BOUND
                                        else "identity_conflict"
                                    )
                                elif verified:
                                    diagnosis = "customer_found_unbound"
                                else:
                                    diagnosis = "email_candidates_unproven" if email_ids else "create_outcome_unknown"

                # Ownership is read after HTTP, without any open DB/network overlap.
                if report["identity_verified_ids"]:
                    if await run_in_threadpool(
                        diagnostic_owner_conflict,
                        factory,
                        configuration,
                        user_id,
                        account_id=state.account_id,
                        customer_id=state.customer_id,
                        provider_ids=tuple(report["identity_verified_ids"]),
                    ):
                        diagnosis = "identity_conflict"
            except AppError as error:
                report["lbx_error"] = error.code
                if isinstance(error, LbxError) and error.response_facts is not None:
                    report["lbx_response_facts"] = asdict(error.response_facts)
        if report["lbx_error"]:
            facts = report["lbx_response_facts"]
            diagnosis = {
                "provider": "source_rejected",
                "authorization": "source_auth_failed",
                "invalid_response": "source_invalid_response",
                "rate_limit": "source_rate_limited",
            }.get(facts["failure_kind"] if facts else None, "source_unavailable")
        # Historical failure explains a held, still-unbound slot even when GETs
        # return zero. It never establishes absence or authorization to retry.
        if (
            diagnosis in {"create_outcome_unknown", "email_candidates_unproven", "source_unavailable"}
            and not state.provider_ids
            and not report["identity_verified_ids"]
            and report["create_responses"]
            and report["create_responses"][0]["reason"] == "email_not_unique"
        ):
            diagnosis = "email_conflict"
    actions = {
        "binding_verified": "investigate_client_readiness_or_widget",
        "customer_found_unbound": "open_billing_to_recover_existing_customer",
        "create_outcome_unknown": "open_billing_to_search_and_retry",
        "email_conflict": "correct_email_conflict_then_open_billing",
        "email_verification_required": "verify_portal_email",
        "not_provisioned": "open_billing_through_portal",
        "source_unavailable": "check_lbx_connection_and_repeat_diagnosis",
        "source_rejected": "investigate_lbx_rejection",
        "source_auth_failed": "check_lbx_credentials_and_permissions",
        "source_invalid_response": "investigate_lbx_response_contract",
        "source_rate_limited": "wait_then_repeat_diagnosis",
    }
    report.update(diagnosis=diagnosis, next_action=actions.get(diagnosis, "manual_review"))
    return report
