# Portal Identity, Session, and Legal Baseline

Status: authoritative as-built `ANY-504` Step 3 handoff to Step 4  
Last verified against code: 2026-09-22

## Authority and scope

This document freezes the provider-independent identity, session, recovery,
and legal baseline implemented by `ANY-510`. It is the retained-schema input
to `ANY-504` Step 4. For target billing ownership and persistence, it is
subordinate to [ADR 0005](decisions/0005-external-billing-boundary.md), the
accepted [External Billing Boundary Design](../superpowers/specs/2026-09-15-external-billing-boundary-design.md),
the accepted [Portal <-> Kernel Access Contract Design](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md),
and the reviewed [External Billing Persistence Reset](external-billing-persistence-reset.md).

The current ORM and migrations are the as-built authority for the details
recorded here. Step 4 must consume their final semantics before replacing the
pre-reset Alembic history. This document does not authorize target billing
runtime, provider behavior, or the destructive reset itself.

## Canonical Portal identity and contour scope

`users.id` is the canonical Portal user identity. It is a UUID and is never
derived from or replaced by email, normalized email, phone, display or legal
name, an external provider customer ID, or an external billing `outer_id`.
The serialized Portal/Kernel identity scope is always:

```text
(tenant_id, region, user_id)
```

`tenant_id` and `region` remain explicit, non-null columns on `users`. A
deployed instance obtains their normalized values from the required
`INSTANCE_TENANT_ID` and `INSTANCE_REGION` settings. Registration, login,
password reset, required-document discovery, and later authenticated legal
writes use those settings or the authenticated user's stored scope. Unknown
caller-supplied `tenant_id` or `region` request fields do not select a data
plane. Responses may return the server-derived values as descriptive identity
scope.

Email uniqueness remains scoped by
`UNIQUE(tenant_id, region, email_normalized)`. The same email in two contours
would represent two accounts in two isolated deployments, not one shared
identity. The implemented `UserStatus` vocabulary is deliberately only
`active`. Login, session authentication, and password-reset confirmation all
query for an active user explicitly; adding another status requires deliberate
authentication and recovery semantics.

Application code does not hard-delete canonical users. `users.id` is immutable
and is never reassigned or reused. Restrictive identity and legal FKs prevent a
referenced user from being deleted and orphaning evidence. PII erasure or
anonymization is a different operation: no erasure workflow, replacement
identity, or retention period is defined here. A future approved erasure flow
must preserve the canonical UUID and referential integrity unless separately
approved legal and retention authority changes that rule.

## Sessions and password recovery

### Auth sessions

- A session secret is an opaque random token generated with
  `secrets.token_urlsafe(32)`. Only its SHA-256 hash is stored.
- The implemented TTL is 30 days. A session is valid only when its row exists,
  is not revoked, is not expired, matches the same canonical
  `(user_id, tenant_id, region)`, and resolves to an active user.
- Successful authentication updates `last_seen_at`. Session IP and user agent
  are nullable ancillary security metadata, not identity.
- Normal logout deletes only the selected session row. Replaying that bearer
  token then fails ordinary authentication with HTTP 401 `invalid_session`.
- Security invalidation is intentionally different: password reset sets
  `revoked_at` on every active session in the canonical user's scope. Revoked
  rows remain invalid. No pruning or retention period is invented here.

### Password reset

- A reset secret is generated with `secrets.token_urlsafe(48)`, has a 30-minute
  TTL, and is stored only as a SHA-256 hash.
- A known-user token carries the canonical `user_id` and matching tenant and
  region. Confirmation atomically claims the unused, unexpired token, resolves
  that exact active user and scope, replaces the password, consumes every
  other outstanding reset token for the user, and revokes all active sessions.
- An unknown-email request persists a hashed decoy token with `user_id=NULL`
  and a one-way decoy email key. It sends no email and preserves the same
  external request behavior without creating a fake user.
- Rate-limit state is shared in `password_reset_rate_limits`, scoped by the
  server tenant/region plus account or client IP. The implemented window is 15
  minutes, with maxima of five account requests and twenty IP requests.
- `MagicLinkToken.entrypoint_session_id` is removed. Recovery has no retained
  checkout, provider, trial, or entrypoint dependency.

Raw session and reset secrets, authorization headers, and passwords must not
be persisted or logged.

## Relational scope integrity

