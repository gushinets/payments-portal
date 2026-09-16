# ANY-493 — Establish Order / Payment / Refund Application Transitions

## Plan Overview

| Field | Value |
| --- | --- |
| Parent | `ANY-407` |
| Ticket | `ANY-493` |
| Immediate predecessor | `ANY-490` / PR #103 |
| Predecessor baseline | Reviewed `ANY-490` branch; current reviewed head used during planning: `4e6395b938dfff7c5058dc04032d102a08460209` |
| Overall status | `ready for execution from reviewed ANY-490 branch` |
| Execution order | Sequential only: Step 1 → review/verify/commit → Step 2 → review/verify/commit → Step 3 → review/verify/commit → Step 4 |
| Steps / proposed commits | 4 |
| Database migration | No |
| Public API change | No |
| Persisted behavior change | Yes — new canonical transitions stop populating provider-specific `Payment.raw_summary`; canonical Payment amount/currency no longer preserve provider-only partial-cancel amounts; explicitly contradictory/stale retained webhook facts may receive the new canonical `FAILED`/`IGNORED` processing classification instead of legacy integration-specific classification; historical persisted values remain untouched |
| New external dependency | No |
| CloudPayments runtime activation | No |

---

# Execution Baseline and Branching Strategy

## Start from the reviewed predecessor; do not wait for merge approval

`ANY-407` is implemented sequentially by dependency, not by waiting for every predecessor PR to be merged before the next implementation can start.

`ANY-493` must branch directly from the reviewed `ANY-490` branch / PR #103 baseline and may be implemented and reviewed while PR #103 is still waiting for final approval/merge.

The intended dependency chain is:

```text
main
  -> ANY-490 (reviewed Step 7 baseline)
      -> ANY-493 (Step 8 implementation)
```

Waiting for `ANY-490` to merge is **not** a prerequisite for starting, implementing, reviewing, or testing `ANY-493`.

This is the normal dependency-inheritance workflow for the sequential ANY-407 chain.

The only required predecessor synchronization rule is:

1. create `ANY-493` from the reviewed `ANY-490` head;
2. if `ANY-490` receives additional commits while `ANY-493` is in progress, continue Step 8 work unless those commits materially invalidate a Step-8 assumption;
3. before final verification / final merge of `ANY-493`, synchronize the final predecessor state into the branch using the team's normal Git workflow;
4. revalidate only assumptions affected by the predecessor delta;
5. do **not** restart broad research merely because the predecessor merged;
6. if the predecessor delta materially changes transaction ownership, persistence boundaries, Presentation/Application boundaries, or the commercial code assumed by this plan, stop and update the affected part of this plan instead of improvising a redesign during implementation.

`ANY-493` must not implement or repair Step-7 work itself. Dependency inheritance is only a way to keep sequential development moving without idle time.

## How to use this file

Execute exactly one step at a time.

After every step:

1. inspect the diff;
2. run only the manual verification commands listed for that step;
3. review the step as one coherent architectural change;
4. create the proposed commit manually if accepted;
5. continue only after the previous step is accepted.

The four steps are intentionally sized to avoid tiny fragmented changes while keeping each review logically bounded:

```text
Step 1  Canonical commercial Application boundary: Payment + Refund
Step 2  Retained CloudPayments delegates to that boundary
Step 3  PostgreSQL concurrency / atomicity proof
Step 4  Architecture ratchet + authoritative docs + final verification
```

---

# Context and Locked Decisions

## Current state to preserve

The predecessor architecture already provides the foundation required by Step 8:

- `app.models.Order`, `Payment`, and `Refund` are the canonical persisted commercial projections;
- `OrderStatus`, `PaymentStatus`, and `RefundStatus` are the canonical persisted vocabularies;
- Payment external identity is protected by the existing unique `(provider_account_id, provider_payment_id)` partial index;
- Refund external identity is protected by the existing unique `(provider_account_id, provider_refund_id)` partial index;
- focused query modules already own Order, Payment, Refund, and provider-account query mechanics;
- Application owns business transitions and caller-owned business transaction orchestration;
- focused Infrastructure helpers may own SQLAlchemy/PostgreSQL mechanics such as row locks, `flush()`, targeted nested savepoints, and expected storage-conflict recovery, but must not own business transition meaning;
- CloudPayments remains absent from normal runtime and is retained only as compatibility/historical code;
- the durable CloudPayments webhook inbox is intentionally committed before normalized processing;
- the existing Subscription/Entitlement lifecycle remains the temporary downstream compatibility consumer until Step 9;
- Presentation/Application separation from ANY-490 remains the baseline.

Do not introduce:

- repository-per-table abstractions;
- a generic Unit of Work;
- a parallel pure-domain ORM hierarchy;
- a generic command bus;
- a generic event bus;
- a generic billing framework;
- speculative future-vendor contracts.

## Actual Step-8 gap

Commercial state-machine ownership is still duplicated inside retained CloudPayments code:

```text
CloudPayments integration
    -> decides Payment state
    -> mutates Payment
    -> decides Order state
    -> mutates Order
    -> creates Refund
    -> updates refunded totals
    -> recomputes aggregate Order refund state
```

The target after ANY-493 is:

```text
Integration / verified source
    -> authenticate / validate external protocol
    -> correlate / redact / normalize
    -> provider-neutral verified commercial fact
    -> Application commercial transition
        -> lock canonical local state
        -> revalidate local correlation
        -> enforce commercial transition policy
        -> mutate Order / Payment / Refund atomically
        -> flush
    -> optional existing Step-9 compatibility handoff
```

Application transitions participate in a caller-owned transaction. They must never call top-level `commit()` or `rollback()`.

## Order creation remains outside Step 8

Checkout remains responsible for creating the local purchase intent and initial `Order`.

ANY-493 does not add a generic `create_order` transition and does not redesign checkout.

Step 8 owns commercial outcome transitions after the Order already exists.

## Durable webhook inbox remains two-phase

Retained CloudPayments webhook handling keeps the established durable receipt boundary:

```text
receive + authenticate + redact
    -> persist PaymentWebhookEvent
    -> COMMIT durable inbox

then

normalize/process verified fact
    -> Application commercial transition
    -> existing Step-9 compatibility handoff when newly applicable
    -> COMMIT or ROLLBACK normalized work
```

ANY-493 must not collapse these phases.

## Step 8 → Step 9 boundary

A newly applicable Payment or Refund transition may still trigger the existing subscription lifecycle for compatibility, but:

- the canonical commercial transition must not query or mutate `Subscription` or `Entitlement`;
- Subscription/Entitlement state must not participate in deciding Order/Payment/Refund state;
- the caller may invoke the existing downstream lifecycle only from an explicit transition result such as `order_became_paid` or `refund_created`;
- redesign of subscription/entitlement transitions belongs to Step 9.

## Provider command responses are not payment authority

A provider REST command response or lookup response is not automatically a confirmed local commercial fact.

Only an appropriately authenticated/validated/normalized authoritative fact may invoke the canonical transition.

Unknown, ambiguous, stale, conflicting, duplicated, or out-of-order observations must not be guessed into confirmed local success/failure.

---

# Research Classification

## Already-correct components to preserve

- canonical persisted ORM models/enums;
- existing Payment/Refund external-identity uniqueness;
- Order-first locking direction;
- caller-owned transaction contract from ANY-489;
- targeted savepoints for recoverable storage races;
- durable webhook inbox from ANY-94;
- CloudPayments signature verification, parsing, redaction, protocol response formatting, and provider-specific request validation;
- provider-neutral transaction lookup/result normalization already present in the repository;
- existing subscription lifecycle as the temporary downstream compatibility consumer;
- CloudPayments runtime deactivation;
- ANY-490 Presentation/Application separation.

