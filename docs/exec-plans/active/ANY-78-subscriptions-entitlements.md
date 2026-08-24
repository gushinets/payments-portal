# ANY-78 - Implement Payment Portal Subscriptions and Entitlements

Status: active
Owner: repository maintainers
Started: 2026-08-24

## Objective

Implement the provider-neutral subscription and entitlement lifecycle that
owns trial and paid access, records auditable state transitions, and gives
ANY-168 a stable domain boundary for CloudPayments recurrent billing.

Paid access must change only from verified provider state. CloudPayments
statuses, DTOs, card tokens, and subscription identifiers must not become
Payment Portal domain identities.

## Verified Baseline

- `subscriptions`, `entitlements`, and `subscription_events` do not exist yet.
- `product_access_states` is the temporary legacy access projection and must not
  be expanded.
- Checkout persists `auto_renew` as metadata, but does not persist explicit
  recurrent-payment consent.
- Verified payment webhooks update orders and payments but deliberately do not
  activate access.
- ANY-169 provides provider-neutral recurring operation contracts and the
  CloudPayments create, update, cancel, and get client operations.
- The currently available `ANY-168` ref points to the same commit as `ANY-169`;
  it contains the provider client and adapter, not the lifecycle integration.
- CloudPayments recurrent plans are created only after an initial payment and
  token issuance. The token is terminal-bound and must remain ephemeral.
- CloudPayments supports `Day`, `Week`, and `Month` recurring intervals with a
  positive numeric period. A yearly domain period is mapped at the provider
  edge to `Month` with period `12`.
- CloudPayments API idempotency through `X-Request-ID` is retained for one hour,
  so durable local operation idempotency remains required.

References:

- https://developers.cloudpayments.ru/#printsip-raboty
- https://developers.cloudpayments.ru/#sozdanie-podpiski-na-rekurrentnye-platezhi
- https://developers.cloudpayments.ru/#platezhi-po-podpiske
- https://developers.cloudpayments.ru/#uvedomleniya

## Non-goals

- Calling CloudPayments recurrent APIs or processing CloudPayments recurrent
  statuses in the billing domain; ANY-168 owns that orchestration.
- Persisting a CloudPayments card token or exposing it through a safe webhook
  payload.
- Implementing the private Platform Kernel access API; ANY-79 owns it.
- Adding a public trial-start endpoint or automatic-renewal cancellation UI.
- Adding or editing customer-facing legal content without explicit legal
  authorization.
- Adding a queue or an in-process FastAPI scheduler.

## Decisions

- Internal subscription statuses are `trialing`, `active`, `past_due`,
  `canceled`, `expired`, `refunded`, and `paused`.
- Entitlement statuses are `active`, `expired`, `revoked`, and `superseded`.
- Renewal modes are `manual` and `automatic`. A manual plan permits only manual
  renewal; an automatic plan lets the customer choose manual or automatic.
- Automatic renewal requires an append-only `DocumentAcceptance` whose
  `acceptance_kind` is `recurring_consent` and whose user, tenant, and region
  match the subscription.
- A requested automatic renewal remains manual until the provider successfully
  creates its recurrent subscription and ANY-168 attaches the provider
  reference through the domain service.
- A customer may use one trial per exact scope, independent of plan version.
- A replacement supersedes only an entitlement for the same exact scope: the
  same product, the same bundle, or all-access. Different scopes may coexist.
- Cancellation stops future renewal while paid access remains valid through the
  current period. A full refund revokes access immediately; a partial refund
  records an event without changing access.
- Expiration is processed by an idempotent one-shot command invoked by an
  external scheduler. Access evaluation always enforces `valid_until` even if
  that command is delayed.

## Progress

- [x] Add the subscription persistence model and forward migration.
  - Add `subscriptions` with UUID identity, tenant, region, user, plan, exact
    scope, domain status, renewal mode, trial/current period timestamps,
    cancellation timestamps, optional provider account/reference, optional
    recurrent-consent acceptance, and mutable record timestamps.
  - Add a partial unique constraint for non-null
    `(provider_account_id, provider_subscription_id)`.
  - Add database constraints for valid scope references and period ordering.
  - Keep provider status out of the table.

- [x] Add entitlements and append-only subscription events.
  - Add `entitlements` linked to subscription, plan, user, scope, validity,
    source (`trial` or `order`), optional source order, and revoke, expire, and
    supersede evidence.
  - Add `subscription_events` with event type, previous and next status,
    occurrence time, local operation idempotency key, optional order, payment,
    refund, and webhook-event references, and redacted metadata.
  - Do not add `updated_at` to `subscription_events`.
  - Define compared state vocabularies as feature-owned `StrEnum` classes while
    retaining `Text` ORM columns.

- [x] Persist recurrent consent at checkout.
  - When `auto_renew=true`, resolve a valid `recurring_consent` acceptance for
    the authenticated user and current contour.
  - Store the selected acceptance reference on checkout/order state so the
    verified payment path uses the exact evidence accepted at checkout.
  - Reject automatic renewal when the plan does not permit it or the acceptance
    is absent, foreign, or for the wrong acceptance kind.
  - Use test fixtures for the legal document; do not add customer legal source
    in this ticket.

