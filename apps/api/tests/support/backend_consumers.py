"""Synthetic, independently credentialed consumer configurations."""

from typing import Any

from app.core.backend_consumers import BackendConsumer


def backend_consumer(**overrides: Any) -> BackendConsumer:
    values = dict(
        consumer_id="platform-kernel",
        tenant_id="anytoolai",
        region="ru",
        consumer_policy_revision=1,
        allowed_products=["proposal_ai", "client_update_writer", "brief_decoder", "acceptance_builder", "kernel_demo"],
        permissions=["backend-session:exchange", "backend-session:introspect", "access-snapshot:read"],
        callback_url="https://kernel.example.test/portal-session/callback",
        backend_base_url="https://kernel.example.test",
        technical_source_id="platform-kernel",
        backend_to_portal_current_secret="synthetic-kernel-service-" + "s" * 32,
        backend_to_portal_previous_secret="synthetic-old-service-" + "p" * 32,
        portal_to_backend_current_secret="synthetic-portal-to-kernel-" + "o" * 32,
    )
    values.update(overrides)
    return BackendConsumer.model_validate(values)


def second_consumer(**overrides: Any) -> BackendConsumer:
    return backend_consumer(
        **dict(
            consumer_id="synthetic-summary",
            allowed_products=["synthetic_summary"],
            technical_source_id="synthetic-summary",
            callback_url="https://summary.example.test/callback",
            backend_base_url="https://summary.example.test",
            backend_to_portal_current_secret="synthetic-summary-service-" + "c" * 32,
            backend_to_portal_previous_secret="synthetic-summary-previous-" + "p" * 32,
            portal_to_backend_current_secret="synthetic-portal-to-summary-" + "o" * 32,
        )
        | overrides
    )
