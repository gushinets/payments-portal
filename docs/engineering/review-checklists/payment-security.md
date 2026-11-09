# Payment and Security Review

- Follow the billing authority chain in [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md).
- Paid access derives from verified authoritative source facts through the shared
  writer. Widget/browser callbacks, webhook receipt, outbound success and payment
  state alone grant no access; the current runtime is polling-only.
- Permanent operation identities, idempotency and fences prevent duplicate
  financial CREATE and stale state application. Unknown outcomes remain GET-only
  recovery, without another financial send.
- Card data, raw tokens, authorization headers and provider secrets are absent
  from application records and telemetry; credentials stay in protected configuration.
- Personal data does not appear in metric labels or unnecessary trace attributes.
- Legal acceptance records remain append-only and version-specific.
