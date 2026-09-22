# ANY-510 — Stabilize Portal User Identity, Session & Provider-Independent Test Baseline

## Plan Overview

| Field | Value |
| --- | --- |
| Program | `ANY-504` — LBX / External Billing Architecture program |
| Program step | ANY-504 Step 3 — Stabilize Portal User Identity, Session & Provider-Independent Test Baseline |
| Ticket | `ANY-510` |
| Overall status | `todo` |
| Execution order | Sequential only: Implementation Step 1 → manual verification → commit → Implementation Step 2 → ... → Implementation Step 6 |
| Implementation steps / proposed commits | 6 |
| Predecessor | `ANY-509` / PR `#117` |
| Successor | `ANY-504` Step 4 — clean pre-production schema/reset and legacy commerce/CloudPayments removal |

## How to Use This File

1. `ANY-509` is the completed sequential predecessor. PR `#117` is merged; its final head `9830ca104ff5729857322c06c2313afe32849f9a` and merged `docs/architecture/external-billing-persistence-reset.md` are authoritative Step-2 → Step-3 input.
2. This plan was revalidated against that final ANY-509 result on 2026-09-21, including `ANY-509 - Align persistence plan with reviewed invariants` and the reviewed paid-grant provenance predicate described below.
3. Immediately before Implementation Step 1, compare current `main` only for later predecessor corrections merged after PR `#117`. Reconcile only material changes that affect the Step-3 handoff, identity/legal provenance, paid-access scope, or retained/removal decisions. Do not reopen the completed ANY-509 design without a concrete contradiction.
4. Execute one Implementation Step at a time. The implementation model must not implement a later step early.
5. After each Implementation Step, review the diff and run the listed manual verification yourself. The implementation model must not run tests, linters, formatters, migration commands, or other automated checks.
6. If the step passes review and manual checks, create the proposed commit yourself before moving to the next Implementation Step.
7. Implementation Step 6 contains the final ANY-504 Step 3 → Step 4 handoff and complete verification set. Do not perform the destructive ANY-504 Step-4 schema reset in this ticket.

## Authoritative Baseline

Use the following precedence when resolving a conflict:

1. ADR 0005 — `docs/architecture/decisions/0005-external-billing-boundary.md`.
2. Accepted External Billing Boundary Design — `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`.
3. Accepted Portal ↔ Kernel Access Contract Design — `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`.
4. `ANY-504` for implementation sequence and step ownership.
5. Completed/merged `ANY-509` / PR `#117`, especially `docs/architecture/external-billing-persistence-reset.md`, for the Step-2 → Step-3 persistence/reset handoff.
6. `docs/architecture/contours.md`, `ARCHITECTURE.md`, `apps/api/AGENTS.md`, and coding conventions for retained Portal architecture and implementation rules.
7. Current code and regression tests as characterization of retained behavior, but not as authority for target commercial ownership where they conflict with ADR 0005 / accepted designs.

## Research Baseline

The plan is based on the repository state after merged `ANY-509` / PR `#117`, which was documentation-only. Its merged result does not alter runtime models, migrations, API behavior, or tests.

### Relevant delta from the updated `ANY-509` baseline

The final merged `ANY-509` head `9830ca104ff5729857322c06c2313afe32849f9a` tightens several later-step persistence/access invariants. Only the following deltas materially constrain `ANY-510`:

- `billing_customer_key` is globally unique across all retained customer slots, not unique only inside one `external_billing_account_id`. Once allocated, the key is permanently reserved locally and cannot become reusable merely because billing-account configuration changes. `ANY-510` still does not allocate this key; ANY-504 Step 4 owns the global DDL constraint and ANY-504 Step 7 owns allocation/runtime behavior.
- future paid-access writers use the canonical ANY-504 Step-3 `User` row as the stable PostgreSQL serialization anchor for semantic scope `(tenant_id, region, user_id)`. ANY-510 must therefore leave a deterministic canonical user row and a physical scope representation that ANY-504 Step 4 can reuse identically for `paid_access_states`, `access_invalidation_outbox`, and AccessSnapshot serialization.
- **paid product access now has an explicit immutable-provenance gate:** an external subscription may be discovered and reconciled with `purchase_intent_id = NULL`, but it remains commercially ineligible and produces neither a paid product grant nor a purchased allowance until it has a valid linked PurchaseIntent with exact accepted commercial/legal evidence and pinned mapping provenance. Primary selection, provider state, and manual-review resolution cannot bypass this predicate, including for unmetered offers. ANY-510 must leave a legal-evidence contract that makes this predicate structurally possible; it must not implement the later paid-access runtime.
- revision-zero invalidation, allowance clock-skew immutability, metric-local duplicate-allowance handling, and deterministic deadline work were aligned between the ANY-509 handoff and locked implementation plan in `9830ca1`. Their implementation remains owned by ANY-504 Steps 4 and 8–10 and does not add runtime work to ANY-510.

### Current identity/session state

- `users.id` is already a UUID primary key and is the correct canonical Portal user identifier.
- `users` uniqueness is currently `(tenant_id, region, email_normalized)`; email remains an attribute, not a cross-system identity.
- `UserStatus` currently contains only `active`. `ANY-510` has no evidence requiring a new suspended/disabled/deleted state, so no new lifecycle vocabulary is introduced.
- registration and login currently accept client-supplied `tenant_id` and `region` even though the target deployment is one contour per instance.
- the frontend already submits registration/login without `tenant_id` or `region`; removing caller authority therefore does not require a new frontend payload.
- `AuthSession` stores only a SHA-256 token hash, has expiry and `revoked_at`, but normal logout currently deletes the row while password-reset security invalidation marks rows revoked.
- session/user contour consistency is enforced by queries, not structurally by a composite database FK.
- password-reset requests already derive the current scope server-side, avoid account enumeration, persist only a reset-token hash, and rate-limit by scoped account/IP keys.
- known password-reset tokens are currently correlated back to the user by `(tenant_id, region, email_normalized)` rather than directly by canonical `users.id`.
- `MagicLinkToken.entrypoint_session_id` has no active password-reset responsibility and is residual entrypoint coupling.

### Current legal state

- `DocumentVersion` is versioned and active-selection is unique per `(tenant_id, region, doc_type)`, but `seed_legal_documents()` currently rewrites fields of an existing version if the manifest changes under the same version identity.
- `DocumentAcceptance` is intended to be append-only, but the database does not currently provide a structural acceptance-evidence grouping for one complete commercial/legal decision.
- the public acceptance API is authenticated, yet the ORM still permits `user_id=None` plus `guest_id`; there is no current guest-acceptance runtime that justifies keeping guest acceptance in the retained target model.
- current recurring-consent semantics are tied to legacy Portal `Plan.id` / entrypoint metadata. `ANY-509` explicitly states that this is not the target commercial/legal contract.
- registration's `personal_consent` and `offer_consent` booleans currently create no durable `DocumentAcceptance` rows.
- the registration UI's personal-consent checkbox covers the current `privacy` and `pd_consent` documents, and the offer checkbox covers the current `offer` document. `cancellation`, `cookies`, and `security` are not currently acceptance-required; recurring consent remains purchase-specific.

### Current contour/bootstrap state

- `docs/architecture/contours.md` is explicit that one production instance enables exactly one contour.
- the current first migration seeds both `ru` and `eu`, plus DE/ES rules. That is retained bootstrap debt, not the target one-instance invariant.
- `CountryRegionRule.default_payment_provider` and `allow_region_override` are legacy/direct-provider or multi-contour-routing residue and must not become target identity authority.
- physical removal of foreign-contour bootstrap rows and legacy provider columns belongs to ANY-504 Step 4, not `ANY-510`.

### Current `entrypoint_sessions` result

The current `EntrypointSession` is created by legacy checkout and contains Product/Bundle foreign keys and legacy commercial checkout provenance. The identity/auth/password-reset baseline does not require it. `DocumentAcceptance.entrypoint_session_id` and entrypoint fields are used by retained legacy recurring checkout behavior, not by the target legal/commercial evidence contract.

**Locked Step-3 disposition:** `entrypoint_sessions` is **not retained** as a target identity/session/legal table. Step 3 removes identity/recovery dependencies on it and records it for physical removal in ANY-504 Step 4. Legacy checkout may continue to reference it until ANY-504 Step 4 removes the retained checkout implementation.

### Current trial dependency result

No provider-independent identity, session, password-reset, legal-document, or legal-acceptance obligation requires the old Portal `Plan` / `Subscription` / `Entitlement` trial model. `GET /api/auth/session?product=...` and `identity.services.account` still project retained commerce/access state, but that is legacy account presentation owned by ANY-504 Step 4 cleanup, not an identity requirement.

**Locked Step-3 result:** no old Portal trial state is retained on behalf of identity/session/legal.

### Retained public identity/legal contract

ANY-510 must leave the survivor boundary explicit so ANY-504 Step 4 does not have to decide which parts of the current auth surface are identity versus legacy billing presentation:

- retain provider-independent registration, login, logout, password-reset request/confirm, required-legal-document discovery, authenticated legal acceptance, and the core authenticated `/api/auth/session` identity result;
- the retained `/api/auth/session` contract is the authenticated identity/session result (`authenticated` + canonical server-scoped user identity). The optional `product` selector and `product_state` output are legacy billing/account presentation and are removed by ANY-504 Step 4 with `identity.services.account` billing reads;
- public registration/login cannot choose tenant/region; password reset and legal-document discovery are server-scoped; authenticated legal writes derive scope from the authenticated user;
- legacy `/api/auth/checkout-intent`, `/api/auth/payment-status`, Portal catalog/account-subscription contracts, and their frontend consumers are classified for ANY-504 Step-4 removal and are not stabilized as part of ANY-510.

## Locked Architecture Decisions for ANY-510

### Canonical Portal identity

- Canonical customer identity is `users.id` UUID.
- `tenant_id + region + user_id` remains the serialized Portal/Kernel identity scope. On one deployed instance, `tenant_id` and `region` are server/deployment-owned constants for that instance. Step 3 keeps `tenant_id` and `region` explicit on the canonical `User` row rather than collapsing them into deployment-only implicit state.
- Email, normalized email, phone, display/legal name, provider customer IDs, or an external billing `outer_id` are never canonical Portal user identity.
- The existing scoped-email uniqueness remains because the same email in different contours represents different accounts on different isolated data planes. The public API on one instance must no longer allow the caller to select another contour.
- No new non-active `UserStatus` value is introduced in this ticket. Authentication paths are nevertheless made explicitly active-user-only so a later status extension cannot accidentally remain fail-open.

### Canonical-user deletion and non-reuse

