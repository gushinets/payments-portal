# Security Requirements

Status: authoritative
Last verified: 2026-09-24

## Sensitive data

ANY-715 Step 1 reconciliation persists allowlisted normalized conclusions,
calendar facts and immutable local provenance, never raw source payloads,
credentials or contact fields. Scope and original customer/agreement/subscription
bindings are server-resolved and rechecked under locks before apply. Conflicts
cannot silently rebind or grant access; see
[billing operations](engineering/ANY-715-billing-operations.md).

Never collect, persist, or log full card data. Redact card-related external
fields, raw session, password-reset, and email-verification tokens,
authorization headers, webhook secrets, passwords, and private billing or
payment configuration before logging or tracing.

Email and IP data are personal data. Record them only where the documented legal
or security purpose requires them, and never add them to metric labels.

## Telemetry correlation and emission

Current identity/legal diagnostics emit only approved bounded local references.
Future target billing runtime may emit local `purchase_intent_id`,
`create_operation_id`, `delivery_id`, `work_item_id`, `subscription_id`,
`observation_id`, or `review_case_id` when the owning flow provides a concrete
incident lookup. They are diagnostic references only and must never become
metric labels.

Keep these categories distinct:

- Local IDs identify a durable Payment Portal record without exposing provider
  or customer data.
- Durable local references are looked up in persisted evidence records rather
  than inferred from telemetry alone.
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

## Sentry event privacy contract

Sentry receives only explicitly allowlisted backend application-failure data:

- release, application environment, and service identity;
- failure category, stable operation, and exception type;
- sanitized stack locations and safe exception-cause structure;
- validated request, trace, span, and scheduled-run correlation IDs;
- the matched route template and approved application failure location; and
- explicitly allowlisted static or bounded diagnostic fields such as an
  invariant identifier or batch size.

Sentry events must not contain raw exception messages, locals, source-code
context, request or response bodies, raw URL or path values, query values,
headers, cookies, user or email data, IP data, provider payloads or external
provider identifiers, authorization data, tokens, card data, or payment values.
High-cardinality request, trace, span, and run IDs are contexts only; they must
not become tags or fingerprints.

Application-owned allowlisting and scrubbing before an event leaves the process
is the primary privacy control. Sentry project data scrubbing and disabled or
policy-compliant IP collection are required defense in depth, not permission to
send forbidden data. Operators must also configure useful project notifications
for new or regressed production issues; project provisioning and notification
automation are outside this repository.

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
  trusting external state. ANY-709 implements real source reads and an explicit
  account Widget bootstrap. Step 3 implements accepted-purchase preparation and
  point-verified payment presentation; automated checks and recorded owner
  intended-agreement test-payment QA passed. Independent final review remains
  pending. Paid-access
  derivation remains deferred.
- Treat request IDs and external billing or payment metadata as untrusted input
  with length and character limits.
- Store session tokens only as hashes.
- Store password-reset and email-verification tokens only as hashes, and keep
  fragment tokens out of browser persistence and query parameters.
- Keep external integration secrets in environment or a secret manager, never
  migrations, seed files, telemetry, or source control.
- Paid access changes only from authenticated, validated authoritative billing
  facts normalized through the local transition path. Browser returns are
  informational and never authoritative.

## Account Widget credentials (ANY-709 Step 2)

Only explicit authenticated POST after verified email may allocate the single
customer slot. Before users POST, the permanent operation, opaque outer key,
send fence, per-attempt two-hour deadline and coalesced recovery work are committed.
Under the owner-approved 2026-10-28 customer amendment, each explicit open uses a
bounded discover/create/recover cycle. Temporary failures wait with backoff within
the existing request deadline. A finite active-send lease protects sends; each
later claim requires fresh successful empty discovery in the same slot/operation.
A saved receipt must be resolved by point proof. Email-uniqueness rejection
permits GET recovery only for the rest of the opening; ambiguous identity, failed
discovery, authorization and permanent validation errors never authorize CREATE.
The selected customer policy relies on LBX email uniqueness; agreement and
subscription retries remain stricter. Unresolved integration errors are
reported once through the sanitized Sentry boundary. No fake
PurchaseIntent, subscription, name, password repair or agreement is created for
account viewing. Proven provider IDs are unique within the connection scope.