The following alternate keys and composite foreign keys are implemented. The
alternate keys exist only as FK targets; they are not additional business
identities.

- `users`: `UNIQUE(id, tenant_id, region)`.
- `auth_sessions(user_id, tenant_id, region)` ->
  `users(id, tenant_id, region) ON DELETE RESTRICT`.
- Known-user `magic_link_tokens(user_id, tenant_id, region)` -> the same user
  key with `ON DELETE RESTRICT`; `user_id=NULL` is reserved for unknown-email
  decoys.
- `legal_entities`: `UNIQUE(id, tenant_id, region)`.
- `document_versions(legal_entity_id, tenant_id, region)` ->
  `legal_entities(id, tenant_id, region) ON DELETE RESTRICT`, with
  `UNIQUE(id, tenant_id, region)` on document versions.
- `legal_acceptance_events(user_id, tenant_id, region)` -> the canonical user
  key with `ON DELETE RESTRICT`.
- `document_acceptances(legal_acceptance_event_id, tenant_id, region,
  user_id)` -> the same event scope with `ON DELETE RESTRICT`.
- `document_acceptances(document_version_id, tenant_id, region)` -> the same
  document-version scope with `ON DELETE RESTRICT`.

## Versioned legal documents

`DocumentVersion` historical identity is
`(tenant_id, region, doc_type, version)`. Once published, its ID, tenant,
region, legal-entity reference, type, version, title, URL path, content hash,
publication and effective timestamps, and `requires_acceptance` value are
immutable. Changed material or seller identity requires a new document
version. `is_active` is the intentional mutable lifecycle selector, and the
partial unique index permits only one active version per tenant, region, and
document type. Legal bootstrap fails closed if an existing version has
different material instead of rewriting it.

`LegalEntity` is contour-scoped current operator metadata, not a second
historical version model. Its current descriptive, tax, address, contact, and
status metadata may be maintained. Historical acceptance truth comes from the
immutable `DocumentVersion` and content hash referenced by acceptance
evidence; readers must not reinterpret old acceptance by dereferencing current
mutable `LegalEntity` metadata. Replacing the legal person requires a new
`LegalEntity` and new affected document versions.

## Registration and acceptance-text integrity

Registration requires exactly the active, effective `privacy`, `pd_consent`,
and `offer` versions. It fails closed for a missing, extra required
non-recurring, duplicate, unmapped, or not-yet-effective registration document.
`recurring_consent` and non-required informational documents are not accepted
at registration.

The two public booleans map to durable evidence as follows:

- `personal_consent=true` accepts both the exact `privacy` and `pd_consent`
  versions using the exact backend-owned Russian statement in
  `REGISTRATION_PERSONAL_CONSENT_TEXT`: consent to personal-data processing
  under the Personal Data Consent and Privacy Policy. Its UTF-8 SHA-256 hash is
  `fa093c89e1a09dd82691c41a5dfb51298be1680e8e8462e138280fbcf61788b3`.
- `offer_consent=true` accepts the exact `offer` version using the canonical
  backend-owned Russian statement in `REGISTRATION_OFFER_CONSENT_TEXT`:
  acceptance of the Public Offer and acknowledgement of the cancellation and
  refund terms. Its UTF-8 SHA-256 hash is
  `4453768958dc84a86fddc9cb07903acc150d2d1a6d64c5486f0b4372552b230f`.

One non-commercial `LegalAcceptanceEvent`, its three
`DocumentAcceptance` rows, the canonical `User`, and the initial
`AuthSession` commit in one transaction with one acceptance timestamp. A
failure leaves none durable. The scoped email unique constraint is the final
concurrency guard: two concurrent registrations produce one complete winner;
the loser rolls back its entire user/session/legal result and receives the
duplicate-email error.

`acceptance_text_hash` proves the actual approved acceptance surface, not one
universal statement for a document version. The generic authenticated legal
surface uses the per-document statement returned by the legal API; registration
uses the statements above. Exact-version accepted-state queries recognize the
approved hashes for both surfaces. Thus the same immutable document version
may be accepted through more than one approved surface without weakening
server-side hash validation.

## Legal acceptance physical contract

`LegalAcceptanceEvent` represents one atomic acceptance action. Its implemented
fields are:

```text
id UUID primary key
tenant_id text not null
region text not null
user_id UUID not null
external_billing_account_id text null
billing_offer_id text null
accepted_commercial_fingerprint text null
accepted_at timestamptz not null
ip inet null
user_agent text null
created_at timestamptz not null
```