- Application code does not hard-delete canonical `User` rows.
- Once identity/legal evidence references a user, database `RESTRICT`/composite FK relationships prevent the evidence from being orphaned by user deletion.
- `users.id` is immutable and never reassigned or reused.
- PII erasure/anonymization is distinct from identity deletion. `ANY-510` does not invent an erasure workflow, retention period, or replacement identifier. Any future PII-erasure workflow must preserve the canonical UUID and legal/commercial referential integrity unless a separately approved retention/legal policy explicitly changes that rule.

### One-contour runtime authority

- Add required deployment settings `INSTANCE_TENANT_ID` and `INSTANCE_REGION` (`Settings.instance_tenant_id` / `Settings.instance_region`).
- local development/test examples use explicit `anytoolai` / `ru` values; production Compose requires explicit values rather than silently selecting a production contour.
- registration, login, password reset, required-document discovery, authenticated sessions, and later legal writes derive scope from these settings or the authenticated user; caller-supplied `tenant_id` / `region` is not data-plane authority.
- existing unknown request/query fields may remain ignored by the current Pydantic/FastAPI boundary where that is the established behavior; the important invariant is that supplied foreign values cannot select foreign data.
- response identity may continue returning `tenant_id` and `region` as descriptive server-derived identity scope.

### Session semantics

- Session secret generation and hashing stay provider-independent: random opaque token, SHA-256 hash at rest, 30-day TTL unless an existing policy changes separately.
- only the token hash is persisted.
- an auth session is valid only when the row exists, is unrevoked, is unexpired, belongs structurally to the same canonical active user/scope, and that user still resolves as active.
- preserve the existing distinction instead of inventing a new retention requirement: **normal user logout deletes that one session row**, while **security-driven invalidation** (currently password reset) sets `revoked_at` on affected active sessions so the security transition is durable.
- first logout succeeds; replay of the deleted bearer token is rejected by ordinary authentication with `invalid_session`/401. A second authenticated logout using that token cannot reach the logout transition because authentication already fails.
- password reset revokes all currently active sessions for the canonical user in the same transaction as password replacement and reset-token consumption.
- no session-retention/pruning period is invented in this ticket. Retention of security-revoked rows remains a separate operational/privacy policy question.

### Password-reset identity semantics

- known-user reset tokens are durably bound to canonical `users.id` in addition to the existing scoped email snapshot used for delivery/abuse protection.
- unknown-email decoy reset tokens keep `user_id=NULL`, preserving indistinguishable external behavior without inventing a fake user.
- reset confirmation resolves a known target by token-bound `user_id` and verifies active user/scope rather than treating mutable email as canonical identity.
- stored token secrets remain hashed; raw reset tokens are never persisted or logged.
- rate limits remain server-scoped and continue to avoid account enumeration.
- `MagicLinkToken.entrypoint_session_id` is removed from the retained identity/recovery shape because password reset has no provider-independent entrypoint-session requirement.

### Relational scope integrity

Where a retained row repeats correctness-critical user or contour scope, application filtering alone is insufficient. Add narrow composite alternate keys and composite FKs consistent with the `ANY-509` strategy:

- `users`: alternate key for `(id, tenant_id, region)`.
- `auth_sessions`: composite FK `(user_id, tenant_id, region)` → `users(id, tenant_id, region)`, `RESTRICT`.
- known-user `magic_link_tokens`: nullable composite FK `(user_id, tenant_id, region)` → `users(...)`, `RESTRICT`; null user remains valid only for the decoy/unknown-email case.
- `legal_entities`: alternate key `(id, tenant_id, region)`.
- `document_versions`: composite FK `(legal_entity_id, tenant_id, region)` → matching legal entity and alternate key `(id, tenant_id, region)`.
- legal acceptance evidence and its `DocumentAcceptance` rows use the same explicit user/contour representation and composite FKs described below.

These alternate keys are relational guards, not new business identities.

For the ANY-504 Step 3 → Step 4 handoff, resolve the delegated paid-access scope representation explicitly: ANY-504 Step 4 must create `paid_access_states` and `access_invalidation_outbox` with non-null `tenant_id`, `region`, and `user_id`, a composite FK to `users(id, tenant_id, region)`, and semantic uniqueness on `(tenant_id, region, user_id)`. AccessSnapshot must serialize the same three-part scope. The canonical `User` row is the future stable `SELECT ... FOR UPDATE` lock anchor for all semantic paid-access writers; `ANY-510` does not implement those writers.

### Versioned legal-document immutability

- an existing `(tenant_id, region, doc_type, version)` is historical identity. Its ID, legal-entity reference, title, URL path, content hash, publication/effective timestamps, and `requires_acceptance` semantics must not be silently rewritten under the same version.
- publishing changed material content requires a new version/document row.
- `is_active` is the intentional lifecycle selector that may change when a newer version becomes current.
- legal seeding must fail closed on a material same-version mismatch instead of mutating historical meaning.

### LegalEntity historical semantics

- `LegalEntity` remains contour-scoped **current operator metadata** and is **not** promoted into a second historical-versioning subsystem in ANY-510.
- historical proof of what the user accepted comes from the immutable `DocumentVersion` identity/content hash plus acceptance evidence that references that exact document version. Historical acceptance readers must not dereference current mutable `LegalEntity` name/address/tax/contact fields to reconstruct or reinterpret old accepted terms.
- `LegalEntity.id` identifies the operator record. Current descriptive/legal-contact metadata may be maintained on that record without rewriting historical document evidence; `status` remains lifecycle metadata. If the legal operator itself is replaced by a different legal person/entity, use a new `LegalEntity` identity and new affected `DocumentVersion` rows rather than repointing an existing historical document.
- `DocumentVersion.legal_entity_id` remains immutable and same-scope. Any change to material accepted text or seller identity represented by the document requires a new `DocumentVersion`.
- `seed_legal_documents()` may maintain current `LegalEntity` metadata, but no seed/application flow may use changed `LegalEntity` metadata to rewrite an existing `DocumentVersion` or claim that its historical content/hash changed.
- ANY-510 therefore does not add speculative `legal_entity_versions`; it makes the boundary explicit: mutable current operator metadata is not historical acceptance authority, while immutable DocumentVersion content/hash is.

### Durable legal/commercial evidence shape

Add one retained legal parent entity named `LegalAcceptanceEvent` (`legal_acceptance_events`) that represents one atomic user acceptance action. It is not a billing table and does not make Portal a commercial authority.

`LegalAcceptanceEvent` target fields:

- `id: UUID` — immutable primary key.
- `tenant_id: text` — immutable.
- `region: text` — immutable.
- `user_id: UUID` — non-null canonical Portal user; composite FK to `users`, `RESTRICT`.
- `external_billing_account_id: text | NULL` — opaque configured billing-boundary ID; no FK/table.
- `billing_offer_id: text | NULL` — opaque external offer identity.
- `accepted_commercial_fingerprint: text | NULL` — exact accepted material commercial fingerprint.
- `accepted_at: timestamptz` — immutable acceptance time.
- `ip` / `user_agent` — nullable ancillary security/audit metadata using the existing storage approach; they are not acceptance identity or commercial authority. Core acceptance facts remain immutable, while any future approved privacy-erasure policy may redact these ancillary values without changing acceptance meaning.
- `created_at` — immutable persistence timestamp.

Commercial binding invariant:

- `external_billing_account_id`, `billing_offer_id`, and `accepted_commercial_fingerprint` are either all NULL for a non-commercial legal action (registration or generic document acceptance) or all non-null/non-empty for a future purchase-bound commercial acceptance.
- no runtime in Step 3 derives these values from `Plan`, email, provider customer state, or arbitrary client metadata.
- ANY-504 Step 7 is responsible for creating a commercial-bound event only after authoritative offer/fingerprint validation.
- a non-commercial event whose commercial triplet is NULL can never satisfy the future PurchaseIntent composite FK and therefore can never be used as the immutable provenance required for paid product access.
- consistent with ANY-509 head `9830ca1`, a later external subscription without a valid linked PurchaseIntent carrying this exact commercial/legal event remains commercially ineligible and contributes neither a paid grant nor an allowance; primary selection or manual review cannot synthesize missing legal provenance.

`DocumentAcceptance` remains the append-only per-document evidence row. Step 3 adds a non-null `legal_acceptance_event_id` and structurally binds each row to the same `(tenant_id, region, user_id)` as its event and to a same-contour `DocumentVersion`.

For Step 3 runtime compatibility, current legacy fields needed only by the soon-to-be-removed checkout flow may remain physically present until ANY-504 Step 4. They are **not** part of the clean retained target shape.

The clean ANY-504 Step-4 retained `DocumentAcceptance` shape is locked as:

- `id`;
- `legal_acceptance_event_id`;
- `tenant_id`;
- `region`;
- `user_id` (non-null);
- `document_version_id`;
- `acceptance_kind`;
- `acceptance_text_hash`;
- `created_at`.

ANY-504 Step 4 removes these legacy-only acceptance columns after the retained checkout/entrypoint implementation is removed:

- `guest_id`;
- `entrypoint_session_id`;
- `entrypoint_type`;
- `entrypoint_value`;
- `source_url`;
- arbitrary `metadata` used for legacy `plan_id` / checkout context;
- duplicated `doc_type` and `version` once all target readers derive them from immutable `DocumentVersion`;
- duplicated per-document `accepted_at`, `ip`, and `user_agent` once the event is the canonical action-level evidence.

The forward Step-3 schema may keep the legacy-only columns temporarily so current checkout characterization remains intact; the Step-3 handoff must make the ANY-504 Step-4 drop list explicit.

Each acceptance event must contain at most one acceptance for a given document version (`UNIQUE(legal_acceptance_event_id, document_version_id)`). Registration and current generic legal writes create the event and its rows in the same Application-owned transaction.

`LegalAcceptanceEvent.accepted_at` is the canonical action timestamp for target reads. The transitional per-document `DocumentAcceptance.accepted_at` may remain until ANY-504 Step 4 only for legacy callers; new Step-3 writes must populate it from the event timestamp rather than independently deriving another time. The clean retained shape drops that duplicate timestamp.

The existing generic `POST /api/legal/acceptances` has no idempotency key. Preserve simple append-only semantics: every successful explicit acceptance call is an independent acceptance action/event; do not invent hidden deduplication or a new idempotency protocol in ANY-510. Query semantics may treat any valid acceptance of the required immutable version/hash as sufficient where the current contract already does so.

For the future ANY-504 Step-4 `purchase_intents` schema, lock the mandatory physical binding as:

- `purchase_intents.legal_acceptance_event_id UUID NOT NULL`;
- composite FK from `(legal_acceptance_event_id, user_id, external_billing_account_id, billing_offer_id, accepted_commercial_fingerprint)` to the corresponding unique alternate key on `legal_acceptance_events`;
- `ON DELETE RESTRICT` / equivalent restrictive behavior.

