# Payment and Security Review

- Payment authority comes from a verified webhook or server-side reconciliation.
- Idempotency prevents duplicate payments, refunds, or state transitions.
- Card data, secrets, tokens, and authorization headers are absent from storage
  and telemetry.
- Personal data does not appear in metric labels or unnecessary trace attributes.
- Legal acceptance records remain append-only and version-specific.