The commercial triplet is either entirely NULL for registration and generic
legal actions or entirely non-null and non-empty for a future purchase-bound
event. `accepted_at` is the canonical action timestamp. `created_at` is the
persistence timestamp. IP and user agent are ancillary security/audit metadata:
they are not acceptance identity or commercial authority and may only be
cleared by a future approved privacy process, never changed or repopulated.
This document defines no retention duration.

The event has alternate keys `UNIQUE(id, tenant_id, region, user_id)` for
same-scope document children and
`UNIQUE(id, user_id, external_billing_account_id, billing_offer_id,
accepted_commercial_fingerprint)` for the future purchase FK. These are
relational targets, not additional event identities.

`DocumentAcceptance` is one exact versioned document accepted in that event,
with at most one row per `(legal_acceptance_event_id, document_version_id)`.
Repeated acceptance is append-only: each successful generic
`POST /api/legal/acceptances` call creates a new event and row; there is no
hidden deduplication or idempotency key.

The clean Step-4 retained `DocumentAcceptance` subset is exactly:

```text
id
legal_acceptance_event_id
tenant_id
region
user_id
document_version_id
acceptance_kind
acceptance_text_hash
created_at
```

The current ORM still contains transitional checkout fields that Step 4 must
remove after deleting their callers: `guest_id`, `entrypoint_session_id`,
`entrypoint_type`, `entrypoint_value`, `source_url`, arbitrary `metadata`
(including legacy `plan_id`), duplicated `doc_type` and `version`, and the
per-document duplicates `accepted_at`, `ip`, and `user_agent`. Target readers
derive document type/version from immutable `DocumentVersion` and action time
and ancillary metadata from the event.

### PostgreSQL-only invariants Step 4 must recreate

SQLAlchemy metadata does not express the Step-3 trigger behavior. The fresh
Step-4 baseline must install equivalent functions and triggers even though it
deletes migrations `20260921_0006` and `20260921_0007` with the rest of the
pre-reset history:

1. `guard_legal_acceptance_event_evidence` on UPDATE or DELETE of
   `legal_acceptance_events` rejects every DELETE; rejects changes to `id`,
   tenant, region, user, any commercial-triplet field, `accepted_at`, or
   `created_at`; and permits `ip` or `user_agent` only to transition from a
   value to NULL. NULL-to-value and value-to-different-value transitions are
   rejected.
2. `guard_document_acceptance_evidence` on UPDATE or DELETE of
   `document_acceptances` rejects both operations unconditionally. Rows are
   append-only.
3. `guard_document_version_material` before UPDATE of `document_versions`
   rejects changes to `id`, tenant, region, legal entity, type, version, title,
   URL path, content hash, publication/effective timestamps, or
   `requires_acceptance`. It permits lifecycle updates such as `is_active` and
   the corresponding `updated_at` change.

Equivalent trigger/function names are acceptable in the fresh baseline only
if these exact semantics and their PostgreSQL tests remain intact.

## Public API survivor contract

Step 4 retains the provider-independent registration, login, logout,
password-reset request/confirmation, authenticated legal acceptance, required
legal-document discovery, and core session identity behavior. Registration,
login, recovery, and legal discovery remain server-scoped as described above.

Core `GET /api/auth/session` continues to authenticate the bearer session and
return `authenticated: true` plus the canonical user's server-derived
`tenant_id`, `region`, `user_id`, and email. Step 4 removes its optional
`product` input and billing-derived `product_state` output. It also removes the
checkout-intent, payment-status, Portal catalog, and old account-subscription
contracts and their frontend callers. Plan-bound recurring-consent and legacy
entrypoint fields on the generic legal request are removed or adapted with
their checkout consumers; they are not part of the retained legal contract.

## Future purchase evidence

Step 4 creates the mandatory purchase binding exactly as follows:

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

A purchase-compatible event must be written atomically from an authoritative
offer and commercial fingerprint and contain the complete set of required
versioned `DocumentAcceptance` rows. Registration and generic events have a
NULL commercial triplet and cannot satisfy this FK. Legacy `Plan.id` consent,
arbitrary JSON, or a lone generic acceptance UUID is not purchase evidence.