This lets a purchase reference one immutable acceptance action that belongs to the same canonical user and exact configured billing boundary / offer / commercial fingerprint. It prevents ANY-504 Step 4 from inventing a single generic acceptance UUID, JSON-only acceptance list, or legacy `Plan.id` consent as the purchase's legal evidence.

Completeness of the required legal-document set is a legal/Application invariant: the future commercial acceptance writer must create the commercial event and all required `DocumentAcceptance` rows atomically from the exact validated offer/fingerprint and current required document versions. Step 3 defines the physical contract; ANY-504 Step 7 owns that future runtime writer.

### Acceptance-text integrity across legal surfaces

`DocumentAcceptance.acceptance_text_hash` is durable evidence of the canonical acceptance statement represented by the API/UI action that created the row. It is **not** assumed to have one universal value per `DocumentVersion`.

- the generic authenticated legal-acceptance flow may continue to use the canonical per-document statement returned by the legal API (currently `build_acceptance_text(document)`) and must validate that hash before persistence;
- registration is a distinct acceptance surface: `personal_consent` and `offer_consent` are API-level attestations to fixed canonical registration statements. Step 4 must define those backend-owned canonical statements to match the current registration checkbox meaning and persist hashes of those statements, rather than fabricating the generic hash returned by `build_acceptance_text(document)` for text that was not the registration action;
- the personal-consent statement may back both the exact `privacy` and `pd_consent` DocumentVersion rows accepted by that checkbox; the offer statement backs the exact `offer` DocumentVersion row;
- server-side write paths validate/derive the appropriate canonical statement hash. The browser does not supply arbitrary acceptance text or an authoritative hash;
- target read logic that asks whether an exact immutable DocumentVersion has already been accepted must rely on valid append-only acceptance rows for the exact document version/user/kind and must not recompute one universal generic text hash as if every acceptance surface displayed identical wording; flow-specific validators may still verify the stored hash when validating a particular acceptance action;
- the Step-6 handoff must document the canonical registration statements/hashes actually implemented so Step 4 preserves their evidence semantics.

### Registration legal semantics

The existing public registration booleans are retained as the UI/API expression of the current RU registration action, but they are no longer a parallel source of truth after commit:

- `personal_consent=true` authorizes atomic durable acceptance of the active required `privacy` and `pd_consent` versions that are applicable to registration.
- `offer_consent=true` authorizes atomic durable acceptance of the active required `offer` version.
- `recurring_consent` is purchase-specific and is not silently accepted during registration.
- non-required informational documents are not written as accepted evidence.
- if a future active required non-recurring registration document has no mapping to the registration UI contract, registration fails closed rather than creating a user with incomplete evidence.
- all registration acceptance rows share one non-commercial `LegalAcceptanceEvent` and one acceptance timestamp.
- User, required acceptance event/rows, and initial AuthSession are committed atomically. A failure leaves none durable.
- the existing scoped unique email constraint is the final concurrency guard. Concurrent duplicate registration yields at most one canonical user with one coherent initial legal/session result; the losing operation rolls back completely and reports the existing duplicate-email semantic error.

### External billing identity guard

Step 3 does not create `external_billing_customers`, allocate customer keys, or implement customer binding. It does lock the invariant for later steps:

- no `external_billing_accounts` table/model; `external_billing_account_id` is configuration scope.
- `billing_customer_key` is immutable, opaque, non-PII, globally unique across all retained customer slots, and permanently reserved locally once allocated.
- changing `external_billing_account_id` configuration must never make an already allocated key reusable for another customer slot.
- it may not be derived from email, normalized email, phone, name/legal name, provider customer ID, or mutable provider state.
- allocation/binding remains ANY-504 Step 7; physical `external_billing_customers` and the global `UNIQUE(billing_customer_key)` constraint are ANY-504 Step 4.

## Global Out of Scope

Do not implement any of the following in `ANY-510`:

- destructive clean reset of the pre-production schema or replacement of all old Alembic history;
- removal of Portal-owned Product/Plan/CheckoutSession/Order/Payment/Refund/Subscription/Entitlement tables;
- physical removal of `entrypoint_sessions` or legacy checkout acceptance columns before ANY-504 Step 4 removes their callers;
- physical creation of the 15 target external-billing tables, including `external_billing_customers` and `purchase_intents`;
- any `external_billing_accounts` table;
- `billing_customer_key` allocation or provider binding runtime;
- LBX/provider Phase 0 behavior;
- external catalog/capability mapping;
- PurchaseIntent creation, Widget minting, or customer/agreement/subscription provider commands;
- webhook/reconciliation implementation;
- paid-access projection or Portal ↔ Kernel runtime integration;
- direct-CloudPayments removal itself;
- a new user disabled/suspended/deleted state without a separate explicit requirement;
- PII-erasure workflow or invented retention/deletion schedules;
- unrelated refactoring or package redesign.

---

# Implementation Step 1 — Make tenant and contour scope server-authoritative

**Status:** `todo`

**Goal**  
Remove client authority over Portal tenant/contour selection and establish one explicit deployment-owned identity scope without changing the existing successful auth response shape or pulling ANY-504 Step-4 commerce cleanup into this ticket.

**Scope / affected code**

Primary files:

- `.env.example`
- `.env.production.example`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `scripts/repo.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domains/identity/session.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/domains/legal/router.py`
- `apps/api/tests/support/settings.py`
- focused identity/legal/deployment tests, primarily `apps/api/tests/test_api.py` and `apps/api/tests/test_deployment_contract.py`

No database migration is required in this step.

**Implementation decisions**

1. Add `Settings.instance_tenant_id` and `Settings.instance_region`, sourced from `INSTANCE_TENANT_ID` and `INSTANCE_REGION`.
   - trim and normalize the existing lowercase identity/region vocabulary consistently;
   - reject blank values;
   - do not invent a fallback in production Compose;
   - local/test examples explicitly set `anytoolai` / `ru`;
   - update repository-managed environments in `scripts/repo.py`: generated/OpenAPI import defaults, local runtime `.harness/runtime.env`, direct API/migration environment, and other harness-owned API startup paths must receive explicit local/test `INSTANCE_TENANT_ID=anytoolai` / `INSTANCE_REGION=ru` so required Settings do not break repository tooling. Production values still come from explicit deployment configuration.
2. Keep `app.domains.identity.session.DEFAULT_TENANT_ID` and `DEFAULT_REGION` only as compatibility exports if still needed by current imports, but derive them from `settings.instance_tenant_id` / `settings.instance_region`; they must no longer be hardcoded data-plane selectors.
3. Remove `tenant_id` and `region` as meaningful fields from `RegisterRequest` and `LoginRequest`.
   - routers pass the configured instance scope to `register_user()` / `login_user()`;
   - if old clients include foreign `tenant_id` / `region`, those values must not alter query/write scope. Preserve the repository's current harmless-extra-input behavior unless a directly affected existing contract requires stricter rejection.
4. Password-reset request remains server-scoped but now uses the same configured instance scope rather than hardcoded constants.
5. `GET /api/legal/required-documents` resolves the configured instance tenant/region server-side rather than allowing query parameters to select another contour.
6. Keep authenticated identity responses (`tenant_id`, `region`, `user_id`, `email`) unchanged and server-derived.
7. Replace the old API regression that proves one process can register the same email in both `ru` and `eu` with one-contour regressions:
   - foreign client scope cannot create a foreign-contour user;
   - foreign client scope cannot make login select a foreign-contour user;
   - required-document discovery cannot be switched to `eu` by a query parameter;
   - local scoped-email uniqueness remains unchanged.
8. Do not delete `eu`/DE/ES seed rows or change `CountryRegionRule` columns in this step. ANY-504 Step 4 owns the clean baseline/bootstrap cleanup.

**Invariants**

- one running API instance has one configured tenant and one configured contour;
- caller input cannot choose a different identity/legal data plane;
- `users.id` remains the canonical user identifier;
- database email uniqueness remains contour-scoped, preserving the architectural possibility of separate same-email accounts on separate contour deployments;
- frontend registration/login payloads remain compatible because they already omit tenant/region;
- repository-managed local/test/generation/migration paths receive explicit local instance scope and do not depend on hidden shell environment;
- no billing/provider selection logic is added to contour configuration.

**Out of scope**

- deleting foreign seed rows;
- changing `default_payment_provider` / `allow_region_override` physically;
- Region Resolver implementation;
- new EU/US enablement behavior;
- changing checkout, product state, payment status, or other ANY-504 Step-4 legacy routes.

**AI prompt**

Implement only Implementation Step 1 of `ANY-510`: make Portal tenant/contour scope server-authoritative.

Use the current branch after merged `ANY-509` / PR #117. Follow these decisions exactly:

- add `Settings.instance_tenant_id` / `Settings.instance_region`, sourced from `INSTANCE_TENANT_ID` / `INSTANCE_REGION`;
- add explicit local/test environment values `anytoolai` / `ru`; production Compose must require explicit values instead of silently choosing a production contour;
- update `scripts/repo.py` repository-managed environments so local runtime generation, direct API/migration commands, generated-schema/OpenAPI imports, and test/check startup paths receive explicit local/test instance scope instead of failing when the new Settings become required;
- make registration, login, password-reset request, and required-document discovery use this server/deployment scope;
- remove caller authority over `tenant_id` / `region` in registration/login and over tenant/region query selection in required-document discovery;
- preserve the existing successful auth response identity fields;
- replace the old cross-region-in-one-process auth regression with one-contour authority regressions;
- do not remove foreign seed rows or legacy provider fields yet.

Work primarily in:

- `.env.example`
- `.env.production.example`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `scripts/repo.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domains/identity/session.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/domains/legal/router.py`
- `apps/api/tests/support/settings.py`
- the directly affected tests in `apps/api/tests/test_api.py` / `test_deployment_contract.py`

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify these plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. briefly summarize how caller scope stopped being authoritative;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
pytest apps/api/tests/test_api.py -k "register_and_login or same_email or password_reset_request_derives_scope or legal_required_documents"
pytest apps/api/tests/test_deployment_contract.py
```

**Expected completion**

- one configured instance scope is the only scope used by public auth/recovery/legal-discovery entrypoints;
- foreign client `tenant_id` / `region` input cannot select a foreign data plane;
- local registration/login/frontend behavior remains usable;
- repository-managed local/test/generation/migration tooling starts successfully with explicit local instance scope;
- no ANY-504 Step-4 data cleanup is performed.

**Proposed commit**

`feat(identity): make contour scope server authoritative`

---

# Implementation Step 2 — Harden canonical identity, sessions, and password-reset persistence

**Status:** `todo`

**Goal**  
Make canonical-user/session/recovery scope structurally consistent, preserve the explicit normal-logout vs security-revocation distinction, and bind known password-reset tokens to `users.id` without changing password-reset anti-enumeration behavior.

**Scope / affected code**

Primary files/areas:

- `apps/api/app/models/_shared.py` only if needed to expose `ForeignKeyConstraint` consistently
- `apps/api/app/models/identity.py`
- `apps/api/app/infrastructure/queries/identity.py`
- `apps/api/app/infrastructure/persistence/password_reset.py`
- `apps/api/app/domains/identity/services/auth.py`
- `apps/api/app/domains/identity/services/password_reset.py`
- one new forward Alembic revision after `20260826_0005`, e.g. `20260921_0006_identity_scope_hardening.py`
- focused fast tests in `apps/api/tests/test_api.py`
- a focused PostgreSQL persistence baseline, preferably `apps/api/tests/test_identity_legal_persistence_postgres.py`

**Implementation decisions**

1. Keep `User.id` unchanged as UUID PK and add only the relational alternate key required for scoped FKs: `UNIQUE(id, tenant_id, region)`. This canonical row/scope key is also the future stable lock anchor required by the updated `ANY-509` paid-access serialization contract; do not implement paid-access locking in this ticket.
2. Replace surrogate-only AuthSession→User scope trust with a composite FK:
   - `(user_id, tenant_id, region)` → `users(id, tenant_id, region)`;
   - restrictive delete behavior;
   - preserve the token-hash unique index and existing expiry fields.
3. Add `MagicLinkToken.user_id: UUID | None`.
   - known-account reset issuance stores the canonical user ID;
   - unknown-email decoy tokens store `NULL`;
   - add a nullable composite FK `(user_id, tenant_id, region)` → matching `users` scope;
   - retain `email_normalized` as the delivery/abuse-protection snapshot, not as canonical identity.
4. Remove `MagicLinkToken.entrypoint_session_id` from the ORM and forward schema because no current password-reset behavior uses it and Step 3 has determined that entrypoint sessions are not retained identity/recovery authority.
5. Forward migration behavior for existing reset tokens:
   - backfill `user_id` only when a unique matching `(tenant_id, region, email_normalized)` user exists;
   - decoy/unknown rows remain null;
   - do not synthesize users or infer across contours.
6. `authenticate_session()` and login lookup must resolve an `active` user explicitly. Do not add a new user status.
7. Preserve normal logout as deletion of that one authenticated session row; do not invent durable logout-history retention. Security-driven invalidation remains revocation:
   - `logout_session()` deletes the current session row as today;
   - password-reset/session-security invalidation sets `revoked_at` on affected active rows;
   - replay after either path fails normal authentication with the existing invalid-session behavior.
8. Password-reset confirmation:
   - atomically claims the hashed reset token as today;
   - requires a non-null token-bound canonical `user_id` for a real reset;
   - reloads the active user by canonical ID and verifies matching tenant/region;
   - changes password, invalidates that user's other outstanding real reset tokens, and revokes active auth sessions in the same transaction;
   - unknown/decoy tokens continue to fail generically without account enumeration.
9. Update outstanding-reset-token invalidation to target canonical `user_id` for known-user tokens rather than mutable email identity. Preserve scoped IP/account rate-limit behavior.
10. Add PostgreSQL tests proving the database rejects an AuthSession or known-user MagicLinkToken whose repeated tenant/region contradicts the referenced user.
11. Add/adjust behavior tests for:
   - normal logout deletes only the current session and replay is invalid;
   - security-revoked/expired tokens remain invalid;
   - reset token hashes only;
   - known reset token stores canonical user ID;
   - decoy reset token has `user_id=NULL`;
   - password reset revokes existing sessions and cannot be reused.
12. Do not add a session pruning/retention job or a new user state.

**Invariants**

- canonical identity is never email-based;
- raw session/reset secrets are never persisted;
- user/session/recovery repeated scope cannot contradict the referenced user in PostgreSQL;
- unknown-email password reset remains externally indistinguishable from known-email request behavior;
- normal logout deletes the current session, while password-reset/security invalidation preserves a durable revoked row; both make token replay invalid;
- canonical User is not hard-deleted by these flows;
- no entrypoint/commerce dependency remains in password-reset persistence.

**Out of scope**

- legal acceptance schema changes (Implementation Step 3);
- registration legal evidence/concurrency changes (Implementation Step 4);
- adding suspended/deleted user states;
- account email-change workflow;
- retention/pruning policy;
- physical removal of the `entrypoint_sessions` table itself.

**AI prompt**

Implement only Implementation Step 2 of `ANY-510`: harden canonical identity, sessions, and password-reset persistence.

Implementation Step 1 is complete. Preserve its server-authoritative instance scope.

Implement these decisions:

- add the scoped alternate key `users(id, tenant_id, region)` required for composite FKs;
- make `auth_sessions(user_id, tenant_id, region)` structurally reference the same scoped user with restrictive deletion;
- add nullable `magic_link_tokens.user_id` with the same scoped composite FK;
- backfill existing known reset tokens only from an exact tenant+region+normalized-email user match; leave decoys null;
- remove `MagicLinkToken.entrypoint_session_id` from the retained identity/recovery schema;
- make login/session resolution explicitly require `UserStatus.ACTIVE` without adding another status;
- preserve normal logout as deletion of the current AuthSession; keep `revoked_at` for password-reset/security invalidation;
- bind real password-reset confirmation/invalidation to token-bound canonical user ID while preserving hashed tokens, rate limits, and unknown-email anti-enumeration behavior;
- add focused PostgreSQL scope-integrity tests plus the directly affected API tests.

Use one ordinary forward Alembic revision after the current `20260826_0005`; do not rewrite old baseline migrations because ANY-504 Step 4 owns the later clean reset.

Work primarily in:

- `apps/api/app/models/identity.py`
- `apps/api/app/infrastructure/queries/identity.py`
- `apps/api/app/infrastructure/persistence/password_reset.py`
- `apps/api/app/domains/identity/services/auth.py`
- `apps/api/app/domains/identity/services/password_reset.py`
- the new identity forward migration
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_identity_legal_persistence_postgres.py`

If model table args need `ForeignKeyConstraint`, add it through the existing model-shared import pattern rather than inventing another ORM abstraction.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify these plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. summarize the final session and reset-token identity semantics;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
pytest apps/api/tests/test_api.py -k "auth_sessions or login_and_logout or password_reset"
make test_db_up
npm run test:api:postgres
make test_db_stop
```

**Expected completion**

- sessions and known reset tokens are structurally scoped to canonical users;
- password reset uses canonical `users.id` for the real account target;
- normal logout removes the current session row while security invalidation retains revoked session rows;
- decoy reset semantics remain intact;
- no entrypoint-session dependency remains in the retained recovery model.

**Proposed commit**

`fix(identity): harden session and recovery scope`

---

# Implementation Step 3 — Add immutable legal acceptance events and legal scope integrity

**Status:** `todo`

**Goal**  
Create the retained provider-independent legal evidence anchor required by the `ANY-509` purchase handoff, make legal/user scope relationally consistent, and stop same-version legal seeding from rewriting historical meaning.

**Scope / affected code**

Primary files/areas:

- `apps/api/app/models/legal.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/domains/legal/models.py`
- `apps/api/app/domains/legal/service.py`
- `apps/api/app/infrastructure/queries/legal.py`
- `apps/api/app/legal_seed.py`
- one new forward Alembic revision after Step 2, e.g. `20260921_0007_legal_acceptance_evidence.py`
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_identity_legal_persistence_postgres.py`
- directly affected legacy test builders that instantiate `DocumentAcceptance`, including `_add_recurring_consent_acceptance()` in `apps/api/tests/test_billing_lifecycle_concurrency_postgres.py`

Do not alter target billing tables; they do not exist yet. Before changing the constructor contract, use one targeted symbol search for direct `DocumentAcceptance(...)` construction so only real callers are adapted; this is caller enumeration for the changed model, not broad repository redesign research.

**Implementation decisions**

1. Add canonical ORM entity `LegalAcceptanceEvent` in `app.models.legal` with the locked fields from this plan:
   - `id` UUID PK;
   - `tenant_id`, `region`, `user_id` non-null and immutable;
   - nullable commercial triplet `external_billing_account_id`, `billing_offer_id`, `accepted_commercial_fingerprint`;
   - `accepted_at`;
   - nullable `ip`, `user_agent`;
   - `created_at`.
2. Add database constraints:
   - composite User FK `(user_id, tenant_id, region)` → `users(id, tenant_id, region)`, restrictive delete;
   - check that the commercial triplet is either all NULL or all non-null/non-empty;
   - alternate key required by the future purchase FK: `(id, user_id, external_billing_account_id, billing_offer_id, accepted_commercial_fingerprint)`;
   - alternate scoped key `(id, tenant_id, region, user_id)` for acceptance-row scope integrity.
3. Add `DocumentAcceptance.legal_acceptance_event_id` and make every retained/new acceptance belong to exactly one event.
   - event/user/tenant/region must match structurally through a composite FK;
   - one event may contain at most one row per `document_version_id`.
4. Make retained target acceptance identity user-bound without prematurely dropping legacy columns.
   - current public acceptance writes are authenticated and no active guest legal runtime justifies guest acceptance;
   - make `DocumentAcceptance.user_id` non-null for the retained Step-3 baseline after a preflight migration check; if an existing row has `user_id IS NULL`, fail explicitly instead of guessing an owner or deleting evidence;
   - keep the physical nullable `guest_id` column only as transitional legacy surface while old checkout/history callers still exist; no new Step-3 target writer may populate it, and ANY-504 Step 4 drops it with the other legacy acceptance provenance columns.
5. Backfill current user-bound acceptance rows safely:
   - create one non-commercial `LegalAcceptanceEvent` per existing acceptance using the same user/scope/accepted-at/IP/user-agent evidence;
   - link the existing acceptance to that event;
   - do not transform legacy `plan_id` / entrypoint metadata into commercial target authority.
6. Add scope integrity for legal ownership:
   - `legal_entities` alternate key `(id, tenant_id, region)`;
   - `document_versions(legal_entity_id, tenant_id, region)` composite FK → same-scoped legal entity;
   - `document_versions` alternate key `(id, tenant_id, region)`;
   - `document_acceptances(document_version_id, tenant_id, region)` composite FK → same-scoped document version.
7. Update current generic authenticated legal acceptance writes so each call creates one non-commercial `LegalAcceptanceEvent` and its `DocumentAcceptance` in the same transaction.
   - public response shape does not need to expose the event ID in this ticket;
   - existing legacy recurring fields may still be written for retained checkout compatibility, but the event commercial triplet stays NULL. Therefore a legacy Plan-bound recurring acceptance cannot satisfy the future PurchaseIntent composite binding.