## Step-8 gaps to resolve

- Payment transition policy still exists in retained CloudPayments processing;
- Order commercial outcome policy still exists in retained CloudPayments processing;
- Refund creation/refunded-total accounting remains integration-owned;
- aggregate Order refund state remains integration-owned;
- terminal/stale/out-of-order commercial rules are distributed across integration helpers;
- there is no reusable provider-neutral Application transition for future verified webhook/reconciliation facts;
- cross-Order uniqueness races have a DB backstop but do not yet produce one canonical Application conflict result;
- commercial duplicate semantics are not yet separated cleanly from webhook-delivery duplicate semantics.

## Retained CloudPayments-only responsibilities

These remain Integration concerns and must not become canonical Application vocabulary:

- HMAC/signature rules;
- endpoint names such as `pay`, `confirm`, `cancel`, `refund`, `check`;
- CloudPayments status strings;
- CloudPayments response codes;
- safe/raw payload shape;
- provider-specific webhook idempotency-key construction;
- `AccountId` / email protocol validation;
- `check` notification semantics;
- `recurrent` parsing;
- CloudPayments DTOs;
- raw provider diagnostics beyond narrow structured canonical fields.

## Deferred work

Do not implement:

- Step 9 Subscription / Entitlement transition redesign;
- Step 10 external-billing command orchestration;
- Step 11 reconciliation workers/schedulers/cursors;
- future external-billing persistence schema;
- retained CloudPayments schema migration;
- generic billing fact dispatcher;
- generic inbox/outbox framework;
- broad cleanup/deletion of inactive CloudPayments code unrelated to duplicate commercial-state ownership.

---

# Canonical Step-8 Commercial Transition Contract

## Application location

Use the existing Billing Application/service area.

Primary module:

```text
apps/api/app/domains/billing/service/commercial_transitions.py
```

It owns:

- typed provider-neutral commercial commands;
- typed transition results;
- Payment state policy;
- Refund state policy;
- coupled Order effects;
- duplicate / ignored / conflict classification;
- canonical ORM mutation decisions for Order / Payment / Refund.

It may:

- receive a SQLAlchemy `Session`;
- use focused Infrastructure query/persistence capabilities;
- mutate canonical ORM entities;
- call `db.add()` / `db.flush()`.

It must not:

- compose persistence queries when an established focused capability should own that mechanics;
- call top-level `commit()` / `rollback()`;
- import FastAPI/Starlette;
- import CloudPayments or another concrete integration;
- use vendor-specific statuses/DTOs as canonical commercial semantics;
- inspect raw webhook payloads;
- call external networks;
- query/mutate Subscription or Entitlement state.

## Application-local Payment outcome vocabulary

Introduce a small non-persisted vocabulary containing only currently demonstrated authoritative outcomes:

```text
AUTHORIZED
SUCCEEDED
FAILED
CANCELED
```

Do not reuse provider command/lookup status types that include `UNKNOWN` as the canonical mutation vocabulary.

Refund success is a separate commercial transition.

## Transition disposition

Use one typed Application result vocabulary:

```text
APPLIED
DUPLICATE
IGNORED
CONFLICT
```

A result should expose at least:

```text
disposition
order_id
payment_id
refund_id                # Refund only
resulting statuses
safe internal reason_code when relevant
order_became_paid        # true only for a newly applied Order -> PAID transition
refund_created           # true only for a newly inserted/applied Refund
```

`DUPLICATE`, `IGNORED`, and `CONFLICT` are expected commercial outcomes, not unexpected programming exceptions.

Unexpected persistence/programming failures still raise normally.

## Important distinction: commercial duplicate != webhook-delivery duplicate

`TransitionDisposition.DUPLICATE` and `PaymentWebhookEventStatus.DUPLICATE` represent different layers and must not be mapped mechanically.

- **Webhook-delivery duplicate** means the retained durable inbox recognizes the same logical delivery/idempotency identity before commercial processing. That remains `PaymentWebhookEventStatus.DUPLICATE`.
- **Commercial duplicate** means a fresh verified source reached Application but the same commercial Payment/Refund identity has already been applied safely. That means "no commercial mutation required" and is not automatically an inbox duplicate.

For a fresh inbox row that reaches Application:

- `APPLIED` maps to `PROCESSED`;
- commercial `DUPLICATE` also maps to `PROCESSED`, with no commercial mutation and no downstream Step-9 effect;
- `IGNORED` maps to retained inbox `IGNORED`;
- `CONFLICT` maps to durable `FAILED` processing with a safe internal error code.

`PaymentWebhookEventStatus.DUPLICATE` is reserved exclusively for durable-inbox delivery/idempotency duplicate detection that occurs before commercial processing. A fresh verified provider delivery must never be marked as inbox `DUPLICATE` merely because Application reports that the same Payment/Refund commercial identity has already been applied.

This preserves a strict separation between transport idempotency and commercial idempotency without moving provider protocol policy into Application.

---

# Payment Contract

## Payment identity and correlation

Every authoritative Payment fact supplied to Application must identify:

- local `order_id`;
- provider namespace;
- local `provider_account_id`;
- non-empty opaque `provider_payment_id`;
- optional external invoice reference when available;
- normalized outcome;
- positive `amount_minor`;
- normalized currency;
- timezone-aware occurrence timestamp;
- optional safe failure code/message;
- optional normalized payment-method type when already part of the canonical projection.

Do not include:

- email;
- CloudPayments `AccountId`;
- endpoint name;
- raw provider status;
- raw/safe arbitrary payload dictionaries;
- signatures/HMAC material;
- webhook acknowledgement semantics.

Before mutation Application validates:

```text
Order.provider
Order.provider_account_id
PaymentProviderAccount.id/provider/tenant_id/region
Order.tenant_id/region
Payment.order_id/provider_account_id/provider when existing
amount
currency
provider_payment_id
provider_invoice_id when supplied and semantically available
```

An account does not have to remain `enabled` for an already-created Order to receive a later authoritative fact.

### CloudPayments provider-account context

For retained CloudPayments webhooks, `provider_account_id` is local correlation context derived from the already correlated local Order / durable inbox context. It is **not** represented as if CloudPayments had sent a trusted provider-account UUID.

Application must still reload/revalidate the local `PaymentProviderAccount` and locked `Order` relationship before mutation.

Provider-specific evidence such as configured CloudPayments PublicId remains Integration validation and must not leak into the Application command.

## Payment amount and currency policy

Canonical Application Payment transitions operate on the immutable commercial amount/currency of the Payment attempt.

For a **new external Payment identity**:

```text
amount_minor == Order.amount_minor
currency == Order.currency
```

is required before creating the Payment projection.

For an **existing Payment identity**, the incoming authoritative fact must match the persisted Payment amount/currency. A mismatch is `CONFLICT`; Application must never rewrite the financial identity of an existing Payment.

Do not encode CloudPayments-specific partial-cancel semantics into the canonical Application transition contract. If retained CloudPayments accepts a provider-protocol cancel amount that is less than the Order amount, that compatibility validation remains in Integration. It may normalize the fact to the already-correlated canonical Payment amount/currency before delegation, but it must not create a partial-cancel commercial meaning or mutate the canonical Payment amount.

Refund amounts remain independently variable and are governed by the Refund contract below.

## Payment state policy

### New distinct external Payment ID

A new external Payment ID represents a distinct attempt even when the Order is already terminal.

Preserve characterized behavior including:

- failed attempt followed by a different successful attempt;
- multiple authorized attempts;
- a second successful charge on an already-paid Order;
- a late distinct successful charge after Order cancellation.

The Payment projection is recorded, but a terminal Order is never reopened/downgraded.

### Same external Payment ID

Supported progression:

```text
CREATED -> AUTHORIZED
CREATED -> SUCCEEDED
CREATED -> FAILED
CREATED -> CANCELED

AUTHORIZED -> SUCCEEDED
AUTHORIZED -> FAILED
AUTHORIZED -> CANCELED
```

Exact replay returns `DUPLICATE` and must not rewrite confirmed timestamps/fields.

For an existing Payment in:

```text
SUCCEEDED
PARTIALLY_REFUNDED
REFUNDED
```

late weaker facts never downgrade it; classify them as exact `DUPLICATE` or safe `IGNORED` according to the locked semantics.

For existing `CANCELED`:

- equivalent cancellation is duplicate;
- safely stale weaker evidence may be ignored;
- same-ID contradictory success is `CONFLICT`.

For existing `FAILED`:

- equivalent failure is duplicate;
- another outcome for the same external Payment identity is `CONFLICT`.

Persisted states whose transition meaning is not demonstrated by current behavior, such as `CAPTURED` / `DISPUTED`, must fail closed as `CONFLICT`; do not invent policy.

## Payment / Order timestamp semantics

Occurrence timestamps are explicit and timezone-aware.

For a **newly applied** Payment outcome:

```text
AUTHORIZED:
    payment.authorized_at = payment.authorized_at or occurred_at

SUCCEEDED:
    payment.authorized_at = payment.authorized_at or occurred_at
    payment.captured_at = payment.captured_at or occurred_at

FAILED:
    payment.failed_at = payment.failed_at or occurred_at

CANCELED:
    no Payment canceled_at column exists; status is canonical
```

Coupled Order first-confirmation timestamps:

```text
SUCCEEDED -> PAID:
    order.paid_at = order.paid_at or occurred_at
    order.failed_at = None

FAILED -> PAYMENT_FAILED:
    order.failed_at = order.failed_at or occurred_at

CANCELED -> CANCELED:
    order.canceled_at = order.canceled_at or occurred_at
```

Duplicate/stale facts must not rewrite first-confirmation timestamps.

If a retained provider source does not expose a trustworthy typed provider occurrence timestamp, its normalization layer may use the current processing time, preserving existing behavior. Do not invent a timestamp from unsafe/raw payload text solely to satisfy the Application contract.

## Order state policy for Payment outcomes

Only payable Orders:

```text
PENDING_PAYMENT
PAYMENT_FAILED
```

may be advanced by a Payment outcome:

```text
SUCCEEDED  -> PAID
FAILED     -> PAYMENT_FAILED
CANCELED   -> CANCELED
AUTHORIZED -> no Order state change
```

Terminal Orders:

```text
PAID
CANCELED
PARTIALLY_REFUNDED
REFUNDED
```

may still acquire a distinct legitimate Payment attempt, but are not reopened or downgraded.

Other states:

```text
CREATED
REQUIRES_CONSENTS
EXPIRED
REGION_MISMATCH
```

are not silently converted by Step 8. A fact that would require such an undefined transition returns `CONFLICT`.

`Order.expires_at` being in the past does not by itself reject an authoritative late Payment fact when the persisted Order itself has not transitioned to `EXPIRED`.

## `Payment.raw_summary` decision

Provider-specific `Payment.raw_summary` must not become an Application command dictionary or a hidden vendor payload channel.

ANY-493 therefore establishes:

- existing historical `raw_summary` values remain untouched;
- new canonical Application transitions do not accept arbitrary provider summary dictionaries;
- provider-specific durable evidence remains in the retained durable webhook inbox;
- structured canonical information that matters for the Payment projection is carried through explicit typed fields (`provider_invoice_id`, failure code/message, payment method type, etc.);
- new Payment rows may retain the model default `{}` for `raw_summary` unless a future separately approved provider-neutral contract gives this field a stable meaning.

This is an intentional, documented removal of integration-shaped summary mutation from the canonical commercial path, not an accidental behavior change.

---

# Refund Contract

## Refund identity and correlation

An authoritative successful Refund fact identifies:

- local `order_id`;
- provider namespace;
- local provider-account ID;
- target opaque `provider_payment_id`;
- non-empty opaque `provider_refund_id`;
- positive refund amount;
- currency;
- timezone-aware occurrence timestamp;
- optional safe reason.

Application resolves/locks the real Payment and validates:

```text
Refund -> Payment -> Order correlation
provider account
provider namespace
tenant
region
external Payment identity
currency
refund amount
```

## Refund replay ordering

Duplicate/conflict classification must happen before current-state refundability checks can incorrectly reject a valid replay.

Canonical order:

```text
1. lock Order
2. resolve/lock target Payment
3. resolve existing Refund by (provider_account_id, provider_refund_id)
4. if Refund already exists:
       compare immutable correlation/financial identity
       exact match      -> DUPLICATE
       contradiction    -> CONFLICT
       return without incrementing totals
5. only for a new Refund identity:
       validate target Payment is currently refundable
       validate remaining refundable amount
       insert/apply Refund
```

This prevents a replay of an already full Refund from being misclassified as `payment_not_refundable` or over-refund merely because the Payment is now `REFUNDED`.

## Refund state policy

Current Step-8 input is a confirmed successful Refund fact.

Do not introduce a new local `RefundStatus.REQUESTED` command workflow.

For a new Refund identity:

1. create exactly one `Refund(status=SUCCEEDED)`;
2. set `requested_at = occurred_at` and `succeeded_at = occurred_at` because Step 8 is projecting an already-confirmed external success and has no separate local request phase;
3. increment `Payment.refunded_amount_minor` exactly once;
4. set Payment to `PARTIALLY_REFUNDED` or `REFUNDED`;
5. recompute aggregate Order refund state where applicable.

A **new** Refund is applicable only to Payment currently in:

```text
SUCCEEDED
PARTIALLY_REFUNDED
```

The total may never exceed `Payment.amount_minor`.

## Aggregate Order refund semantics

Captured Payment projections considered in aggregate accounting:

```text
SUCCEEDED
PARTIALLY_REFUNDED
REFUNDED
```

For Order currently:

```text
PAID
PARTIALLY_REFUNDED
```

derive:

```text
total refunded < captured total  -> PARTIALLY_REFUNDED
total refunded >= captured total -> REFUNDED
```

Never downgrade an already `REFUNDED` Order.

A `CANCELED` Order remains `CANCELED` when a late distinct successful Payment is later refunded.

Do not query Subscription/Entitlement to decide commercial refund state.

---

# Locking, Uniqueness, and Race Recovery

Canonical lock direction:

```text
Order
    -> Payment
    -> Refund
```

Application locks the Order before deciding a commercial mutation.

Same-Order concurrent transitions therefore serialize on the Order row.

Existing unique indexes remain the final invariant for cross-Order races on external Payment/Refund identity.

Use a narrowly focused persistence helper only for expected unique-insert races.

The helper must:

1. establish/claim a new external Payment/Refund identity before Application performs related canonical commercial mutations for that logical transition;
2. ensure there are no pending Order/Payment/Refund commercial changes from that logical transition before entering the targeted `begin_nested()` identity-insert savepoint, because pending Session state may be flushed before the SAVEPOINT is established;
3. execute the candidate identity `add()` / `flush()` inside the targeted `begin_nested()` savepoint;
4. recover only when the `IntegrityError` can be attributed to the known Payment or Refund external-identity unique index/constraint;
5. re-raise unrelated `IntegrityError` instead of treating every integrity failure as idempotency;
6. reload the winning row after the savepoint rolls back;
7. return storage evidence to Application;
8. leave duplicate/conflict business classification to Application;
9. only after identity establishment/recovery, let Application apply the corresponding Payment/Refund/Order commercial mutations and final outer-transaction `flush()`;
10. never commit or roll back the outer caller-owned business transaction.