Every open point-checks Server `user_id`/original `outer_id`, checks Client API
readiness and rechecks the Portal session after I/O. Only then is the fresh
HS256 type-7 credential returned with no-store. Technical login/password exist
only in the one outbound request; JWTs and credentials never enter durable
recovery evidence, browser storage, logs or URLs. The SDK runs in a disposable
opaque-origin frame with a CSP restricted to the validated configured provider
origin. Logout/unmount removes Portal-held SDK/token memory.

These local lifecycle controls do not revoke a copied provider JWT. LBX's accepted
72h `iat` behavior and provider-owned Client API permissions remain unchanged;
presentation flags are not ACLs. Account-view flags disable purchasing/payment.
Step 3 payment presentation requires owned original acceptance plus fresh concrete
subscription/customer/seller/agreement readback, followed by auth and fence rechecks.
It enables only the payment presentation flag; subscription create/edit, autopay,
invoice and stop controls stay disabled. Financial CREATE never inherits the
customer later-open retry policy, and UNKNOWN keeps its hold and original +2h
deadline. No operation or Widget outcome grants paid access.
Account viewing has no catalog, price, seller-agreement or subscription prerequisite.

Step 4 uses one disposable SDK lifecycle for account and payment views. Opening
another presentation destroys the previous host; product/user changes, logout,
close and late-response guards prevent local credential reuse. Only proven
payment presentation permits sandboxed forms, acquiring popups that can leave
the sandbox, and user-activated navigation. Account viewing retains its stricter
sandbox. These browser capabilities enable provider payment UX, do not establish
ACLs or paid access, and require real-method human acceptance. Widget close reads
local status only; the UI explicitly awaits authoritative payment verification.

SDK `render()` returning is not readiness proof. The isolated host accepts the
existing `lbx-widget` READY message only from its actual nested window at the
configured provider origin. Its bounded startup deadline remains active until
that message; host/script/readiness failures remove the frame and show the
correlated request ID. The console and optional Sentry receive only fixed
operation/stage, a closed failure reason and a validated request ID. The Sentry
sanitizer discards raw messages, request data, URLs, breadcrumbs and user fields.
No third-party frame document is inspected. READY establishes only startup
readiness, not client-data, payment, subscription or access authority. Once ready,
no loading timer may interrupt an active checkout.

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

## ANY-709 analyzer adjudication, PR 150

Sonar issue `AaF3I2LPjkGs2B7KgoeF` (`typescript:S2819`) flags the SDK host's
`postMessage` target `*`. This specific use is a false positive: the receiver is
an exact Portal-created `data:` frame with an opaque origin. The
[Window.postMessage contract](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)
requires `*` for such receivers. The window message carries a fixed handshake
and transferred private port, never the JWT. The host accepts only its parent,
removes the window listener before loading the configured remote SDK and receives
the JWT over the dedicated port. The host URL/HTML contains no credential.
Changing the target to the vendor HTTPS origin breaks this opaque-frame handshake;
loading the SDK on the Portal origin removes the intended isolation. Component
coverage verifies the actual window/port payloads, listener ordering and teardown.
The documented `NOSONAR` exception is confined to this handshake line because
scanner administration is not authenticated in this session. It addresses this
false positive without disabling the rule or excluding the file from analysis.

CodeQL alert 5 (`py/clear-text-logging-sensitive-data`) flags `print(output)` in
`apps/api/tests/support/v1_cli.py`. This is a retained test-support CLI, excluded
from the production image. Output is deliberately normalized mapping evidence
(commercial IDs, references, operator reason), not configuration, raw provider
responses, credentials or customer PII. The existing PostgreSQL CLI test checks
password/token/PII canaries in dry-run, publish and query output. Operator-provided
reason text must remain nonsecret; it has the same authorized input/DB boundary.
Keep the useful output. Alert 5 was dismissed as false positive on 2026-10-27,
with the rationale retained in GitHub and here.
These are independent findings; neither proves real-method Widget acceptance.