Consistent with the reviewed `ANY-509` predicate at `9830ca1`, an external
subscription without a valid linked PurchaseIntent, this immutable complete
legal/commercial evidence, and pinned mapping provenance is commercially
ineligible and contributes neither a paid product grant nor a purchased
allowance. Provider state, primary selection, and manual review cannot
manufacture or bypass missing provenance.

## External billing identity and paid-access scope

There is no `external_billing_accounts` table. The configured
`external_billing_account_id` is an opaque, stable, non-secret scope value.
The future `billing_customer_key` is an opaque, immutable, non-PII allocation
identity, globally unique across every retained customer slot and permanently
reserved locally once allocated. Changing billing-account configuration never
makes a prior key reusable. It must not be derived from email, phone, names,
provider IDs, or mutable provider state. Step 4 creates the customer slot and
global uniqueness; Step 7 owns allocation and binding runtime.

Step 4 must put explicit, non-null `tenant_id`, `region`, and `user_id` columns
on both `paid_access_states` and `access_invalidation_outbox`, with:

```text
FOREIGN KEY (user_id, tenant_id, region)
  REFERENCES users(id, tenant_id, region)
  ON DELETE RESTRICT

UNIQUE (tenant_id, region, user_id)
```

Future AccessSnapshot serialization uses the identical three-part semantic
scope. The canonical `User` row is the stable `SELECT ... FOR UPDATE` lock
anchor that Step-9 writers acquire before deriving and committing a semantic
access revision. This handoff defines the physical scope and lock anchor; it
does not implement paid-access state, locking, or serialization runtime.

## Step-4 retained, cleanup, and install handoff

After revalidating the no-production reset premise, Step 4 must preserve these
retained tables using the as-built contract above:

1. `regions`;
2. `country_region_rules`, after the cleanup below;
3. `users`;
4. `auth_sessions`;
5. `magic_link_tokens`;
6. `password_reset_rate_limits`;
7. `legal_entities`;
8. `document_versions`;
9. `legal_acceptance_events`;
10. `document_acceptances` in its clean retained subset.

Step 4 must also:

- remove `entrypoint_sessions`; Step 3 found no provider-independent identity,
  legal, or origin purpose for it, and no replacement origin table is created;
- remove the transitional `DocumentAcceptance` columns listed above after
  removing legacy checkout consumers;
- remove foreign `eu`/DE/ES seed rows from the clean RU data plane and retain
  only the configured contour's region, country membership, and legal bootstrap;
- remove `country_region_rules.default_payment_provider` and
  `allow_region_override`; direct-provider routing is not contour authority and
  a client cannot override the instance data plane;
- preserve provider-independent local country membership, market enablement,
  strict validation, and document-set configuration where still used;
- remove the old Portal trial/commercial lifecycle. Identity, session,
  recovery, and legal behavior has no provider-independent dependency on it;
- preserve core `/api/auth/session` while applying the public-contract removals
  above; and
- install the 15 approved target billing tables and only the Step-4-safe
  constraints defined by the persistence-reset handoff, without later-step
  runtime.

Step 4 replaces the entire pre-reset Alembic history present when it begins
with one fresh first-install baseline and one head. Migrations
`20260921_0006` and `20260921_0007` are transitional upgrade history, not a
template to copy mechanically. The clean baseline must reconstruct every
retained column, key, index, legal bootstrap rule, and PostgreSQL-only trigger
semantic recorded here.

The required removal order remains: neutralize public/backend/frontend
consumers; remove legacy runtime, integration, provider, configuration, and
persistence consumers; install retained and approved target models; replace
the migration chain and bootstrap; replace affected tests; regenerate schema
and OpenAPI artifacts; then prove no removed dependency remains.

## Provider-independent regression matrix

These tests are the survivor baseline. Step 4 may adapt fixtures and schema
expectations, but it must preserve each provider-independent proof.