Known storage identities:

```text
Payment: (provider_account_id, provider_payment_id)
Refund:  (provider_account_id, provider_refund_id)
```

Do not add a generic retry loop, advisory lock, distributed lock, or migration.

---

# Step 1 — Establish the Canonical Commercial Application Boundary

**Status:** `todo`

## Goal

Implement Payment **and** Refund transitions together as one coherent Application-owned commercial boundary.

Payment and Refund are intentionally one implementation step because they share:

- the same Application ownership boundary;
- the same Order-first locking model;
- the same external-identity race-recovery mechanism;
- the same typed result/disposition contract;
- the same canonical ORM projections;
- the same focused unit/regression test surface.

Keeping them together avoids two small overlapping diffs while still producing one reviewable architectural unit before any Integration rewiring begins.

## Scope / affected code

Primary:

- `apps/api/app/domains/billing/service/commercial_transitions.py` — new;
- `apps/api/app/infrastructure/queries/orders.py`;
- `apps/api/app/infrastructure/queries/payments.py`;
- `apps/api/app/infrastructure/persistence/commercial.py` — new focused storage helper;
- `apps/api/tests/test_commercial_transitions.py` — new.

Do not change CloudPayments callers in this step.

## Implementation decisions

1. Define typed Pydantic Application commands/results in `commercial_transitions.py`.
2. Use `extra="forbid"` and timezone-aware occurrence validation consistent with existing lifecycle commands.
3. Define Application-local Payment outcomes:
   - `authorized`;
   - `succeeded`;
   - `failed`;
   - `canceled`.
4. Define transition dispositions:
   - `applied`;
   - `duplicate`;
   - `ignored`;
   - `conflict`.
5. Implement one Payment transition using the complete Payment/Order semantics defined above.
6. Implement one successful Refund transition using the complete Refund/aggregate semantics defined above.
7. Lock Order before Payment/Refund mutation.
8. Validate local provider account / tenant / region / provider namespace / financial correlation before mutation.
9. New Payment rows derive tenant, region, provider, provider account, and Order linkage from locked local state rather than trusting repeated caller values.
10. Do not accept arbitrary provider dictionaries.
11. Do not populate/update provider-specific `Payment.raw_summary` from Application.
12. Implement first-confirmation timestamp semantics exactly as defined above.
13. For a confirmed Refund projection, use `requested_at = succeeded_at = occurred_at`.
14. Existing Refund identity must be classified duplicate/conflict **before** checking whether current Payment state remains refundable.
15. Add targeted Payment/Refund unique-insert race recovery in the focused persistence helper.
16. For a new external identity, establish/claim that identity inside the targeted savepoint **before** applying related Order/Payment/Refund commercial mutations. Do not leave pending commercial mutations from this logical transition in the Session before entering `begin_nested()`.
17. The savepoint must contain the candidate identity `add()` / `flush()` and recover only the expected external-identity uniqueness violation.
18. After identity establishment/recovery, apply the canonical commercial mutation and final `flush()` in the caller-owned outer transaction.
19. Do not call subscription lifecycle.
20. Flush only; caller owns outer commit/rollback.
21. No schema change.

## Required focused tests

Cover at least:

### Payment

- new `AUTHORIZED`, `SUCCEEDED`, `FAILED`, `CANCELED` facts;
- `AUTHORIZED -> SUCCEEDED/FAILED/CANCELED`;
- exact replay;
- first-confirmation timestamps;
- amount/currency/provider/provider-account/order correlation conflict;
- new Payment amount/currency must match Order commercial amount/currency;
- existing Payment amount/currency cannot be rewritten by a later fact;
- retained provider partial-cancel compatibility does not create canonical partial-cancel Payment semantics;
- same external Payment ID contradictory outcome;
- stale weaker facts cannot downgrade success/refund;
- failed attempt followed by distinct Payment identity;
- second successful distinct Payment identity on already-paid Order;
- late successful distinct Payment after canceled Order without reopening it;
- elapsed `expires_at` does not by itself reject authoritative late fact;
- persisted `EXPIRED`/unsupported Order state fails closed;
- unsupported Payment states fail closed;
- `raw_summary` is not populated through provider dictionaries.

### Refund

- new partial Refund;
- full Refund;
- multiple partial Refunds;
- multiple successful Payments and aggregate Order refund state;
- exact Refund replay after Payment already became `REFUNDED`;
- same Refund identity with contradictory correlation;
- over-refund;
- non-refundable Payment for a **new** Refund identity;
- canceled Order preservation;
- already-refunded Order monotonicity;
- `requested_at` / `succeeded_at` occurrence semantics;
- no subscription/entitlement dependency.

## Invariants

- Application owns all supported local Order/Payment/Refund transition decisions.
- Same logical commercial identity is replay-safe.
- Distinct Payment IDs remain distinct attempts.
- Same external identity cannot silently move across incompatible financial semantics.
- Refund amount is applied exactly once.
- Terminal Orders are not reopened.
- Payment + coupled Order effects are atomic in the caller transaction.
- Refund + Payment totals + Order aggregate effects are atomic in the caller transaction.
- No network I/O.
- No top-level commit/rollback.
- No migration.

## Out of scope

- CloudPayments rewiring;
- Subscription/Entitlement redesign;
- checkout Order creation;
- durable webhook event policy;
- external billing;
- reconciliation;
- public API changes;
- broad persistence cleanup.

## AI prompt

Implement only Step 1 of ANY-493: establish the canonical Application-owned commercial transition boundary for both Payment and Refund outcomes.

The ANY-493 branch is intentionally inherited from the reviewed ANY-490 / PR #103 branch. Do not wait for ANY-490 to merge and do not redo Step-7 Presentation/DI work.

Work only in the directly relevant current files:

- `apps/api/app/domains/billing/service/commercial_transitions.py`
- `apps/api/app/infrastructure/queries/orders.py`
- `apps/api/app/infrastructure/queries/payments.py`
- `apps/api/app/infrastructure/persistence/commercial.py`
- `apps/api/tests/test_commercial_transitions.py`

Create transport-neutral/provider-neutral Pydantic command/result contracts with `extra="forbid"` and timezone-aware occurrence validation.

Define an Application-local Payment outcome vocabulary containing only `authorized`, `succeeded`, `failed`, and `canceled`, plus transition dispositions `applied`, `duplicate`, `ignored`, and `conflict`.

The Payment command must carry local Order ID, provider namespace, local provider-account ID, opaque external Payment ID, optional external invoice ID, amount in minor units, currency, outcome, occurrence time, and only narrow structured safe Payment fields. Do not include email, AccountId, webhook endpoint names, raw provider statuses, signatures, raw payloads, or arbitrary dictionaries.

For a new Payment identity, require `amount_minor == Order.amount_minor` and matching currency. For an existing Payment identity, require incoming amount/currency to match the persisted Payment; mismatch is `CONFLICT`. Do not invent partial-cancel semantics in Application. Any retained CloudPayments partial-cancel protocol compatibility remains Integration-only and must normalize to the existing canonical Payment amount/currency before delegation.

The Refund command must carry local Order ID, provider namespace, local provider-account ID, target opaque external Payment ID, opaque external Refund ID, positive amount in minor units, currency, timezone-aware occurrence time, and optional safe reason.

Lock Order first. Resolve and lock Payment/Refund state only after the Order lock. Revalidate local provider-account, tenant, region, provider namespace, financial values, and external identities before mutation.

Implement the Payment state policy from this plan:

- a new external Payment ID is a distinct attempt;
- `CREATED -> AUTHORIZED|SUCCEEDED|FAILED|CANCELED`;
- `AUTHORIZED -> SUCCEEDED|FAILED|CANCELED`;
- exact replay is duplicate;
- success/refund cannot be downgraded by late weaker facts;
- same-ID canceled -> succeeded is conflict;
- same-ID failed -> different outcome is conflict;
- undefined persisted-state transitions fail closed.

For payable Orders (`PENDING_PAYMENT`, `PAYMENT_FAILED`): succeeded -> paid, failed -> payment_failed, canceled -> canceled, authorized -> no Order state change. Terminal Orders may receive a distinct Payment attempt but are not reopened/downgraded. Do not reject an authoritative fact only because `expires_at` is in the past.

Use first-confirmation timestamp semantics:

- authorized sets `authorized_at` once;
- succeeded sets `authorized_at` if absent and `captured_at` once;
- failed sets `failed_at` once;
- Order paid/failed/canceled timestamps are first-confirmation timestamps;
- duplicates/stale facts do not rewrite them.

Do not accept or populate provider-specific `Payment.raw_summary`; existing historical values are left untouched and new rows may keep `{}`. Use explicit canonical fields only.

Implement Refund replay in this order: lock Order -> lock Payment -> resolve existing Refund identity -> classify exact existing Refund as duplicate or contradictory existing Refund as conflict -> only for a new Refund validate current refundability/remaining amount -> insert/apply.

For a new confirmed Refund create `Refund(status=SUCCEEDED)` with `requested_at = occurred_at` and `succeeded_at = occurred_at`, increment refunded amount exactly once, update Payment to partial/full refunded, and recompute Order aggregate across `SUCCEEDED/PARTIALLY_REFUNDED/REFUNDED` Payments. Preserve canceled Order and already-refunded Order semantics.

Add a focused storage helper for Payment/Refund external-identity insert races. For a new external identity, establish/claim the identity before applying related canonical Order/Payment/Refund mutations. Do not leave pending commercial mutations from this logical transition in the Session before entering `begin_nested()`, because pending state may be flushed before the SAVEPOINT is established. Candidate identity insert/flush must happen inside `begin_nested()`. Recover only the expected known unique identity violation; re-raise unrelated IntegrityError. Reload the winning row and let Application classify duplicate/conflict. Only after identity establishment/recovery should Application apply the corresponding commercial mutation and final outer-transaction flush. Never commit/rollback the outer transaction.

Do not query/mutate Subscription or Entitlement. Do not change CloudPayments yet.

Implement only this step. Inspect directly relevant files as necessary, but do not restart broad repository research or redesign predecessor architecture. Do not perform unrelated refactoring or future steps.

Do not run tests, linters, formatters, type checkers, generators, stage files, or create commits.

After implementation:

1. report changed files;
2. summarize Payment transition semantics;
3. summarize Refund/aggregate semantics;
4. report exact manual verification commands.

If current code materially contradicts a required plan assumption, stop and report the contradiction instead of inventing a new architecture.

## Manual verification

```bash
pytest apps/api/tests/test_commercial_transitions.py -q
```

## Expected completion

- Payment and Refund facts can be applied directly without CloudPayments.
- One Application module owns supported Order/Payment/Refund commercial state policy.
- Focused tests characterize replay, conflict, stale, terminal, timestamp, correlation, aggregate-refund, and race-helper behavior.
- CloudPayments remains unchanged.

## Proposed commit

`refactor(billing): centralize commercial transitions`

---

# Step 2 — Route Retained CloudPayments Through Application Transitions

**Status:** `todo`

## Goal

Remove retained CloudPayments as a competing local Order/Payment/Refund state machine while preserving provider protocol behavior, durable inbox semantics, deactivation, and the existing Step-9 compatibility handoff.

## Scope / affected code

Primarily:

- `apps/api/app/integrations/cloudpayments/processing.py`;
- `apps/api/app/integrations/cloudpayments/processing_support.py`;
- `apps/api/app/integrations/cloudpayments/validation.py`;
- `apps/api/app/integrations/cloudpayments/refunds.py`;
- directly affected retained tests:
  - `apps/api/tests/test_api.py`;
  - `apps/api/tests/test_cloudpayments_adapter_api.py`;
  - `apps/api/tests/test_cloudpayments_deactivation.py`;
  - `apps/api/tests/test_cloudpayments_webhook_postgres.py` only where existing hooks refer to removed mutation helpers.

## Implementation decisions

1. Delete integration-owned `upsert_payment_from_webhook()` commercial mutation policy.
2. Delete integration-owned `record_refund()` and aggregate refund state mutation.
3. Move Payment/Refund state validation out of `validation.py` when it represents canonical local commercial state. Keep request/provider/account/schema validation that genuinely belongs to Integration.
4. Preserve CloudPayments `AccountId`/email checking only as retained provider-protocol validation. Never pass email to Application.
5. Keep `check` webhook read-only and provider-specific.
6. Keep `recurrent` out of Step 8.
7. Map normalized provider facts:
   - authorized Pay -> Application `AUTHORIZED`;
   - successful Pay/Confirm -> `SUCCEEDED`;
   - Fail -> `FAILED`;
   - Cancel -> `CANCELED`;
   - confirmed Refund -> Application Refund transition.
8. Retained Integration may resolve a candidate Order from provider invoice correlation, but Application performs the authoritative lock/revalidation before mutation.
9. `provider_account_id` passed to Application is local correlation context derived from the correlated Order/inbox; do not pretend it is an external CloudPayments identifier.
10. CloudPayments may normalize omitted currency from already correlated local state only where the retained protocol characterization already permits this.
11. If CloudPayments lacks a trustworthy typed occurrence timestamp, use processing time rather than inventing parsing of arbitrary provider timestamp payload fields.
12. Keep durable inbox pre-processing commit unchanged.
13. Keep webhook delivery idempotency unchanged.
14. Do **not** mechanically map Application `DUPLICATE` to `PaymentWebhookEventStatus.DUPLICATE`.
15. Preserve the distinction:
    - inbox/delivery duplicate -> `PaymentWebhookEventStatus.DUPLICATE`;
    - fresh event + already-applied commercial identity -> acknowledged non-mutating processing according to retained endpoint characterization (`PROCESSED` or `IGNORED` as current behavior requires).
16. Application `CONFLICT` becomes durable failed normalized processing with a safe internal reason code; it is not an unexpected 500.
17. Preserve non-`check` CloudPayments provider acknowledgement behavior.
18. Preserve terminal/stale characterization unless the explicit same-identity conflict policy intentionally distinguishes contradictory facts.
19. Call `activate_paid_period()` only when `order_became_paid=True` from a newly applied commercial transition.
20. Do not call paid activation for a late second success against an already terminal Order.
21. Call existing downstream `apply_refund()` only when `refund_created=True` and the existing compatibility gate says downstream subscription handling applies.
22. Never invoke downstream lifecycle for a commercial replay.
23. Keep commercial transition + downstream compatibility handoff in the same normalized processing transaction so downstream failure rolls back commercial mutation.
24. Keep the raw inbox durable because it was committed earlier.
25. Keep outbound `refund_payment()` network command separate and non-authoritative for local Refund success.
26. Keep server-side transaction lookup read-only.
27. Keep normal runtime CloudPayments-free.
28. Remove provider-specific Payment `raw_summary` mutation from retained processing; durable provider evidence remains in `PaymentWebhookEvent`, while canonical Payment fields are populated by typed Application commands.

## Required retained behavior

Preserve characterization for at least:

- amount/currency/schema mismatch;
- failed attempt then distinct successful attempt;
- multiple authorized/successful attempts;
- late distinct success on already-paid Order;
- late distinct success after cancellation without reopening Order;
- late failure cannot downgrade confirmed success;
- same-identity stale/terminal semantics;
- partial/full refunds;
- duplicate Refund identity without double accounting;
- excessive refund rejection;
- duplicate webhook delivery;
- distinct provider event carrying an already-applied commercial identity;
- full refund after historical subscription expiration/cancellation compatibility;
- durable inbox recovery after normalized-processing failure;
- normal runtime exposes no CloudPayments surface.

## Invariants

- Integration owns provider protocol; Application owns local commercial state.
- Raw vendor statuses/payloads never enter Application contracts.
- Inbox duplicate and commercial duplicate remain separate concepts.
- A second successful Payment attempt cannot duplicate paid-period activation.
- A repeated Refund cannot duplicate downstream refund effects.
- Downstream failure rolls back commercial mutation but not the earlier durable inbox receipt.
- No provider network call moves inside the commercial transaction.
- CloudPayments remains deactivated from normal runtime.

## Out of scope

- removing all retained CloudPayments code;
- frontend changes;
- enabling CloudPayments;
- recurrent/subscription redesign;
- reconciliation scheduling;
- future external billing.

## AI prompt

Implement only Step 2 of ANY-493: route retained CloudPayments commercial outcomes through the canonical Application transitions completed in Step 1.

The ANY-493 branch intentionally inherits from the reviewed ANY-490 baseline. Do not wait for ANY-490 merge approval. Step 1 is assumed complete and accepted.

Work primarily in:

- `apps/api/app/integrations/cloudpayments/processing.py`
- `apps/api/app/integrations/cloudpayments/processing_support.py`
- `apps/api/app/integrations/cloudpayments/validation.py`
- `apps/api/app/integrations/cloudpayments/refunds.py`
- directly affected retained CloudPayments tests.

Remove the integration-owned Order/Payment/Refund state machines. `processing.py` must no longer directly decide canonical Payment/Order transitions. Remove `upsert_payment_from_webhook()` mutation ownership. Remove `record_refund()` and integration-owned refunded-total / aggregate Order-refund mutation.

Keep CloudPayments responsible for authentication/HMAC, decoding, redaction, provider-specific schema/account validation, response codes, durable webhook receipt/idempotency semantics, and mapping provider vocabulary into provider-neutral Application commands.

Map authorized Pay -> `AUTHORIZED`, successful Pay/Confirm -> `SUCCEEDED`, Fail -> `FAILED`, Cancel -> `CANCELED`, and successful Refund -> the Application Refund transition.

Do not pass raw payloads, AccountId/email, CloudPayments status strings, endpoint names, HMAC data, or arbitrary dictionaries into Application.

The local provider-account ID passed to Application is correlation context derived from the local Order/durable inbox, not an external CloudPayments identity. Application still reloads and validates the account/Order relationship.

If the retained webhook does not expose a trustworthy typed provider occurrence timestamp, use current processing time, preserving existing behavior.

Preserve the durable inbox phase exactly. Do not change the router's pre-processing commit.

Keep webhook-delivery duplicate semantics separate from Application commercial duplicate semantics. `PaymentWebhookEventStatus.DUPLICATE` is reserved only for durable-inbox delivery/idempotency duplicate detection before commercial processing.

Use this exact mapping for a fresh event that reaches Application:

- Application `APPLIED` -> inbox `PROCESSED`;
- Application commercial `DUPLICATE` -> inbox `PROCESSED`, with no commercial mutation and no downstream Step-9 effect;
- Application `IGNORED` -> inbox `IGNORED`;
- Application `CONFLICT` -> inbox `FAILED` with a safe internal code.

Do not mark a fresh verified delivery as inbox `DUPLICATE` merely because its commercial identity was already applied. Do not turn an expected commercial conflict into an unexpected 500.

Only call `activate_paid_period()` when the Payment result says `order_became_paid=True`. Only call existing `apply_refund()` downstream compatibility handling when the Refund result says `refund_created=True` and the existing compatibility gate applies. Do not invoke downstream lifecycle on commercial replay.

Keep commercial mutation and downstream compatibility handling in the same normalized caller-owned transaction. If downstream handling fails, rollback normalized commercial work while the previously committed raw inbox remains durable.

Stop writing provider-specific `Payment.raw_summary`; preserve provider evidence in the durable webhook event and use explicit canonical Payment fields.

Keep outbound `refund_payment()` and server-side lookup separate/non-authoritative. Preserve `/api/cloudpayments` deactivation from normal application composition.

Update retained characterization tests without redesigning Step 9 or future billing.

Do not run tests, linters, formatters, type checkers, generators, stage files, or create commits.

After implementation:

1. report changed files;
2. summarize commercial decisions removed from CloudPayments;
3. summarize inbox duplicate vs commercial duplicate handling;
4. summarize Step-8 -> Step-9 compatibility handoff;
5. report exact manual verification commands.

If current code materially contradicts the plan, stop and report the contradiction instead of inventing a new architecture.

## Manual verification

```bash
pytest apps/api/tests/test_cloudpayments_adapter_api.py apps/api/tests/test_cloudpayments_deactivation.py -q
pytest apps/api/tests/test_api.py -k "webhook or late_pay or late_confirm or late_fail or refund" -q
```

## Expected completion

- CloudPayments no longer owns Payment/Refund mutation policy.
- Retained provider behavior delegates through canonical Application transitions.
- Inbox/delivery idempotency remains separate from commercial replay semantics.
- Subscription/Entitlement remains only a downstream compatibility consumer.
- Normal runtime remains CloudPayments-free.

## Proposed commit

`refactor(cloudpayments): delegate commercial transitions`

---

# Step 3 — Prove Commercial Concurrency and Atomicity on PostgreSQL

**Status:** `todo`

## Goal

Prove the Step-1 transaction/uniqueness design under real PostgreSQL concurrency and prove that the Step-2 retained webhook path still preserves durable atomic behavior.

## Scope / affected code

Primarily:

- `apps/api/tests/test_commercial_transitions_postgres.py` — new;
- existing shared PostgreSQL fixtures/factories only where directly required;
- `apps/api/tests/test_cloudpayments_webhook_postgres.py` only where Step 2 changed existing hooks/helpers.

This step is intentionally test-focused and should not redesign production code.

## Required concurrency coverage

1. **Same Order + same Payment fact concurrently**
   - one Payment row;
   - one effective Order transition;
   - one operation applies and the other resolves harmlessly;
   - first-confirmation timestamps stay stable.

2. **Different Orders racing for the same external Payment identity**
   - existing unique index selects one persisted identity;
   - losing operation recovers from the expected targeted unique conflict;
   - losing operation returns business `CONFLICT`;
   - losing Order/Payment commercial state is not partially mutated by pre-SAVEPOINT flush;
   - outer transaction remains usable;
   - no second Payment row.

3. **Same Refund identity concurrently**
   - one Refund row;
   - refunded amount incremented once;
   - correct Payment/Order state;
   - replay remains duplicate even if the winner made Payment fully refunded.

4. **Two distinct partial Refunds concurrently against the same Payment**
   - Order lock serializes aggregate accounting;
   - if both fit, exact combined amount persists;
   - if the combined amount exceeds remaining refundable amount, only valid transition(s) apply;
   - no over-refund/lost update.

5. **Same external Refund identity racing across different Payments/Orders**
   - one identity wins;
   - loser returns conflict;
   - losing Payment/Order/refund-accounting state is not partially mutated by pre-SAVEPOINT flush;
   - no double accounting;
   - outer transaction remains usable.

6. **Caller rollback**
   - failure after Application transition but before outer commit leaves no partial Order/Payment/Refund transition durable.

7. **Retained durable webhook characterization**
   - raw inbox survives normalized-processing failure;
   - normalized commercial changes roll back;
   - webhook-delivery duplicate creates no extra Payment/Refund;
   - fresh delivery of already-applied commercial identity does not double-apply financial effects;
   - historical full-refund regression remains valid.