- [x] Implement the provider-neutral lifecycle service.
  - Define validated Pydantic commands for starting a trial, activating a paid
    period, enabling automatic renewal, applying a renewal payment or failure,
    applying normalized provider subscription state, requesting cancellation,
    applying a refund, and expiring due subscriptions.
  - `start_trial` creates a `trialing` subscription and active entitlement
    without an order or payment and enforces one trial per exact scope.
  - `activate_paid_period` accepts internal order, payment, and webhook-event
    identifiers and rechecks persisted `paid`/`succeeded` state before granting
    access.
  - A renewal of the same plan and scope extends from
    `max(current_period_end, paid_at)`.
  - A replacement plan for the same scope creates the replacement lifecycle and
    marks the previous entitlement `superseded`.
  - `enable_automatic_renewal` validates consent and attaches the provider
    account/reference atomically only after a successful provider operation.
  - Every transition locks affected rows and writes one event in the same
    transaction. Duplicate operation keys return the existing outcome.

- [ ] Connect verified initial payment and refund outcomes.
  - Stop creating or updating `product_access_states` in checkout.
  - After a verified initial `Pay` or captured `Confirm`, invoke
    `activate_paid_period` with internal identifiers; browser callbacks never
    activate access.
  - After a verified refund is persisted, invoke the domain refund transition.
  - Failed, canceled, malformed, or unverified payments do not create access.
  - Preserve the existing checkout and payment-result response shapes by
    projecting pending state from order/order-item data and paid access from the
    subscription and entitlement records.

- [ ] Provide the stable integration boundary required by ANY-168.
  - Allow ANY-168 to attach an optional provider subscription reference only
    through `enable_automatic_renewal`.
  - Accept normalized renewal success, failure, and recurrent-status commands;
    domain code must not import payment-provider or CloudPayments contracts.
  - Treat `past_due` as a renewal condition without revoking the already paid
    period. Canceled, rejected, or ended provider renewal stops future renewal;
    entitlement validity remains governed by the paid period and refund rules.
  - Keep initial payment access independent from recurrent setup: a failed
    provider create operation leaves paid access active and renewal manual.

- [ ] Replace legacy access persistence safely.
  - Backfill valid active `product_access_states` rows into manual subscriptions,
    entitlements, and `legacy_access_migrated` events.
  - Backfill already elapsed rows as expired and do not migrate pending rows.
  - Abort migration on an ambiguous or unmappable active row rather than
    silently losing access.
  - Drop the legacy table and remove its ORM compatibility export after the
    application reads and writes the new model.

- [ ] Add authenticated account read APIs.
  - Add `GET /api/account/subscriptions` and
    `GET /api/account/subscriptions/{subscription_id}`.
  - Return named Pydantic response models containing internal subscription ID,
    plan, scope, domain status, renewal mode, current period, cancellation
    state, and entitlement validity.
  - Enforce tenant, contour, and authenticated-user ownership.
  - Do not expose provider account/reference, provider status, payment IDs, or
    webhook IDs.

- [ ] Add expiration maintenance.
  - Implement an idempotent batch transition using row locks and
    `FOR UPDATE SKIP LOCKED` on PostgreSQL.
  - Add a one-shot CLI with configurable batch size for an external cron or
    deployment scheduler.
  - Do not run a periodic loop inside FastAPI workers.

- [ ] Update authoritative and generated documentation.
  - Mark subscriptions, entitlements, and subscription events as implemented in
    the normative data-model document.
  - Document the provider-neutral lifecycle and the ANY-168 integration
    boundary without presenting CloudPayments as the only possible provider.
  - Run `npm run generate`; do not hand-edit generated schema files.

## ANY-168 Follow-up Contract

After ANY-78 is merged, ANY-168 can implement the recurrent flow as follows:

1. Receive and verify the initial CloudPayments `Pay` notification.
2. Activate the paid internal period through the ANY-78 lifecycle service.
3. If automatic renewal was requested and consent exists, use the card token
   only inside the verified adapter boundary before redaction.
4. Call the existing provider-neutral `CreateRecurringSubscriptionRequest`.
5. On provider success, call `enable_automatic_renewal` with the provider
   account and subscription reference; on failure, retain manual renewal and
   paid access.
6. Resolve later renewal `Pay` and `Fail` notifications by provider account and
   `SubscriptionId`, then send normalized commands to the lifecycle service.
7. Apply successful update/cancel API results immediately because
   CloudPayments does not send `Recurrent` after `subscriptions/update`.
8. Use `Recurrent` for independently observed provider status changes without
   copying provider status into the domain model.

ANY-168 must extend the current webhook adapter so the verified initial token
can be consumed ephemerally before `_safe_payload` replaces it with
`[redacted]`. The token must never enter `NormalizedPaymentEvent.safe_payload`,
database records, telemetry, exceptions, or logs.

## Validation Plan

- PostgreSQL migration tests cover clean upgrade/downgrade, constraints,
  indexes, active/expired legacy backfill, and ambiguous-backfill rejection.
- Lifecycle tests cover trial creation and reuse rejection, verified and
  unverified initial payment, duplicate delivery, renewal success and failure,
  consent enforcement, provider-reference attachment, cancellation, partial and
  full refund, expiration, replacement, and entitlement changes.
- Integration tests prove that paid access changes only after verified persisted
  payment state and that recurrent setup failure does not revoke paid access.
- API tests cover list/detail ownership, contour isolation, 404 for foreign
  subscriptions, and omission of provider fields from responses and OpenAPI.
- Compatibility tests preserve checkout, session, account, and payment-result
  response behavior after removal of `product_access_states`.
- Run `npm run test:api` and PostgreSQL migration tests while iterating.
- Run `npm run check:fast`, followed by the broadest locally supported
  `npm run check`, and record any skipped PostgreSQL or browser checks.

## Follow-up before completion

- Split `apps/api/app/models.py` into bounded modules so the architecture
  check's file-size limit passes without weakening the guardrail.
- Run `npm run generate` and commit the updated generated database schema
  artifact after all planned ORM changes are complete.