| Proof | Owning tests |
| --- | --- |
| Server-authoritative registration/login and legal discovery scope | `apps/api/tests/test_api.py::test_same_email_foreign_client_scope_cannot_create_foreign_contour_user`, `::test_register_and_login_foreign_client_scope_cannot_select_foreign_contour_user`, `::test_legal_required_documents_use_instance_scope` |
| Canonical UUID user, hashed initial session, event-backed three-document registration | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_registration_persists_canonical_identity_hashed_session_and_legal_event` |
| Atomic failure rollback and concurrent duplicate registration | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_registration_failure_rolls_back_identity_session_and_legal_evidence`, `::test_concurrent_duplicate_registration_keeps_one_complete_result` |
| Normal logout deletes one row; revoked/expired sessions remain invalid | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_normal_logout_deletes_only_the_selected_session`, `apps/api/tests/test_api.py::test_security_revoked_and_expired_auth_sessions_remain_invalid` |
| Unknown-email reset anti-enumeration, hash-only storage, canonical-user binding, token consumption, security revocation, and shared throttling | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_unknown_email_password_reset_uses_hashed_decoy_without_user_binding`, `::test_password_reset_binds_canonical_user_and_revokes_security_state`; `apps/api/tests/test_password_reset_persistence_postgres.py::test_password_reset_rate_limit_upsert_returns_persisted_attempt_count` |
| User/session/reset/legal relational scope and restrictive deletion | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_auth_session_scope_must_match_canonical_user`, `::test_known_reset_token_scope_must_match_canonical_user`, `::test_canonical_user_delete_is_restricted_by_auth_session`, `::test_legal_event_scope_must_match_canonical_user`, `::test_document_version_scope_must_match_legal_entity`, `::test_document_acceptance_scope_must_match_event_user`, `::test_document_acceptance_scope_must_match_document_version` |
| Event immutability, ancillary clearing only, append-only document acceptance, immutable same-version material with mutable active selection | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_core_evidence_cannot_be_updated_or_deleted`, `::test_legal_acceptance_event_audit_metadata_may_only_be_cleared`, `::test_document_acceptance_rows_are_append_only`, `::test_document_version_material_is_immutable_but_active_selection_may_change` |
| Commercial triplet all-or-none/non-empty and complete-triplet support | `apps/api/tests/test_identity_legal_persistence_postgres.py::test_legal_acceptance_event_commercial_triplet_is_all_or_none_and_nonempty`, `::test_legal_acceptance_event_accepts_a_complete_commercial_triplet` |
| Every successful generic exact-version acceptance is a new event rather than a hidden deduplication | `apps/api/tests/test_api.py::test_required_document_acceptance_creates_a_new_noncommercial_event_per_call` |
| Migration backfill/fail-closed identity and legal evidence | `apps/api/tests/test_alembic_postgres.py::test_identity_scope_migration_backfills_only_exact_known_users`, `::test_legal_acceptance_migration_backfills_one_noncommercial_event_per_user_acceptance`, `::test_legal_acceptance_migration_rejects_evidence_without_a_canonical_user` |
| Active-only user vocabulary and deliberate future auth semantics | `apps/api/tests/test_model_enums.py::test_user_status_vocabulary_requires_explicit_auth_semantics`, `apps/api/tests/test_api.py::test_auth_sessions_and_login_require_active_user` |
| No `external_billing_accounts` ORM/FK; no billing-customer/PII cross-system identity ownership; no recovery dependency on entrypoint, commerce, provider, or trial state | `apps/api/tests/test_architecture.py::test_external_billing_accounts_orm_table_and_fk_targets_are_forbidden`, `::test_identity_legal_rejects_billing_customer_and_cross_system_identity_ownership`, `::test_identity_recovery_rejects_entrypoint_commerce_provider_and_trial_dependencies`, `::test_magic_link_token_has_no_entrypoint_session_binding` |
| Registration statement/hash mapping, canonical legal source hashes, and immutable-version bootstrap behavior | `apps/api/tests/test_api.py::test_seeded_registration_documents_are_accepted_atomically`, `::test_registration_offer_statement_hash_matches_checkout_checkbox`, `::test_legal_seed_is_idempotent_for_exact_immutable_versions`, `::test_legal_seed_fails_closed_on_same_version_material_mismatch`, `::test_legal_seed_keeps_operator_metadata_separate_from_historical_document_identity`; `apps/api/tests/test_legal_manifest.py::test_legal_manifest_hashes_match_source` |

## Explicit deferrals

This baseline does not implement the Step-4 reset or target tables. It also
does not implement LBX Phase 0 evidence, capability/catalog import, mapping
publication, commercial acceptance writing, PurchaseIntent/customer binding,
Widget flow, webhooks, reconciliation, paid-access derivation, invalidation
delivery, AccessSnapshot transport, or Platform Kernel changes. Those remain
owned by their later `ANY-504` steps. No legal or PII retention duration is
defined without Legal/Finance authority.