## Invariants

- Database uniqueness is the final external-identity invariant.
- Application checks are not the only concurrency defense.
- Targeted savepoint recovery does not poison the outer transaction.
- Unrelated integrity failures are not swallowed as idempotency.
- No lost update occurs on refunded totals.
- No partial business transition remains after caller rollback.

## Out of scope

- generic DB retry middleware;
- advisory/distributed locks;
- migration/index changes;
- load/performance testing;
- workers/reconciliation.

## AI prompt

Implement only Step 3 of ANY-493: add focused real-PostgreSQL concurrency and atomicity coverage for the commercial transitions completed in Steps 1-2.

The branch remains inherited from the reviewed ANY-490 baseline. Do not wait for predecessor merge approval. Steps 1-2 are assumed complete and accepted.

Create:

- `apps/api/tests/test_commercial_transitions_postgres.py`

Update `apps/api/tests/test_cloudpayments_webhook_postgres.py` only where Step 2 removed/changed a test hook or helper.

Use the repository's existing PostgreSQL fixtures/database lifecycle. Do not create a second engine/database ownership mechanism.

Add deterministic tests for:

1. concurrent same successful Payment fact on the same Order;
2. different Orders racing for the same `(provider_account_id, provider_payment_id)`;
3. concurrent same Refund identity;
4. distinct concurrent partial Refunds including remaining-amount limit;
5. different commercial contexts racing for the same `(provider_account_id, provider_refund_id)`;
6. rollback after an applied transition before caller commit;
7. retained durable inbox failure/duplicate characterization through the new Application boundary.

Assert persisted row counts, statuses, refunded totals, stable timestamps/correlation where material, and returned transition dispositions.

Prove that the targeted nested-savepoint recovery returns a business conflict/duplicate while leaving the outer Session transaction usable. Also prove unrelated integrity failures are not treated as expected identity races where a focused test can do so without building artificial infrastructure.

This step is test hardening. Do not introduce a new concurrency mechanism unless the tests reveal a concrete contradiction with the approved locking/uniqueness design; if they do, stop and report it.

Do not run tests, linters, formatters, type checkers, generators, stage files, or create commits.

After implementation:

1. report changed test files;
2. summarize each concurrency invariant covered;
3. report exact manual verification commands.

## Manual verification

```bash
make test_db_up
pytest apps/api/tests/test_commercial_transitions_postgres.py apps/api/tests/test_cloudpayments_webhook_postgres.py -q
make test_db_stop
```

## Expected completion

- Payment/Refund replay and cross-context identity races are proven on PostgreSQL.
- Refunded amounts cannot be double-applied or lost under concurrency.
- Expected unique conflicts recover without poisoning the outer transaction.
- Caller rollback is atomic.
- Durable webhook semantics still hold through the Application boundary.

## Proposed commit

`test(billing): cover commercial transition concurrency`

---

# Step 4 — Ratchet Ownership, Document the Contract, and Run Final Verification

**Status:** `todo`

## Goal

Prevent regression of the completed ownership boundary and update authoritative documentation to describe the implemented Step-8 architecture.

## Scope / affected code

Architecture guard:

- `scripts/repo.py`;
- `apps/api/tests/test_architecture.py`.

Documentation:

- `ARCHITECTURE.md`;
- `docs/architecture/billing-authority.md`;
- `docs/architecture/payment-portal-data-model.md`;
- `docs/RELIABILITY.md`.

Do not create another ADR. ADR-0004 / ANY-411 remains authoritative.

## 1. Final predecessor synchronization without blocking implementation

Before Step 4 starts, the developer must manually synchronize the current `ANY-493` branch with the latest reviewed/final `ANY-490` predecessor state using the team's normal Git workflow.

If ANY-490 was merged, synchronize its final predecessor state into ANY-493 and verify that all final predecessor changes are represented in the resulting tree. Do not require identical predecessor commit ancestry or duplicate predecessor commits after a squash/rebase merge.

The execution AI must **not** perform merge/rebase/cherry-pick or other Git-history synchronization itself. After the developer completes synchronization, the AI may inspect the resulting repository state and:

- inspect only directly affected deltas/assumptions;
- avoid repeating broad research;
- continue when the Step-8 assumptions remain valid;
- stop and report the contradiction if a late predecessor change materially invalidates transaction ownership, persistence boundaries, Presentation/Application boundaries, or the implemented commercial transition design.

This is a **manual final consistency gate**, not a prerequisite for Steps 1-3.

## 2. Architecture ratchet

After Integration mutation ownership has actually been removed, add one stable narrow rule:

Under `app.integrations`, direct import/use of canonical commercial mutation vocabulary must not be reintroduced:

```text
Payment
Refund
PaymentStatus
RefundStatus
```

The guard must recognize these symbols from the canonical `app.models` namespace regardless of whether code imports through:

```text
from app.models import Payment
from app.models.commerce import Payment
from app.models.enums import PaymentStatus
```

Do not make the rule dependent on one façade import spelling.

Do not broadly prohibit:

- `Order` (retained check/correlation may legitimately read it);
- `PaymentProviderAccount`;
- `PaymentWebhookEvent`;
- provider-specific contracts.

Do not freeze:

- filename `commercial_transitions.py`;
- concrete function names;
- DTO field names;
- helper signatures;
- fragile AST guesses about every possible assignment.

The ratchet protects the stable ownership invariant: Integration must not regain canonical Payment/Refund state-machine ownership.

Add fixtures proving:

- forbidden canonical commercial mutation imports are rejected through supported canonical module paths;
- allowed retained Order/provider-account/webhook-event dependencies remain allowed.

## 3. Documentation

### `ARCHITECTURE.md`

Document:

- Application commercial transition boundary;
- caller-owned transaction participation;
- Integration normalization vs Application mutation ownership;
- Order-first lock direction;
- durable webhook inbox remains a retained compatibility boundary;
- Step 8 → Step 9 handoff.

### `docs/architecture/billing-authority.md`

Document:

- verified commercial fact -> Application transition;
- `APPLIED / DUPLICATE / IGNORED / CONFLICT`;
- commercial duplicate vs webhook-delivery duplicate;
- no last-write-wins;
- distinct external Payment attempts vs same-identity conflict;
- future reconciliation must use the same transition path;
- provider-account local correlation semantics;
- provider-specific `Payment.raw_summary` is not a canonical Application input.

### `docs/architecture/payment-portal-data-model.md`

Document:

- actual Order/Payment/Refund transition semantics;
- first-confirmation timestamp behavior;
- Refund replay ordering;
- aggregate refund behavior;
- `requested_at = succeeded_at = occurrence` for externally confirmed successful Refund projections in this Step-8 path;
- no schema migration required;
- future external-billing schema adaptation remains deferred.

### `docs/RELIABILITY.md`

Document:

- Order-first locking;
- uniqueness as final external identity invariant;
- candidate insert/flush inside targeted savepoint;
- recover only known identity uniqueness races;
- unrelated IntegrityError is re-raised;
- caller-owned transaction;
- no generic DB retry;
- no network I/O in commercial transition;
- durable inbox then normalized transaction;
- webhook/reconciliation convergence.

Do not document CloudPayments endpoint/status vocabulary as canonical Application semantics.

## Invariants

- Docs describe implemented current state, not speculative target code.
- Guard protects a stable responsibility boundary, not incidental code shape.
- No contradiction with ANY-411 / ANY-455 / ANY-489 / ANY-490.
- CloudPayments remains deactivated.
- No migration/public API change.

## AI prompt