8. Make target service/read logic use the event as canonical acceptance-action time/scope without doing ANY-504 Step-4 cleanup of every legacy column. New Step-3 writes populate transitional per-document `accepted_at` from the event timestamp; legacy readers may remain temporarily, but no target rule may treat the duplicate timestamp as independent authority. Do not duplicate a second target validator.
9. Harden `seed_legal_documents()`:
   - if the exact `(tenant_id, region, doc_type, version)` already exists, compare its immutable material identity with the manifest;
   - any mismatch in ID, legal-entity reference, title, URL, content hash, published/effective times, or `requires_acceptance` must raise a clear seed/configuration error before rewriting the existing version;
   - allow only active-selection lifecycle changes (`is_active`) for an existing identical version;
   - publishing changed material meaning requires a new version row.
10. Enforce the legal audit boundary in PostgreSQL in the same forward migration, after all backfill is complete:
    - reject `DELETE` of `legal_acceptance_events` and changes to its core acceptance identity/scope/commercial/timestamp fields;
    - `ip` / `user_agent` are ancillary metadata, not acceptance authority: do not implement a redaction workflow now, but shape the guard so a future separately approved privacy policy can only clear/redact those values rather than rewrite them to different non-null evidence;
    - reject `UPDATE` and `DELETE` of `document_acceptances` for the current Step-3 baseline; their legacy per-row request metadata is transitional and will be dropped in ANY-504 Step 4 rather than promoted into target authority;
    - protect material `document_versions` fields from in-place update while still allowing the intentional `is_active` lifecycle selection (and its ordinary timestamp bookkeeping);
    - use narrowly scoped PostgreSQL trigger functions/constraints local to this legal invariant rather than a general trigger framework.
11. Add focused tests proving:
    - exact re-seeding is idempotent;
    - mutable current LegalEntity metadata is never used to reinterpret/rebuild historical accepted DocumentVersion content/hash; a true operator-identity replacement uses a new LegalEntity + new affected DocumentVersion, and no speculative `legal_entity_versions` table/model is introduced;
    - adding a newer version may deactivate the old one without rewriting it;
    - a same-version material mismatch fails closed;
    - direct PostgreSQL attempts to update/delete acceptance evidence fail;
    - material in-place DocumentVersion rewrite fails while `is_active` selection remains allowed;
    - legal event/user/document scope mismatches are rejected by PostgreSQL;
    - generic legal acceptance creates one event + one acceptance, and a repeated explicit call creates another append-only action rather than hidden deduplication;
    - event `accepted_at` is the target action timestamp used by new writes/reads;
    - legacy recurring acceptance remains transitional and has no target commercial triplet.
12. Adapt only direct existing `DocumentAcceptance(...)` builders broken by the required event/user fields. Known callers include the helper(s) in `test_api.py` and `_add_recurring_consent_acceptance()` in `test_billing_lifecycle_concurrency_postgres.py`; preserve what those tests characterize instead of redesigning their billing behavior.
13. Do not add a commercial acceptance public API or a writer that accepts arbitrary `billing_offer_id` / fingerprint from a browser. ANY-504 Step 7 will own authoritative commercial acceptance creation after catalog/mapping authority exists.
14. Keep current legacy checkout-only acceptance columns that still have active retained callers until ANY-504 Step 4; record their removal explicitly in the Implementation Step-6 handoff rather than breaking current checkout inside Step 3.

**Invariants**

- historical legal-document material meaning is not rewritten under a reused version;
- every new retained acceptance belongs to one canonical user and one acceptance action;
- legal evidence cannot cross tenant/region/user scope;
- legacy `Plan.id` or arbitrary metadata never becomes the target commercial fingerprint/offer authority;
- the future purchase binding can be a relational FK to an immutable legal acceptance event rather than JSON or copied mutable data;
- no provider/LBX customer or payment semantics enter the legal domain.

**Out of scope**

- PurchaseIntent table or runtime;
- external catalog validation;
- Widget/LBX integration;
- deletion of legacy recurring/entrypoint columns still needed by current checkout;
- physical removal of `entrypoint_sessions`;
- legal/PII retention duration policy.

**AI prompt**

Implement only Implementation Step 3 of `ANY-510`: add the retained legal acceptance-event boundary and harden legal scope/version integrity.

Implementation Steps 1–2 are complete. Follow these locked decisions:

- add `LegalAcceptanceEvent` as the provider-independent parent for one atomic legal acceptance action;
- fields are exactly: UUID id, tenant_id, region, canonical user_id, nullable all-or-none commercial triplet (`external_billing_account_id`, `billing_offer_id`, `accepted_commercial_fingerprint`), accepted_at, optional IP/user-agent audit evidence, created_at;
- add composite user/scope FKs and the alternate keys needed for both acceptance-row scope and the future PurchaseIntent composite FK;
- add non-null `DocumentAcceptance.legal_acceptance_event_id`, enforce same event/user/tenant/region and one document version per event;
- make retained `DocumentAcceptance.user_id` non-null after an explicit preflight check; keep `guest_id` only as an unused transitional legacy column until ANY-504 Step 4, and fail migration if an existing acceptance has no canonical user rather than inventing ownership;
- backfill existing user-bound acceptances with non-commercial events without promoting legacy Plan/entrypoint metadata into target commercial authority;
- add same-scope composite FK integrity for LegalEntity → DocumentVersion and DocumentVersion → DocumentAcceptance;
- make current authenticated legal writes create a non-commercial event + acceptance atomically while preserving their existing public response contract;
- make legal seeding fail closed on same-version DocumentVersion material mismatch and allow only active-selection changes for an otherwise identical version; LegalEntity remains current operator metadata and historical acceptance logic must never reconstruct old accepted meaning from mutable LegalEntity fields; a true operator replacement uses a new LegalEntity identity plus new affected DocumentVersion rows;
- add narrow PostgreSQL legal-evidence guards: core LegalAcceptanceEvent facts cannot be rewritten/deleted, future policy may only redact ancillary event IP/user-agent rather than replace them, DocumentAcceptance rows remain append-only in Step 3, and material DocumentVersion fields cannot be rewritten in place while `is_active` lifecycle selection remains allowed;
- adapt only direct existing DocumentAcceptance constructors that need the new event/user fields, including the known billing concurrency test helper, without changing the billing behavior they characterize;
- retain checkout-only legacy acceptance columns until ANY-504 Step 4 if current retained checkout still directly needs them; no new target writer may rely on guest/entrypoint/source/arbitrary metadata;
- do not create a public commercial acceptance endpoint or trust browser-supplied external offer/fingerprint values.

Use one ordinary forward Alembic revision after Step 2; do not rewrite the existing initial migration history.

Work primarily in:

- `apps/api/app/models/legal.py`
- `apps/api/app/models/__init__.py`
- `apps/api/app/domains/legal/models.py`
- `apps/api/app/domains/legal/service.py`
- `apps/api/app/infrastructure/queries/legal.py`
- `apps/api/app/legal_seed.py`
- the new legal forward migration
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_identity_legal_persistence_postgres.py`

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify these plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. summarize the final LegalAcceptanceEvent / DocumentAcceptance relation and same-version seed rule;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
pytest apps/api/tests/test_api.py -k "legal_seed or required_document_acceptance or recurring_consent"
make test_db_up
npm run test:api:postgres
make test_db_stop
```

**Expected completion**

- `LegalAcceptanceEvent` exists as retained provider-independent evidence;
- all new legal acceptances are event-backed and user-bound;
- database scope prevents cross-user/cross-contour evidence;
- same-version legal material can no longer be silently rewritten;
- future PurchaseIntent has a precise relational evidence target, but no future purchase runtime is implemented.

**Proposed commit**

`feat(legal): add immutable acceptance evidence boundary`

---

# Implementation Step 4 — Make registration atomically persist mandatory legal evidence

**Status:** `todo`

**Goal**  
Make successful registration produce one coherent canonical user, durable required legal evidence, and initial session in one transaction, including deterministic concurrent-duplicate behavior.

**Scope / affected code**

Primary files/areas:

- `apps/api/app/domains/identity/services/auth.py`
- provider-independent helpers in `apps/api/app/domains/legal/service.py` created in Step 3
- focused identity/legal queries only if needed
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_identity_legal_persistence_postgres.py`
- existing legal/checkout characterization tests whose old assumption was specifically that registration created zero durable acceptances

The frontend registration payload does not need to change.

**Implementation decisions**

1. Preserve the public registration booleans `personal_consent` and `offer_consent`; give them one explicit durable meaning instead of leaving them as transient gates.
2. After validating both booleans and before committing registration, resolve the current server-scoped active required legal documents.
3. Registration acceptance mapping:
   - `privacy` and `pd_consent` required versions are covered by `personal_consent`;
   - `offer` required version is covered by `offer_consent`;
   - `recurring_consent` is explicitly excluded because it is purchase-specific;
   - `requires_acceptance=False` documents are informational and are not recorded as accepted merely because registration happened.
4. Fail closed before commit if the server-scoped legal pack cannot produce the complete expected registration set: active required `privacy`, `pd_consent`, and `offer` versions must all exist and be effective, and no additional active required non-recurring document may exist without an explicit registration UI/API mapping. Do not silently register with missing evidence and do not invent a new checkbox mapping in backend code.
5. Create exactly one non-commercial `LegalAcceptanceEvent` for the registration action and one `DocumentAcceptance` per applicable required document using:
   - canonical new user ID/scope;
   - the exact current `DocumentVersion` ID;
   - canonical `acceptance_kind` mapping;
   - the canonical **registration-surface** acceptance-text hash defined by the API contract, not the generic per-document `build_acceptance_text(document)` hash unless the actual registration statement is identical;
   - one shared `accepted_at`;
   - request IP/user-agent at the event level.
   The backend owns/derives these canonical registration statements/hashes; browser input is only the two booleans and cannot provide arbitrary evidence text/hash.
6. Update provider-independent legal read/missing-document logic as needed so an exact DocumentVersion acceptance created through registration remains valid evidence even though its acceptance statement may differ from the generic standalone legal-acceptance statement. Do not weaken write-time hash validation: each write path must still derive/validate its own canonical statement/hash.
7. Keep User + registration LegalAcceptanceEvent + all required DocumentAcceptance rows + initial AuthSession inside the existing `register_user()` Application-owned transaction. There must be one final commit.
8. Preserve existing registration failure semantics for missing personal/offer consent.
9. Harden duplicate registration concurrency around the existing database uniqueness constraint:
   - the pre-check may remain as an early friendly path;
   - the database unique constraint `uq_users_tenant_region_email_normalized` is the final race guard;
   - classify an `IntegrityError` as duplicate registration only when PostgreSQL reports that exact constraint (or the repository's stable equivalent after the scoped key is renamed) and, after rollback, the same scoped user exists;
   - do not use "scoped user exists" alone to swallow an unrelated integrity failure; every other integrity error is re-raised.
10. PostgreSQL concurrency regression:
   - run two registration transactions for the same configured tenant/region/email concurrently;
   - exactly one succeeds;
   - the loser returns duplicate-email semantics;
   - final state contains one User, one coherent initial registration acceptance event/set of mandatory acceptances, and one initial AuthSession from the winning registration;
   - no partial user/evidence/session rows from the loser.
11. Extend the existing injected registration failure regression so a failure before initial session/commit leaves no User, no LegalAcceptanceEvent, no DocumentAcceptance, and no AuthSession, and retry can succeed cleanly.
12. Update only characterization tests whose premise intentionally changes from 'registration booleans are transient' to 'registration persists durable evidence'. In particular:
    - replace/rename `test_seeded_legal_documents_block_checkout_on_fresh_database` so it proves seeded required registration documents are accepted atomically during registration rather than expected to remain missing;
    - in `test_checkout_requires_acceptance_again_when_active_document_version_changes`, treat the registration-time version as already accepted and keep the important assertion that a newly activated later version requires a new acceptance;
    - for hash/scope/time legal-gate tests that need an unaccepted document, create/activate the document version after registration (or otherwise construct the user directly) instead of deleting/falsifying the new registration evidence;
    - use a targeted search for `DocumentAcceptance` zero-count assertions immediately after registration and change only those whose semantic assumption is superseded by this ticket.
13. Registration response remains the existing token + user identity contract. Do not expose internal acceptance event IDs merely because they now exist.
14. Do not change email verification semantics in this ticket; that is separate from the requested identity/legal baseline.

**Invariants**

- a successfully registered canonical user is never left without the required registration legal evidence;
- registration booleans are only transport/UI intent; durable versioned evidence is the committed source of truth;
- registration legal evidence and initial session cannot commit partially;
- concurrent duplicate registration creates at most one canonical user;
- no recurring/commercial offer acceptance is fabricated during account creation;
- no external billing/provider state is touched.

**Out of scope**

- changing the registration UI/checkbox wording;
- adding new legal document types or guessing a mapping for them;
- email verification redesign;
- commercial purchase acceptance;
- checkout cleanup;
- external billing customer creation.

**AI prompt**

Implement only Implementation Step 4 of `ANY-510`: make registration atomically persist mandatory versioned legal evidence.

Implementation Steps 1–3 are complete. Use the provider-independent `LegalAcceptanceEvent` / `DocumentAcceptance` boundary from Step 3.

Implement these exact semantics:

- keep `personal_consent` and `offer_consent` in the public registration payload;
- `personal_consent=true` durably covers active required `privacy` and `pd_consent` documents;
- `offer_consent=true` durably covers the active required `offer` document;
- do not auto-accept `recurring_consent` or informational documents;
- if another active required non-recurring document exists with no registration UI mapping, fail closed before commit;
- require the complete expected active/effective registration document set (`privacy`, `pd_consent`, `offer`) and fail closed if any is missing or if an unmapped active required non-recurring document exists;
- define backend-owned canonical registration acceptance statements matching the API/UI checkbox meaning and persist hashes of those statements; do not fabricate the generic standalone per-document acceptance phrase for registration evidence, and do not trust a browser-supplied acceptance hash;
- make exact-version acceptance/read logic support valid evidence created by different approved acceptance surfaces without weakening flow-specific write-time hash validation;
- one registration action creates one non-commercial LegalAcceptanceEvent and one DocumentAcceptance per applicable required document, all at one acceptance timestamp;
- User + all registration legal evidence + initial AuthSession must commit atomically in `register_user()`;
- preserve the existing missing-consent errors and successful response shape;
- use `uq_users_tenant_region_email_normalized` as the final concurrent duplicate guard; map to `EmailAlreadyRegisteredError` only when the caught PostgreSQL integrity failure is that exact scoped-email constraint and the scoped user exists after rollback; re-raise unrelated integrity errors;
- add PostgreSQL concurrency coverage and extend the existing rollback/retry regression to assert no partial legal evidence;
- update only existing legal/checkout characterization tests whose old assumption was that registration created no acceptance rows: registration-time active `privacy` / `pd_consent` / `offer` are now accepted, while a later newly activated version must still require fresh acceptance. For hash/scope/time tests that need an unaccepted document, arrange that document after registration instead of deleting the new evidence.

Work primarily in:

- `apps/api/app/domains/identity/services/auth.py`
- directly used provider-independent legal helpers in `apps/api/app/domains/legal/service.py`
- `apps/api/tests/test_api.py`
- `apps/api/tests/test_identity_legal_persistence_postgres.py`

Do not change the frontend payload; it already sends the two registration booleans and does not send tenant/region.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify these plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. summarize the exact registration transaction and duplicate-race behavior;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
pytest apps/api/tests/test_api.py -k "registration or register or missing_personal_consent or missing_offer_consent"
make test_db_up
npm run test:api:postgres
make test_db_stop
```

**Expected completion**

- every successful registration has durable exact-version legal evidence before commit, with hashes representing the canonical registration statements actually attested by the API booleans rather than fabricated generic document-acceptance text;
- exact-version acceptance reads remain valid across approved generic and registration acceptance surfaces without weakening write-time validation;
- user/evidence/session commit is atomic;
- concurrent duplicate registration converges to one user and one winning registration result without partial loser state;
- public frontend/API registration contract remains compatible.

**Proposed commit**

`feat(identity): persist registration legal evidence atomically`

---

# Implementation Step 5 — Add provider-independent identity/legal architecture guards and survivor regressions

**Status:** `todo`

**Goal**  
Turn the ANY-504 Step-3 identity/legal decisions into focused regressions that can survive ANY-504 Step-4 legacy commerce removal and prevent the retained identity/legal boundary from reintroducing PII/provider/entrypoint/trial authority. Do not add speculative tests for an allocator that does not exist until ANY-504 Step 7.

**Scope / affected code**

Primary files/areas:

- `apps/api/tests/test_architecture.py`
- `apps/api/tests/test_model_enums.py` only for the existing `UserStatus` vocabulary assertion if appropriate
- `apps/api/tests/test_identity_legal_persistence_postgres.py`
- directly affected identity/legal tests currently in `apps/api/tests/test_api.py`
- repository architecture-check helpers only if an existing reusable AST helper is clearly the correct owner; do not create a new general framework solely for this ticket

**Implementation decisions**

1. Add a durable architecture regression that forbids an ORM/table named `external_billing_accounts` and forbids FKs to such a table. `external_billing_account_id` remains an opaque configured text scope in later retained/target rows.
2. Do **not** add a speculative `billing_customer_key` expression/AST rule before the allocator exists. Add a durable boundary assertion that retained identity/session/legal modules do not allocate/bind billing customers and do not use email/phone/name/provider IDs as cross-system identity. Do **not** assert globally that `external_billing_customers` is absent: ANY-504 Step 4 is required to create that target table, so such a test would be intentionally broken by the next step. Record the global key non-reuse invariant in the durable handoff; allocator-specific derivation tests belong to ANY-504 Step 7 when real allocation code exists.
3. Guard retained identity/recovery from `EntrypointSession`/commerce coupling:
   - `MagicLinkToken` no longer contains `entrypoint_session_id` after Step 2;
   - auth/session/password-reset retained modules must not import/use `EntrypointSession`, Product/Plan, Subscription/Entitlement, or provider adapters for identity/recovery decisions.
   - do not globally ban `EntrypointSession` while legacy checkout still exists; restrict the guard to the retained identity/recovery surfaces.
4. Lock `UserStatus` to its current evidence-backed vocabulary (`active`) for this step. If another status appears, tests should force its auth/session/recovery semantics to be deliberately added rather than silently inheriting active behavior.
5. Ensure focused provider-independent behavioral coverage exists for:
   - server-authoritative one-contour registration/login/legal discovery;
   - canonical UUID user identity;
   - hashed sessions/reset tokens;
   - delete-on-normal-logout plus reset/security-session revocation;
   - unknown-email reset anti-enumeration;
   - canonical-user reset binding;
   - structural user/session/recovery/legal scope constraints;
   - immutable same-version legal documents;
   - event-backed append-only legal acceptances;
   - atomic/concurrent registration.
6. Keep these tests independent from CloudPayments, provider registry success, checkout Orders/Plans, subscription lifecycle, or trial data wherever the behavior under test is identity/session/legal.
7. Do not duplicate large test setups unnecessarily. Reuse the Implementation Step-2/3/4 focused PostgreSQL baseline and current API test fixtures; extract a helper only when it removes concrete duplication in these new tests.
8. Add a regression/assertion documenting that no retained identity/session/legal behavior requires Portal trial state. Do this as a dependency/architecture assertion, not by deleting the legacy `identity.services.account` code that ANY-504 Step 4 owns.

**Invariants**

- later external-billing work cannot silently introduce a Portal-owned `external_billing_accounts` model;
- ANY-510 introduces no premature customer-key allocation/binding responsibility into retained identity/legal modules; retained identity/legal code cannot use PII/provider values as cross-system identity, and the handoff preserves global non-reuse for the later real allocator;
- identity/recovery remains provider- and commerce-independent;
- no new user status can silently inherit undefined auth behavior;
- ANY-504 Step-4 deletion of legacy commerce/tests will not erase the provider-independent identity/legal regression baseline.

**Out of scope**

- implementing or AST-policing a not-yet-existing `billing_customer_key` allocator; allocator-specific guards belong to ANY-504 Step 7;
- forbidding the future target `external_billing_customers` table globally; ANY-504 Step 4 owns creation of that approved table;
- proving LBX `outer_id` behavior;
- deleting legacy checkout/account/product-state tests;
- rewriting the entire architecture checker;
- adding a generalized static-analysis framework.

**AI prompt**

Implement only Implementation Step 5 of `ANY-510`: add focused architecture guards and survivor regressions for the provider-independent identity/session/legal baseline completed in Implementation Steps 1–4.

Add only narrowly justified checks:

1. forbid an ORM/table/FK target named `external_billing_accounts` — `external_billing_account_id` is configuration scope, not a Portal account entity;
2. do not add a speculative customer-key allocator or allocator-specific AST rule. Guard the retained identity/session/legal modules against billing-customer allocation/binding responsibilities and against promoting email/phone/name/provider IDs into cross-system identity. Do not assert that `external_billing_customers` is globally absent, because ANY-504 Step 4 must create that target table. Preserve the ANY-509 global key non-reuse invariant in the handoff; real allocation/derivation guards belong to ANY-504 Step 7;
3. guard the retained auth/session/password-reset surfaces from `EntrypointSession`, Product/Plan, Subscription/Entitlement, and provider-adapter dependencies without banning those classes from the still-retained legacy checkout code;
4. keep `UserStatus` at the currently justified `active` vocabulary and make a future new status require deliberate test/behavior updates;
5. ensure there is focused provider-independent regression coverage for one-contour scope, canonical identity, hashed secrets, normal-logout deletion, security revocation, reset anti-enumeration/canonical binding, relational scope integrity, immutable legal versions, event-backed legal acceptance, and atomic/concurrent registration;
6. add a focused dependency assertion showing retained identity/session/legal does not require old Portal trial state, but do not delete `identity.services.account` or other ANY-504 Step-4 legacy code.

