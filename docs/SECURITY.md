# Security Requirements

Status: authoritative
Last verified: 2026-09-08

## Sensitive data

Never collect, persist, or log full card data. Redact card-related external
fields, raw session tokens, authorization headers, webhook secrets, passwords,
and private billing or payment configuration before logging or tracing.

Email and IP data are personal data. Record them only where the documented legal
or security purpose requires them, and never add them to metric labels.

## Telemetry correlation and emission

The following are local Payment Portal identifiers that may be emitted in the
approved bounded diagnostics when their flow provides a concrete incident
lookup: `order_id`, `payment_id`, `subscription_id`, `webhook_event_id`, and
`run_id`. They are diagnostic references only and must never become metric
labels. `refund_id` is a local durable business and audit lookup reference
already available through lifecycle data such as `SubscriptionEvent`; it is not
a new ANY-437 telemetry emission.

Keep these categories distinct:

- Local IDs identify a durable Payment Portal record without exposing provider
  or customer data.
- Durable local references, including `refund_id`, are looked up in persisted
  lifecycle and audit records rather than inferred from telemetry alone.
- Provider transaction IDs, provider invoice IDs, email, user-provided account
  identifiers, authorization or token data, card data, arbitrary headers or
  query values, raw payloads, amounts, and raw exception text are not telemetry
  correlation keys.

Redaction is defense in depth, not permission to put unsafe data into a log
message or arbitrary logging extra. Critical diagnostics must be safe at the
emission site: use static event/message names and explicitly selected bounded
structured fields. Do not interpolate provider values, payloads, secrets, or
error text into free-form messages. The new bounded business diagnostics do not
use raw exception text or `exc_info`.

Automatic HTTP tracing must retain useful path and route identification without
retaining arbitrary query values. Arbitrary request-header capture is not
enabled. Business/entity identifiers remain in logs or durable records where
needed for incident reconstruction, never in metric labels.

## Durable webhook receipt

After authentication and minimal validation, webhook receipt must be durable
before external acknowledgement and subsequent normalized processing, but the
default persistence boundary must whitelist and redact data before storage.
Store only whitelisted or redacted metadata and safe normalized fields that the
concrete integration actually requires, such as the integration identifier,
event type, safe external identifiers, timestamps, hashes, normalized idempotency
keys, processing state, and safe normalized recovery fields.

Never persist raw query-string secrets, authorization or webhook secrets,
unrestricted raw headers, or unrestricted sensitive payloads merely to make
receipt durable. A concrete integration may persist additional payload data only
under a separately approved integration-specific requirement that defines its
need, security treatment, and retention.

## Trust boundaries

- Validate HTTP, environment, webhook, and database-boundary data.
- Verify authenticity at every external billing or payment Integration before
  trusting external state. The implemented `ru` CloudPayments integration
  verifies webhook signatures.
- Treat request IDs and external billing or payment metadata as untrusted input
  with length and character limits.
- Store session tokens only as hashes.
- Keep external integration secrets in environment or a secret manager, never
  migrations, seed files, telemetry, or source control.
- Paid access changes only from authenticated, validated authoritative billing
  facts normalized through the local transition path. Browser returns are
  informational and never authoritative.

## High-risk review paths

Authentication, payments, legal sources and seeds, migrations, telemetry
redaction, production Compose, deployment configuration, and secret handling
require human review. Agents may prepare changes and evidence but may not merge
them autonomously.

## Dependency and container scanning

Dependabot checks npm, uv, Dockerfile, Docker Compose, and GitHub Actions
dependencies weekly. Repository administrators must keep Dependabot alerts and
security updates enabled in GitHub; those settings are not controlled by
`.github/dependabot.yml`.

The `Security scans` workflow scans the repository filesystem and both
production images on pull requests, pushes to `main`, a weekly schedule, and
manual dispatch. JSON reports are retained as workflow artifacts for 14 days.
Scans must write findings to reports instead of workflow logs. Secret match and
source-code fields are removed before upload so detected values are neither
printed nor retained in workflow artifacts.

Trivy's built-in IaC checks are supplemented by a separate Compose-policy scan
configured in `trivy-compose.yaml`. Repository-owned checks under
`security/trivy` reject privileged services, host namespace sharing, Docker
socket mounts, and adding all Linux capabilities. Keeping the raw YAML scan
separate prevents it from replacing Trivy's built-in Kubernetes and other IaC
adapters.

The initial rollout is report-only while the baseline is remediated. After human
approval, set the repository Actions variable `TRIVY_ENFORCE=true`. The checked-in
gate then rejects all Critical vulnerabilities, fixable High vulnerabilities,
and High or Critical secret and misconfiguration findings. Exceptions belong in
`.trivyignore.yaml` and must include an ID, an actionable statement naming the
affected image or path and its owner, an expiration date, and either affected
paths or package PURLs. Use a package PURL for an OS-package image finding
without `PkgPath`; adding a source path to Trivy's `paths` filter would prevent
that exception from matching the image finding.

The root npm overrides for vulnerable nanoid 3.x and `brace-expansion` 1.x
releases are temporary security constraints. Remove the nanoid override once
every parent that requires the 3.x line resolves `3.3.18` or newer without it.
Remove the `brace-expansion` override once every parent that requires the 1.x
line resolves `1.1.18` or newer without it. In both cases, regenerate the
lockfile and confirm that npm audit and the Trivy filesystem scan remain free of
Critical and fixable High findings before removing the override.