Implement only Step 4 of ANY-493 after the developer has manually synchronized the branch with the latest reviewed/final ANY-490 predecessor state: add a stable architecture ratchet for commercial mutation ownership, update authoritative docs, and prepare final verification.

ANY-493 was intentionally implemented from the reviewed ANY-490 branch without waiting for merge approval. Do not perform merge, rebase, cherry-pick, branch synchronization, staging, or commits. Inspect the already-synchronized repository state only for predecessor deltas that directly affect Step-8 assumptions. Do not restart broad research.

Work only in:

- `scripts/repo.py`
- `apps/api/tests/test_architecture.py`
- `ARCHITECTURE.md`
- `docs/architecture/billing-authority.md`
- `docs/architecture/payment-portal-data-model.md`
- `docs/RELIABILITY.md`

Add a narrow architecture rule preventing `app.integrations` from importing/using canonical Payment/Refund mutation vocabulary (`Payment`, `Refund`, `PaymentStatus`, `RefundStatus`) through canonical `app.models` module paths, including façade and direct submodules. Do not write a check that only recognizes `from app.models import ...`.

Keep `Order`, `PaymentProviderAccount`, `PaymentWebhookEvent`, and provider-specific contracts allowed where currently legitimate.

Do not freeze implementation filenames/functions/signatures and do not attempt broad fragile AST detection of every ORM assignment.

Update docs to describe:

- Application ownership of Order/Payment/Refund commercial transitions;
- typed normalized facts;
- caller-owned transactions;
- Order-first locking;
- targeted savepoints and known uniqueness recovery only;
- exact replay / stale / conflict behavior;
- commercial duplicate vs webhook-delivery duplicate;
- first-confirmation timestamp semantics;
- Refund replay ordering before current-state refundability checks;
- aggregate refund accounting;
- provider-account local correlation semantics;
- provider-specific `Payment.raw_summary` no longer being mutated as canonical Application state;
- future webhook/reconciliation convergence on the same transition path;
- Step-9 downstream Subscription/Entitlement boundary;
- CloudPayments remaining absent from normal runtime;
- no migration/future-vendor schema introduced by ANY-493.

Do not create a new ADR or future-vendor contracts.

Do not run verification commands automatically, do not stage files, and do not create commits.

After implementation:

1. report changed files;
2. summarize architecture ratchet;
3. summarize final documented Step-8 contract;
4. report exact manual verification commands.

If a late predecessor delta materially contradicts this completed design, stop and report the contradiction instead of redesigning it silently.

## Manual verification

```bash
pytest apps/api/tests/test_architecture.py apps/api/tests/test_cloudpayments_deactivation.py -q
npm run architecture:check
npm run docs:check
npm run generate:check
npm run check:fast

make test_db_up
npm run test:api
npm run check
make test_db_stop
```

## Expected completion

ANY-493 is complete when:

- the branch contains the required final predecessor state before final merge;
- one Application-owned commercial boundary owns Payment and Refund transition policy;
- Order effects are part of canonical commercial transitions;
- retained CloudPayments delegates commercial mutation instead of owning a competing state machine;
- webhook-delivery idempotency and commercial replay are explicitly separate;
- timestamps/replay/conflict/late/terminal semantics are explicit;
- provider-specific `raw_summary` mutation is removed from the canonical path;
- targeted race recovery is proven on PostgreSQL;
- Subscription/Entitlement remains a downstream Step-9 concern;
- architecture/docs prevent ownership regression;
- normal runtime remains CloudPayments-free;
- no schema or public API change was introduced.

## Proposed commit

`chore(architecture): guard commercial transition ownership`

---

# Final Plan Validation

## Reviewed predecessor baseline

Covered by the dependency-inheritance strategy and the manual Step-4 predecessor synchronization gate.

Implementation/review/testing may proceed directly from reviewed ANY-490 without waiting for merge approval.

Before Step 4, the developer manually synchronizes the latest/final ANY-490 predecessor state into ANY-493. The execution AI only revalidates affected assumptions after that synchronization and must not modify Git history itself.

## Canonical Application ownership

Covered by Step 1.

Payment and Refund transitions are implemented together because they form one commercial projection boundary and share locking/uniqueness/result semantics.

## Provider neutrality

Covered by Steps 1-2.

Application receives explicit normalized commercial fields only. Provider endpoint/status/payload/email/response semantics remain outside.

## Duplicate / retry safety

Covered by Steps 1-3.

The plan explicitly distinguishes:

- durable webhook-delivery duplicate;
- commercial replay/duplicate;
- distinct external Payment attempt;
- contradictory same-identity conflict.

## Stale / out-of-order / conflicting facts

Covered by Steps 1-2.

No last-write-wins behavior remains in canonical transitions.

## Correlation

Covered by Step 1 and enforced again at the Step-2 handoff.

Order, Payment, Refund, provider account, provider namespace, tenant, region, amounts, currencies, and opaque external identities are revalidated before mutation.

## Timestamp semantics

Covered explicitly by Step 1 and documented in Step 4.

Duplicates/stale facts do not rewrite confirmed timestamps.

## Transaction / locking / atomicity

Covered by Steps 1 and 3.

Order-first locking, focused nested savepoints, targeted known uniqueness recovery, and caller-owned transactions preserve the ANY-489 contract.

## No network calls in transactions

Preserved by design.

Provider commands and transaction lookup remain outside canonical commercial transitions.

## PostgreSQL concurrency

Covered explicitly by Step 3.

## CloudPayments deactivation

Preserved and regression-tested in Steps 2 and 4.

## Step 8 → Step 9 boundary

Explicit:

```text
verified commercial fact
    -> Order / Payment / Refund Application transition
    -> typed transition result

if newly applicable:
    -> existing Subscription / Entitlement compatibility handoff
```

The commercial transition never owns access policy.

## Step 10 / Step 11 protection

No external-vendor command flow, reconciliation worker, scheduler, cursor, generic operation table, or future-vendor schema is introduced.

## Schema

No demonstrated current Step-8 invariant requires a migration.

Existing unique identities + Order-first locking + targeted savepoint recovery are sufficient for the demonstrated current scope.

## Public API

No active HTTP contract changes are planned.

## Persisted behavior

No schema migration is introduced.

The following persisted/processing semantics change intentionally and are regression-tested:

- historical `Payment.raw_summary` values remain untouched, but new canonical commercial transitions stop populating provider-specific `raw_summary`; provider evidence remains in the durable webhook inbox and narrow canonical Payment fields;
- canonical Payment amount/currency become immutable commercial identity: retained provider-only partial-cancel amounts do not rewrite the canonical Payment amount;
- retained webhook facts that are explicitly contradictory or safely stale may receive the canonical `FAILED` / `IGNORED` processing classification instead of legacy integration-specific `IGNORED` / `PROCESSED` classification.

These are explicit Step-8 behavior decisions, not silent schema/data migrations.

## Architecture guard

A narrow stable ratchet is introduced only after Integration commercial mutation ownership has actually been removed, and it recognizes canonical model symbols across canonical `app.models` module paths rather than one import spelling.

---

# Final Scope Boundary

After ANY-493:

```text
Verified source
    |
    v
Integration / source adapter
    - authenticate
    - validate provider protocol
    - correlate
    - redact
    - normalize
    |
    v
Application commercial transition
    - lock Order first
    - validate local correlation
    - enforce Payment / Refund / coupled Order policy
    - classify applied / duplicate / ignored / conflict
    - recover only targeted identity insert races
    - mutate canonical ORM projections
    - flush
    |
    +----> caller-owned commit / rollback
    |
    +----> existing Step-9 compatibility consumer
              Subscription / Entitlement
```

Future verified webhooks and future reconciliation must converge through the same Application commercial transition instead of creating another local state machine.

That is the intended completion boundary of ANY-493.