Work primarily in:

- `apps/api/tests/test_architecture.py`
- `apps/api/tests/test_model_enums.py` if needed
- `apps/api/tests/test_identity_legal_persistence_postgres.py`
- directly affected identity/legal tests in `apps/api/tests/test_api.py`

Reuse existing AST/test patterns rather than creating a generic new framework.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify these plan assumptions. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. summarize each guard and what future regression it prevents;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution.

**Manual verification**

```bash
pytest apps/api/tests/test_architecture.py -k "external_billing or billing_customer or identity or entrypoint or trial"
pytest apps/api/tests/test_model_enums.py -k "user or enum"
make test_db_up
pytest apps/api/tests/test_identity_legal_persistence_postgres.py
make test_db_stop
npm run architecture:check
```

**Expected completion**

- ANY-510 cannot accidentally introduce a Portal billing-account/customer allocator or PII/provider-based cross-system identity into the retained boundary;
- retained identity/recovery code is mechanically independent from entrypoint/commerce/provider/trial ownership;
- ANY-504 Step-3 provider-independent regressions are separable from ANY-504 Step-4 legacy deletion.

**Proposed commit**

`test(architecture): guard provider independent identity baseline`

---

# Implementation Step 6 — Freeze the ANY-504 Step 3 → Step 4 handoff and run final verification manually

**Status:** `todo`

**Goal**  
Record the final as-built identity/session/legal contract and exact ANY-504 Step-4 cleanup/install instructions so ANY-504 Step 4 can build the clean target schema without reopening Step-3 architecture.

**Scope / affected code**

Primary documentation:

- new `docs/architecture/portal-identity-session-legal-baseline.md`
- `docs/architecture/external-billing-persistence-reset.md`
- `docs/architecture/contours.md`
- `docs/architecture/deployment.md`
- `docs/architecture/payment-portal-data-model.md` as current-state documentation for the newly implemented retained tables/constraints
- `docs/README.md` if needed for navigation
- `apps/api/tests/test_repository_docs.py` / existing docs guard only if the new canonical handoff document needs a navigation regression

No new business behavior should be introduced in this step.

**Implementation decisions**

1. Create `docs/architecture/portal-identity-session-legal-baseline.md` as the durable Step-3 handoff. It must document the **as-built** repository, not repeat the Linear ticket generically.
2. Include these sections explicitly:
   - authority and scope;
   - canonical Portal user identity and one-contour scope;
   - current `UserStatus` lifecycle decision;
   - canonical user deletion/non-reuse vs future PII erasure;
   - session token/hash/expiry/revocation/logout/replay semantics;
   - password-reset token/canonical-user/rate-limit/session-revocation semantics;
   - relational scope-integrity keys/FKs;
   - legal-document immutability and active-version lifecycle, plus the explicit decision that immutable DocumentVersion content/hash is historical acceptance truth rather than a speculative second LegalEntity-version model;
   - registration boolean → durable document-version acceptance mapping and transaction/concurrency semantics;
   - retained public auth/session/legal/recovery API contract, including core `/api/auth/session` survivor semantics and the ANY-504 Step-4 removal of `product`/`product_state` billing presentation;
   - `LegalAcceptanceEvent` + `DocumentAcceptance` target physical contract, canonical event timestamp, generic repeated-acceptance semantics, and ancillary IP/user-agent privacy status;
   - exact future PurchaseIntent legal-evidence FK shape and the ANY-509 rule that missing linked PurchaseIntent/mapping/legal provenance forbids both paid grants and allowances;
   - security/privacy rules for token secrets, PII, IP/user-agent evidence, and no invented retention duration;
   - external-billing customer identity invariant (`billing_customer_key` globally unique/permanently non-reusable across retained slots, no `external_billing_accounts` table, configured `external_billing_account_id`);
   - exact paid-access semantic scope representation and the canonical `User` row as the future serialization lock anchor;
   - provider-independent regression matrix and exact owning tests;
   - explicit ANY-504 Step-4 migration/install handoff;
   - explicit later-step deferrals.
3. Freeze the ANY-504 Step-4 retained table set:
   - `regions`;
   - `country_region_rules` after ANY-504 Step-4 cleanup of non-local/provider-routing residue;
   - `users`;
   - `auth_sessions`;
   - `magic_link_tokens`;
   - `password_reset_rate_limits`;
   - `legal_entities`;
   - `document_versions`;
   - `legal_acceptance_events`;
   - `document_acceptances` in its clean retained subset.
4. Freeze ANY-504 Step-4 removals/cleanups relevant to Step 3:
   - remove `entrypoint_sessions`; Step 3 found no provider-independent identity/legal/origin requirement that justifies retaining it;
   - remove legacy `DocumentAcceptance` guest/entrypoint/source/arbitrary-metadata/Plan-bound columns listed in this plan once legacy checkout is removed;
   - remove non-local `eu`/DE/ES bootstrap rows from the RU clean baseline; Step-3 tests no longer require cross-contour registration in one database/runtime;
   - retain only local one-contour region/country bootstrap needed by the configured RU instance;
   - remove `CountryRegionRule.default_payment_provider` from the clean target because direct-provider selection is not contour identity authority;
   - remove `allow_region_override` from the clean one-contour baseline. The target contour contract makes deployment/Region Resolver routing authoritative and the local Portal instance never lets the client override its data-plane contour;
   - preserve provider-independent local fields such as country membership/market enablement/document-set validation where still used by the one-contour model.
5. Resolve the `ANY-509` paid-access scope handoff explicitly: ANY-504 Step 4 must use non-null explicit `tenant_id`, `region`, and `user_id` on both `paid_access_states` and `access_invalidation_outbox`, enforce a composite FK to `users(id, tenant_id, region)`, and enforce one row per `(tenant_id, region, user_id)` semantic scope. Future AccessSnapshot serialization uses that identical three-part scope. The canonical `User` row is the stable lock anchor that ANY-504 Step 9 writers will acquire before deriving/committing semantic access changes. Step 3/6 documents this contract; it does not implement paid-access state or locking runtime.
6. State explicitly that ANY-504 Step 4 replaces pre-reset Alembic history with one clean baseline **after** using the final Step-3 ORM/handoff as authority. The Implementation Step-2/3 forward migrations are transitional upgrade history and must not be copied mechanically into the new clean baseline.
   - Step 4 must nevertheless recreate every retained Step-3 **PostgreSQL-only invariant that is not expressible in SQLAlchemy metadata**, especially the narrow legal immutability/append-only trigger semantics installed for `legal_acceptance_events`, `document_acceptances`, and material `document_versions` fields.
   - the Step-6 handoff must list those trigger/function semantics explicitly so deleting Step-3 migration files cannot silently delete the invariant from the clean baseline.
7. Update the `ANY-509` handoff checklist in `docs/architecture/external-billing-persistence-reset.md` from delegated questions to resolved Step-3 results/link. Do not reopen its 15-table target design.
8. Freeze future PurchaseIntent binding exactly:

```text
purchase_intents.legal_acceptance_event_id NOT NULL

(legal_acceptance_event_id,
 user_id,
 external_billing_account_id,
 billing_offer_id,
 accepted_commercial_fingerprint)
    -> legal_acceptance_events(
         id,
         user_id,
         external_billing_account_id,
         billing_offer_id,
         accepted_commercial_fingerprint)
ON DELETE RESTRICT
```

9. Record that a purchase-compatible event must contain the complete required versioned document acceptance set created atomically from an authoritative commercial offer/fingerprint. Generic registration/legal events with NULL commercial triplets are not purchase-compatible evidence. Carry forward the reviewed ANY-509 `9830ca1` predicate: an external subscription lacking a valid linked PurchaseIntent with this immutable legal/commercial evidence and pinned mapping provenance remains commercially ineligible and contributes neither a paid product grant nor an allowance; primary selection/provider state/manual review cannot bypass that rule.
10. Record the retained public API survivor/removal contract explicitly: core `/api/auth/session` identity remains; `product` input and `product_state` output plus checkout/payment/catalog/account-billing contracts are ANY-504 Step-4 removals. Registration/login/recovery/legal discovery are server-scoped as established by ANY-510.
11. Record `entrypoint_sessions` removal as final; do not preserve Product/Bundle foreign keys or invent a replacement origin table in ANY-504 Step 4.
12. Record the trial dependency result as final: identity/session/legal requires no retained Portal trial lifecycle. ANY-504 Step 4 may remove old trial/commercial state according to `ANY-509`.
13. Update deployment/contour docs to show `INSTANCE_TENANT_ID` / `INSTANCE_REGION` as implemented one-contour authority.
14. Update current-state data-model docs to match the as-built Step-3 models and constraints. Clearly distinguish transitional legacy columns still waiting for ANY-504 Step 4 from the clean retained target subset.
15. Do not put implementation-plan status prose into normative architecture sections unless it explains a necessary transition; normative docs should describe the resulting contract.

**Invariants**

- ANY-504 Step 4 can implement the clean schema without inventing identity/session/legal decisions;
- ANY-504 Step 4 does not preserve `entrypoint_sessions`, foreign contour seeds, or direct-provider routing because old tests happened to use them;
- ANY-504 Step 4 does not create a generic legal JSON field or legacy Plan-bound consent as PurchaseIntent evidence;
- no later-step LBX/catalog/purchase/webhook/access behavior is implemented by documentation edits;
- `ANY-509` target billing tables and ownership remain unchanged except for resolving the legal-evidence FK delegated to Step 3.

**Out of scope**

- executing ANY-504 Step 4;
- squashing/replacing Alembic history now;
- changing any remaining business behavior merely to make documentation prettier;
- LBX Phase 0 or provider-contract decisions;
- legal/PII retention durations not provided by Legal/Finance authority.

**AI prompt**

Implement only Implementation Step 6 of `ANY-510`: freeze the as-built Portal identity/session/legal baseline and the exact ANY-504 Step 3 → Step 4 handoff.

Implementation Steps 1–5 are complete and are the implementation authority for this documentation step. Do not redesign them.

Create `docs/architecture/portal-identity-session-legal-baseline.md` and update the directly related handoff/current-state documentation so ANY-504 Step 4 has no unresolved identity/session/legal architecture to invent.

The handoff must explicitly record:

- canonical UUID user identity and server-authoritative one-contour scope;
- current active-only UserStatus decision and canonical-user non-reuse/hard-delete rules;
- session and password-reset semantics, including normal logout deletion versus security-driven revocation;
- relational scope-integrity constraints;
- legal version immutability and explicit non-versioned LegalEntity metadata semantics;
- atomic registration legal evidence and duplicate concurrency behavior, including the implemented canonical registration acceptance statements/hashes and the rule that exact-version acceptance may originate from more than one approved acceptance surface;
- final `LegalAcceptanceEvent` / clean `DocumentAcceptance` physical contract, canonical event timestamp, append-only repeated-acceptance semantics, ancillary IP/user-agent treatment, and the exact PostgreSQL-only immutability/append-only trigger semantics that Step 4 must recreate in its fresh baseline even though the transitional Step-3 migrations are discarded;
- future PurchaseIntent composite FK to the exact same user + configured external billing account + billing offer + accepted commercial fingerprint, plus the reviewed ANY-509 predicate that paid grant/allowance derivation requires the valid linked PurchaseIntent + immutable accepted legal/commercial evidence + pinned mapping provenance;
- no `external_billing_accounts` table; `billing_customer_key` is opaque/non-PII, globally unique across retained customer slots, permanently reserved locally, and cannot become reusable after billing-account configuration changes;
- explicit `(tenant_id, region, user_id)` columns/constraints are the ANY-504 Step-4 physical paid-access scope, and the canonical User row is the later paid-access serialization lock anchor;
- `entrypoint_sessions` has no retained provider-independent role and is removed in ANY-504 Step 4;
- ANY-504 Step 4 removes foreign `eu`/DE/ES RU-baseline seeds and direct-provider contour residue now that Step-3 tests no longer depend on them;
- no provider-independent identity/session/legal dependency on the old Portal trial lifecycle;
- exact provider-independent regression/test matrix;
- explicit deferral of target billing table creation, LBX Phase 0, catalog, PurchaseIntent runtime, Widget, webhooks, paid access, and Kernel integration.

Update `docs/architecture/external-billing-persistence-reset.md` only enough to resolve its Step-3 delegated checklist and link the new handoff. Do not reopen the 15 target billing-table design.

Also align `contours.md`, deployment docs, and current-state data-model docs with the implemented `INSTANCE_TENANT_ID` / `INSTANCE_REGION` and retained Step-3 schema.

Implement only this step. Follow the decisions defined in this prompt. Do not perform broad repository research; inspect only the directly relevant current files if needed to verify the completed implementation. Do not redesign the architecture. Do not perform unrelated refactoring. Do not work on future steps. Do not run tests, linters, formatters, migration commands, generators, docs checks, or any other automated verification commands. Do not stage files. Do not create commits.

After implementation:

1. report every changed file;
2. summarize the final ANY-504 Step-4 handoff decisions;
3. report the exact verification commands I should run manually.

If the current code materially contradicts an assumption required by this step, stop and describe the contradiction instead of inventing a new solution or changing the documented architecture to hide the mismatch.

**Manual verification**

Run the final verification yourself after reviewing the Step-6 diff:

```bash
npm run docs:check
npm run test:api:fast
make test_db_up
npm run migrate:api
npm run test:api:postgres
npm run test:api
make test_db_stop
npm run architecture:check
npm run check:fast
```

If `npm run test:api` already executes the PostgreSQL partition in the current repository tooling, it is acceptable to omit the immediately preceding duplicate `npm run test:api:postgres`; keep at least one full PostgreSQL-backed run.

**Expected completion**

- the repository contains one explicit as-built authority for Portal identity/session/legal Step 3;
- every `ANY-509` Step-3 handoff question is resolved;
- ANY-504 Step 4 has exact retained/drop/bootstrap/legal-FK instructions plus the PostgreSQL-only legal immutability triggers it must recreate in the clean baseline, and does not need to redesign Step 3;
- provider-independent tests and architecture checks pass manually;
- no future `ANY-504` step has been implemented early.

**Proposed commit**

`docs(architecture): freeze identity legal step 4 handoff`

---

## Final Acceptance Mapping

| ANY-510 required outcome | Covered by |
| --- | --- |
| Canonical Portal user identity is UUID and not email/provider identity | Implementation Steps 2, 5, 6 |
| `billing_customer_key` is opaque/non-PII, globally unique across retained customer slots, permanently non-reused across billing-account configuration changes, and not allocated early | Implementation Steps 5, 6 |
| `external_billing_account_id` is configured scope, not a Portal account table | Implementation Steps 3, 5, 6 |
| One contour per deployed instance; client cannot select another data plane | Implementation Steps 1, 5, 6 |
| `UserStatus` lifecycle is explicit without inventing unsupported states | Implementation Steps 2, 5, 6 |
| Canonical user non-reuse / hard-delete vs future PII erasure is explicit | Implementation Steps 2, 3, 6 |
| Session token hashing, expiry, normal-logout deletion, security revocation, orphan/scope behavior are explicit and tested | Implementation Steps 2, 5 |
| Logout and security invalidation have an explicit distinction and replay semantics | Implementation Steps 2, 6 |
| Password reset remains hashed, anti-enumerating, rate-limited, canonical-user-bound, and revokes sessions | Implementation Steps 2, 5 |
| Repeated correctness-critical scope is structurally guarded | Implementation Steps 2–3 |
| ANY-504 Step 4 receives explicit `(tenant_id, region, user_id)` paid-access/outbox scope and canonical User lock-anchor semantics from Step 3 | Implementation Steps 2, 6 |
| Historical legal versions cannot be silently rewritten; LegalEntity is not turned into a speculative second versioning subsystem | Implementation Step 3 |
| Registration booleans produce durable exact-version legal evidence atomically, with canonical registration-surface acceptance-text hashes and fail-closed complete document-set validation | Implementation Step 4 |
| Concurrent duplicate registration creates at most one coherent user/evidence/session result and only the exact scoped-email constraint is mapped to the duplicate error | Implementation Step 4 |
| Append-only legal/commercial evidence has a physical target for future PurchaseIntent | Implementation Steps 3, 6 |
| Future PurchaseIntent directly binds same user/account/offer/fingerprint + complete legal evidence; missing linkage/provenance cannot yield paid grant or allowance | Implementation Step 3 contract, Implementation Step 6 handoff |
| Legacy Plan-bound recurring consent is not target authority | Implementation Steps 3, 6 |
| `entrypoint_sessions` retention decision is resolved | Research baseline, Implementation Steps 2, 5, 6 |
| One-contour regions/country-rule/bootstrap ANY-504 Step-4 disposition is resolved | Implementation Steps 1, 6 |
| No provider-independent obligation keeps old Portal trial lifecycle | Implementation Steps 5, 6 |
| Provider-independent survivor tests exist before destructive ANY-504 Step 4 | Implementation Steps 2–5 |
| ANY-504 Step 4 receives exact retained/drop/migration ordering and public-API survivor handoff | Implementation Step 6 |

## Explicitly Deferred to Later `ANY-504` Steps

### ANY-504 Step 4

- destructive pre-production reset;
- new clean Alembic baseline replacing current pre-reset history;
- physical removal of legacy commerce/direct-CloudPayments tables/code owned by the ANY-504 Step-4 scope;
- physical removal of `entrypoint_sessions` and the Step-3-classified legacy acceptance columns;
- RU-only clean bootstrap and removal of foreign-contour/provider-routing seed residue;
- creation of the 15 target external-billing tables, including `external_billing_customers` and `purchase_intents`;
- global `UNIQUE(billing_customer_key)` on `external_billing_customers`, preserving permanent local non-reuse across billing-account configuration changes;
- explicit `(tenant_id, region, user_id)` scope constraints/FKs for `paid_access_states` and `access_invalidation_outbox` exactly as handed off by Step 3, including support for the canonical User-row lock anchor used later by ANY-504 Step 9;
- implementation of the PurchaseIntent → LegalAcceptanceEvent composite FK exactly as handed off by Step 3.

### ANY-504 Step 5

- LBX/provider Phase 0 discovery and test-stand verification;
- provider ID/outer_id semantics and other gated provider facts.

### ANY-504 Step 6

- external catalog/capability manifest projection and commercial mapping publication.

### ANY-504 Step 7

- `billing_customer_key` allocation and customer-slot binding runtime;
- commercial-bound LegalAcceptanceEvent creation from authoritative offer/fingerprint context;
- PurchaseIntent runtime/idempotency and authoritative commercial-bound legal-acceptance creation;
- Widget mint/preparation and external customer/agreement/subscription commands.

### ANY-504 Steps 8–10

- webhook/reconciliation normalized transitions;
- paid-access projection/invalidation, including enforcement that an unlinked/discovered subscription without valid PurchaseIntent + accepted legal/commercial + pinned mapping provenance yields neither paid grant nor allowance;
- Portal ↔ Kernel access contract runtime.

### Separate policy authority

- legal/PII retention durations;
- PII-erasure/anonymization operational workflow;
- session/audit pruning schedule.

## Completion State Expected After ANY-510

After all six steps:

1. Portal identity, session, password-reset, and legal evidence are coherent without any payment provider.
2. The running API derives tenant/contour from deployment configuration rather than caller input.
3. Canonical user/session/recovery/legal scope is structurally guarded in PostgreSQL.
4. Normal logout deletes the current session row; password-reset/security invalidation revokes affected active session rows. Both paths make token replay invalid without inventing durable normal-logout retention.
5. Known password-reset tokens bind to canonical user UUID rather than mutable email identity.
6. Historical legal document versions fail closed against same-version material rewriting.
7. Registration commits User + the complete required exact-version legal evidence + initial session atomically; stored acceptance-text hashes represent the canonical registration statements attested by the API booleans, exact-version reads support approved acceptance surfaces, and concurrent duplicates converge safely.
8. The retained legal model contains a provider-independent acceptance-event anchor capable of directly binding a future PurchaseIntent to the same canonical user and exact configured billing account / offer / accepted commercial fingerprint; generic NULL-commercial events cannot satisfy that purchase binding.
9. The Step-3 handoff fixes explicit `(tenant_id, region, user_id)` paid-access/outbox scope and identifies the canonical User row as the future stable serialization lock anchor required by the updated `ANY-509` contract.
10. The handoff preserves the updated `ANY-509` customer-key invariant: `billing_customer_key` is globally unique across retained customer slots and permanently non-reusable even if configured billing-account scope changes; allocation remains deferred.
11. Legacy Plan/entrypoint recurring consent remains clearly transitional and cannot masquerade as target purchase evidence; the reviewed ANY-509 paid-access predicate cannot be bypassed by an unlinked discovered subscription, primary selection, provider state, or manual review.
12. `entrypoint_sessions`, foreign-contour RU-baseline seeds, direct-provider contour residue, and old Portal trial/commercial state have no unresolved Step-3 retention claim and may be removed by ANY-504 Step 4 under the `ANY-509` reset contract.
13. ANY-504 Step 4 receives an exact schema/migration handoff rather than an open architecture question.
