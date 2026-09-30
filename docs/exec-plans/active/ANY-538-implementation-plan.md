# ANY-538 — Provider-Independent Account Verification & Authentication Security Baseline

## Plan Overview

- Parent: `ANY-504`
- Baseline: current `ANY-533` branch / PR #125
- Execution: sequential, one step per chat
- Steps / commits: **4**
- LBX dependency: none
- Successor: `ANY-539`
- Goal: close only the identity/auth gaps that later external billing must safely rely on.

Final handoff invariant:

```text
authenticated Portal user
    => active canonical User
    + verified mailbox ownership
    + retained provider-independent legal baseline
```

This is not a general security-hardening program.

## Working baseline

Implementation starts from the current `ANY-533` branch / PR #125 baseline.

Validated predecessor head at final plan review:

```text
ANY-533
PR #125
head SHA: 1b3cc1ebd9306b638b9132579499892b01dcc08e
```

Use a separate ANY-538 working branch. Do not push ANY-538 commits into PR #125.

If ANY-533 receives review-fix commits before a later ANY-538 step:

1. bring only that predecessor delta into the ANY-538 branch;
2. inspect only the new delta;
3. continue if it does not materially change auth/session/reset/locale/email/persistence/deployment assumptions.

Do not repeat broad predecessor research.

---

# Global Execution Rules

For the selected step:

1. read that step in full;
2. read only plan-level sections explicitly referenced by that step;
3. inspect only listed files and immediate directly-called helpers;
4. inspect focused tests covering changed behavior.

Do not reread the whole plan, other step prompts, all Linear tickets, ADRs, standards, billing/LBX code, or unrelated repository areas.

If current code materially contradicts the approved plan, stop and report the contradiction.

Implement one step only. Do not work ahead.

The implementation model does **not** run verification. Do not run tests, lint, typecheck, builds, Playwright, architecture/docs checks, or equivalents.

Implementation-required write commands explicitly allowed by a step are permitted.

After implementation run formatting only:

```bash
cd apps/api
python -m ruff format <changed-normal-python-files>
```

Format only changed ordinary Python files. Alembic/generated/web files keep existing local formatting manually. Do not introduce Prettier or `eslint --fix`.

Do not stage, commit, or push.

After every step report:

- changed files;
- concise implementation summary;
- important invariants;
- formatting actually run;
- exact manual verification commands;
- contradictions/follow-ups.

---

# Locked Minimal Decisions

## Passwords

Keep the existing product password contract unchanged:

```text
minimum = 8
maximum = 128
```

Do **not** add:

- 15-character minimum;
- common-password/SecLists blocklist;
- NFC/casefold policy;
- composition rules;
- new password-strength UX;
- external password/breach services.

Change storage only:

```text
new writes -> Argon2id
legacy PBKDF2 -> verify -> successful proof -> rehash to Argon2id
```

Use:

```text
argon2-cffi==25.1.0
memory_cost = 19456 KiB
time_cost = 2
parallelism = 1
hash_len = 32
```

Malformed/unsupported hashes fail authentication safely.

No password string normalization change.

## Verified email

After ANY-538:

```text
email_verified_at != NULL
```

means proven mailbox ownership.

Registration retains the current request:

```text
email + password + existing registration legal consents
```

Successful new registration creates:

```text
active User
email_verified_at = NULL
last_login_at = NULL
current password hash
existing registration legal evidence
one EMAIL_VERIFICATION token
no AuthSession
```

Response:

```json
{"status":"verification_required"}
```

Duplicate registration returns the same public response, creates nothing, creates no session, and does not automatically resend verification.

The retained registration legal evidence remains **non-commercial**. It does not authorize a future purchase and cannot satisfy the later PurchaseIntent purchase-bound legal FK/acceptance contract. ANY-538 does not redesign purchase legal evidence.

Verification requires:

```text
valid verification token + correct current account password
```

Success, under canonical User lock:

```text
revalidate/claim token
verify current password
set email_verified_at
invalidate sibling verification tokens
create first AuthSession
set last_login_at
commit atomically
```

This prevents a mailbox owner from accidentally activating a password chosen by a pre-registration attacker.

Historical predecessor `email_verified_at` values are not proof. Forward migration revokes their active sessions and clears those timestamps.

Session authentication requires an active User with non-null `email_verified_at`.

## Verification token / resend

Reuse `magic_link_tokens`.

Add:

```text
MagicLinkPurpose.EMAIL_VERIFICATION
```

Token:

```text
secrets.token_urlsafe(48)
SHA-256 stored
24h TTL
single-use
```

URL:

```text
/{routeLocale}/verify-email#token=<secret>
```

Browser reads the fragment, removes it immediately with `history.replaceState`, keeps it memory-only, asks for the current password, and verifies only on explicit user action.

Endpoints:

```text
POST /api/auth/email-verification/request
POST /api/auth/email-verification/confirm
```

Resend response is generic for unknown / verified / unverified accounts:

```json
{"status":"accepted"}
```

Only an unverified account receives a fresh verification token/email.

Confirmation body:

```json
{"token":"...","password":"..."}
```

Success:

```json
{"status":"verified","token":"...","user":{...}}
```

Wrong / expired / already-used verification tokens all use:

```text
400 invalid_or_expired_verification_token
```

No separate `already_used` public state.

## Password reset

Password reset remains credential recovery.

For an unverified User:

```text
change password
revoke sessions
invalidate verification tokens
clear login-account-failure state
keep email_verified_at = NULL
create no session
```

The user then uses normal resend + verification with the new password.

Already verified Users retain their existing `email_verified_at`.

## Abuse controls

Add one dedicated table:

```text
authentication_rate_limits
```

Minimal shape:

```text
rate_limit_key
count
window_start
expires_at
created_at
updated_at
```

Reuse the current password-reset fixed-window SQL style. Do not create a generic rate-limit framework.

Use distinct key namespaces so unrelated controls cannot collide in the shared table:

```text
registration:account:{tenant}:{region}:{normalized_email}
registration:ip:{tenant}:{region}:{client_ip}

verification:account:{tenant}:{region}:{normalized_email}
verification:ip:{tenant}:{region}:{client_ip}

login:ip:{tenant}:{region}:{client_ip}
login:account:{tenant}:{region}:{normalized_email}
```

Do not expose raw bucket keys as metric labels or logs.

Registration / verification resend:

```text
account 5 / 15m
source IP 20 / 15m
```

Login source:

```text
50 / 15m
```

Login account failures use a 15-minute observation window.

After 10 accepted invalid credentials:

```text
failure 10 -> 1s
failure 11 -> 2s
failure 12 -> 4s
failure 13 -> 8s
failure 14 -> 16s
failure 15 -> 32s
failure 16+ -> 60s cap
```

Requests rejected during active cooldown do not mutate failure state or extend cooldown.

Correct credentials clear account failure state. Correct-but-unverified credentials clear it before returning `email_verification_required`. Successful password reset clears it.

Unknown/no-hash login performs one dummy current Argon2 verify. Wrong legacy PBKDF2 performs legacy verify + one dummy current Argon2 verify. No sleeps/random delay.

## Production prerequisites

Production verification requires working email configuration.

Reject production config with:

```text
empty SMTP_HOST
SMTP_USE_TLS=false
invalid SMTP_FROM_EMAIL
invalid SMTP_PORT
only one of SMTP_USERNAME/SMTP_PASSWORD configured
```

No SMTP readiness probe, queue, worker, or outbox.

Transient SMTP outage does not fail readiness; user remains unverified and can resend.

IP-based security requires bounded proxy trust.

Reject production `FORWARDED_ALLOW_IPS` values:

```text
empty
*
0.0.0.0/0
::/0
```

Use one explicit Caddy/API proxy range, a dedicated Caddy/API network, and `api:8000`. No custom X-Forwarded-For parser.

Minimal edge headers only:

```text
Strict-Transport-Security: max-age=31536000
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
```

No CSP/provider origins, Permissions-Policy, COOP/COEP/CORP, HSTS preload/includeSubDomains, or Server-header work.

## ANY-539 boundary

ANY-538 does not redesign Portal shell, header/footer, global navigation, catalog/product pages, mobile navigation, or broad responsive/accessibility presentation.

Do not add a dedicated viewport/mobile-hardening subtask. Existing web/E2E coverage may be extended only where necessary to prove the new verification/auth behavior itself. CSS changes are out of scope unless a concrete defect blocks the newly introduced verification flow.

---

# Step 1 — Password + Security Persistence Foundation

## Goal

Create all storage primitives in one pass so ORM/migration/password research is not repeated in separate chats.

## Inspect only

```text
apps/api/pyproject.toml
apps/api/uv.lock
apps/api/app/domains/identity/passwords.py
apps/api/app/domains/identity/services/auth.py
apps/api/app/models/identity.py
apps/api/app/models/enums.py
apps/api/app/models/__init__.py
apps/api/app/infrastructure/persistence/password_reset.py
apps/api/app/infrastructure/queries/identity.py
apps/api/alembic/versions/20260924_0001_clean_first_install.py
apps/api/alembic/versions/<new-any-538-migration>.py
apps/api/tests/test_model_enums.py
apps/api/tests/test_alembic_postgres.py
apps/api/tests/test_api_identity_session.py
apps/api/tests/test_identity_legal_persistence_postgres.py
apps/api/tests/test_password_reset_persistence_postgres.py
```

Create a focused auth-rate-limit persistence module if needed.

## Implement

- pin `argon2-cffi==25.1.0`;
- update lock with allowed write command `npm run lock:api`;
- Argon2id new writes;
- PBKDF2 verify-only compatibility;
- successful legacy proof rehashes to Argon2;
- Argon2 rehash check;
- malformed hashes fail safely;
- password validation remains **8–128 unchanged**;
- add `EMAIL_VERIFICATION`;
- add `authentication_rate_limits`;
- implement atomic fixed-window increment/reset, login-account state read/record, bucket clear, expired-row prune;
- login-account failure recording increments only attempts that actually reach password verification; requests rejected during active cooldown do not call the record operation and do not move `updated_at`;
- add canonical active User `FOR UPDATE` query;
- forward migration revokes sessions for predecessor false-verified Users and clears `email_verified_at`;
- do not edit clean first-install migration;
- downgrade never restores false verification or revoked sessions.

Persistence helpers may mutate/flush but never own outer commit/rollback.

## Out of scope

Routes, verification behavior, limiter callers, SMTP, frontend, password-policy changes.

## AI prompt

Implement only Step 1 of ANY-538.

Read this step plus the Passwords, Verified Email historical cleanup, and Abuse Controls sections only.

Inspect only the listed files and direct helpers.

Implement Argon2id with the locked parameters while leaving password validation exactly 8–128. Preserve legacy PBKDF2 verification and opportunistic rehash after successful proof. Do not add password normalization, common-password checks, or frontend changes.

Add EMAIL_VERIFICATION, one minimal authentication_rate_limits table, and only the persistence primitives required by Step 2. Follow the existing password-reset limiter SQL style; no generic framework. Persistence never commits/rolls back the outer transaction.

Create one forward migration after the clean baseline. Revoke active sessions for historical false-verified Users and clear their email_verified_at. Do not modify the clean first-install migration and do not restore these values/sessions on downgrade.

`npm run lock:api` is allowed.

Do not run verification commands. Run Ruff formatting only on changed ordinary Python files. Do not stage/commit/push.

Report changed files, password compatibility, schema/migration behavior, persistence operations, formatting, and manual verification commands.

Stop if current baseline proves predecessor email_verified_at values came from real mailbox verification.

## Manual verification

```bash
python -m pytest -p no:cacheprovider   apps/api/tests/test_api_identity_session.py   apps/api/tests/test_model_enums.py   -k "password or login or hash or enum" -q

npm run lock:check:api
```

```bash
python scripts/repo.py test-db up

python -m pytest -p no:cacheprovider   apps/api/tests/test_alembic_postgres.py   apps/api/tests/test_identity_legal_persistence_postgres.py   apps/api/tests/test_password_reset_persistence_postgres.py   -q

python scripts/repo.py test-db stop
```

Production-container benchmark:

```bash
docker build \
  --target production \
  -f apps/api/Dockerfile \
  -t payments-portal-api:any-538-password-benchmark \
  .
```

Then:

```bash
docker run --rm payments-portal-api:any-538-password-benchmark \
  python -c 'import resource,sys,time; sys.path.insert(0, "/app/apps/api"); from app.domains.identity.passwords import hash_password, verify_password; p="AnytoolAI benchmark password 2026"; t=time.perf_counter(); h=hash_password(p); hs=time.perf_counter()-t; t=time.perf_counter(); ok=verify_password(p,h); vs=time.perf_counter()-t; print(f"hash_seconds={hs:.4f} verify_seconds={vs:.4f} max_rss_kib={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}"); assert ok'
```

Record hash/verify time and RSS. If normal hash/verify approaches ~1 second or memory pressure is unacceptable, stop and revalidate parameters.

## Expected result

Password storage and all database primitives needed by the runtime are ready; no public auth flow changed yet.

## Commit

```text
feat(identity): establish auth security foundation
```

---

# Step 2 — Verified Email + Authentication Runtime

## Goal

Implement the backend invariant later billing relies on and activate the minimal abuse protections in the same auth pass.

## Inspect only

```text
apps/api/app/domains/identity/router.py
apps/api/app/domains/identity/password_reset.py
apps/api/app/domains/identity/services/auth.py
apps/api/app/domains/identity/services/password_reset.py
apps/api/app/domains/identity/services/email_verification.py  # create if a focused verification service is clearer
apps/api/app/domains/identity/errors.py
apps/api/app/http/errors.py
apps/api/app/infrastructure/queries/identity.py
apps/api/app/infrastructure/persistence/password_reset.py
apps/api/app/infrastructure/persistence/<auth-rate-limit-module>
apps/api/app/infrastructure/persistence/<verification-module>  # create only if a focused separate module is clearer; otherwise extend a directly relevant identity persistence module
apps/api/app/core/email.py
apps/api/app/core/password_reset_email.py
apps/api/app/core/email_verification_email.py  # create for verification-specific localized templates/delivery
apps/api/app/core/observability.py
apps/api/app/generated/locales.py
apps/api/tests/test_api_identity_session.py
apps/api/tests/test_api_password_reset.py
apps/api/tests/test_email.py
apps/api/tests/test_api_email_verification.py
apps/api/tests/test_auth_rate_limits_postgres.py
apps/api/tests/test_email_verification_persistence_postgres.py
```

Use existing registration legal helpers only through the retained registration flow. Do not redesign legal architecture.

## Implement

Registration:

After normal request/password/required-consent validation and before account lookup/state branching:

```text
current email/password/consents request
-> persist registration source/account security accounting
-> active unverified User
-> existing non-commercial registration legal evidence
-> verification token
-> commit User + legal evidence + hash-only token
-> schedule localized verification email only after commit
-> no session
-> verification_required
```

Normalize registration `Accept-Language` through the existing ANY-533 Presentation locale helper. Locale is delivery metadata only and is not added to identity/business JSON.

Duplicate valid registration returns the same response and creates/sends nothing. A concurrent uniqueness loser rolls back its User/legal/token attempt, returns the same generic response, and must not send a second verification email.

Verification resend:

- generic response;
- account/source limiter before state branching;
- unverified User locked;
- old verification tokens invalidated;
- fresh token committed;
- email scheduled only after commit.

Confirmation uses the existing password input contract (`8–128`) and no new password-strength policy.

```text
candidate token read
-> canonical User FOR UPDATE
-> token revalidation
-> current password verification
-> opportunistic legacy PBKDF2 -> Argon2 rehash if required
-> conditional claim
-> email_verified_at set
-> sibling tokens invalidated
-> first AuthSession + last_login_at
-> commit
```

Login/session/reset semantics follow the locked decisions.

Activate:

- registration/resend `5 account / 20 source / 15m`;
- login source `50/15m`;
- progressive login-account cooldown;
- dummy Argon2 unknown-user path.

Limiter/failure state causing `401/403/429` must be durably committed by Application/service code before returning the public error. Persistence helpers never commit.

Reuse ANY-533 locale normalization for both initial registration verification delivery and resend. Verification email covers EN/FR/IT/DE/ES/RU/PT with `pt -> pt-BR`.

No PII/high-cardinality metric labels.

## Out of scope

Frontend verification page, SMTP/proxy deployment changes, shell/mobile/product work.

## AI prompt

Implement only Step 2 of ANY-538.

Read this step plus Verified Email, Verification Token/Resend, Password Reset, and Abuse Controls only.

Inspect only the listed auth/reset/persistence/email files and direct helpers. Focused verification service/email modules explicitly listed as `create` are allowed; do not create generic auth/mail frameworks. Do not inspect billing/provider code.

Change registration to persist its source/account limiter accounting first, then create the existing User + non-commercial registration legal evidence + EMAIL_VERIFICATION token, but no email_verified_at, last_login_at, or AuthSession. Commit User + legal evidence + hash-only token before scheduling the localized email. Registration uses the existing ANY-533 Accept-Language normalization. Return verification_required. Duplicate/concurrent-loser registration returns the same response and creates/sends nothing.

Implement resend and confirmation exactly as specified. Confirmation requires token + current password and must lock/revalidate the canonical User before claiming the token. If the password is legacy PBKDF2, successful verification rehashes it to current Argon2 in the same successful transaction. Successful verification creates the first session atomically.

Correct-password login of an unverified User returns email_verification_required and creates no session. Session resolution rejects unverified Users.

Unverified password reset changes the password but remains unverified, invalidates verification tokens, revokes sessions, and clears login failure state.

Activate only the defined registration/resend/login abuse controls and dummy Argon2 path. Security accounting must survive 401/403/429 through Application-owned transaction boundaries. No generic framework and no arbitrary sleeps.

Reuse existing locale normalization and add seven localized verification emails.

Do not run verification commands. Ruff-format only changed ordinary Python files. Do not stage/commit/push.

Report changed files, transactions/locking, limiter thresholds/commit points, reset interaction, locale delivery, formatting and manual verification commands.

## Manual verification

```bash
python -m pytest -p no:cacheprovider \
  apps/api/tests/test_api_identity_session.py \
  apps/api/tests/test_api_password_reset.py \
  apps/api/tests/test_api_email_verification.py \
  apps/api/tests/test_email.py \
  -q
```

```bash
python scripts/repo.py test-db up

python -m pytest -p no:cacheprovider \
  apps/api/tests/test_auth_rate_limits_postgres.py \
  apps/api/tests/test_email_verification_persistence_postgres.py \
  -q

python scripts/repo.py test-db stop
```

## Expected result

Backend registration, verification, login/session, reset, timing and rate-limit behavior form one complete provider-independent account-security runtime.

## Commit

```text
feat(identity): require verified email for authentication
```

---

# Step 3 — Production Boundary + Web Verification Flow

## Goal

Complete the deployable runtime in one final implementation pass: production mail/IP prerequisites plus browser verification and focused changed-surface regression.

## Inspect only

Backend/deployment:

```text
apps/api/app/core/settings.py
apps/api/Dockerfile
docker-compose.prod.yml
.env.production.example
deploy/caddy/Caddyfile.prod
apps/api/tests/test_deployment_contract.py
apps/api/tests/test_email.py
apps/api/tests/test_api_health_system.py
```

Web:

```text
apps/web/src/shared/api/auth.ts
apps/web/src/shared/ui/AuthForm.tsx
apps/web/src/shared/ui/HeaderAccount.tsx
apps/web/src/shared/ui/auth-errors.ts
apps/web/src/features/checkout/CheckoutClient.tsx
apps/web/src/features/password-reset/PasswordResetRequestClient.tsx
apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx
apps/web/src/shared/ui/LocaleSwitcher.tsx
apps/web/src/app/[locale]/verify-email/page.tsx
apps/web/src/features/email-verification/*
apps/web/src/generated/locales.ts
apps/web/src/messages/*.json
apps/web/e2e/auth-legal-links.spec.ts
apps/web/e2e/password-reset.spec.ts
apps/web/e2e/account-logout.spec.ts
apps/web/e2e/email-verification.spec.ts
```

Inspect CSS only if focused E2E exposes a concrete defect.

## Implement

Production:

- required secure SMTP configuration;
- no SMTP readiness/worker/outbox;
- explicit trusted `FORWARDED_ALLOW_IPS`;
- add a dedicated `api_proxy` network shared only by Caddy and API;
- keep Caddy + web on the existing web-facing `edge` network;
- remove API from `edge`; API remains on `backend` + `api_proxy`;
- attach Caddy to both `edge` + `api_proxy`;
- Caddy uses `api:8000` over `api_proxy`;
- only four locked edge headers.

Web:

- split login and registration response contracts;
- registration sends route-derived `Accept-Language`, handles `verification_required`, and stores no session;
- localized check-email guidance includes an explicit resend action using the registration email;
- login `403 email_verification_required` transitions to the same verification-required/resend recovery state instead of a dead-end generic error;
- `/[locale]/verify-email`;
- read fragment -> remove immediately -> memory-only;
- require password + explicit Verify;
- invalid/expired/used token UX provides a generic retry/resend path; if the page no longer knows the email, ask the user to enter it for resend rather than persisting it as hidden verification state;
- successful confirmation stores the existing bearer session key/event;
- resend sends route-derived `Accept-Language`;
- no locale switch on verification route;
- all seven message catalogs;
- password-reset success may return to normal sign-in; if that User is still unverified, the next login's `email_verification_required` state provides the resend path;
- password UX remains the existing 8–128.

No shell/catalog/product/header/footer/mobile-nav or dedicated viewport-hardening changes.

## AI prompt

Implement only Step 3 of ANY-538.

Read this step plus Production Prerequisites and ANY-539 Boundary only.

Inspect only the listed deployment/web files. Inspect CSS only after a focused test exposes a concrete defect.

Implement production SMTP validation and explicit Caddy/API IP trust. Add a dedicated `api_proxy` network shared only by Caddy and API; keep Caddy+web on `edge`, remove API from `edge`, keep API on `backend`, attach Caddy to both networks, and proxy API through `api:8000`. Add only the four approved edge headers. No readiness probe, worker, CSP, Permissions-Policy, or extra hardening.

Split login/registration response decoding. Registration sends route-derived Accept-Language, handles verification_required without storing a session, and exposes an explicit generic resend action.

Map login `email_verification_required` to the same recovery state so migrated historical Users are not left at a dead-end error.

Add the localized verify-email route. Read/remove the fragment immediately, keep token memory-only, require current password and explicit Verify, and establish the existing browser session only after success. Invalid/expired/used token UX must provide a generic resend path; ask for email when necessary rather than persisting hidden verification state.

Reuse existing locale mapping/Accept-Language. Keep password behavior unchanged at 8–128.

Add focused verification E2E only for the new registration/verification/recovery behavior. Do not add a dedicated viewport matrix and do not proactively inspect or redesign CSS/product/shell/mobile work.

Do not run verification. Ruff-format changed Python only; preserve web/YAML/Caddy formatting manually. Do not stage/commit/push.

Report changed files, production boundary, browser token/session/recovery lifecycle, formatting and manual verification commands.

## Manual verification

```bash
python -m pytest -p no:cacheprovider \
  apps/api/tests/test_deployment_contract.py \
  apps/api/tests/test_email.py \
  apps/api/tests/test_api_health_system.py \
  -q

npm run build:api
```

Validate Caddy:

```bash
docker run --rm \
  -e CADDY_DOMAIN=payments.example.test \
  -v "$PWD/deploy/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" \
  caddy:2.11.4-alpine \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

```bash
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web

npm run test:e2e -- \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/account-logout.spec.ts
```

## Expected result

The verified-account flow is usable end-to-end and its mail/IP security inputs are trustworthy in production, without unrelated Portal redesign.

## Commit

```text
feat(security): complete verified account production flow
```

---

# Step 4 — As-Built Handoff + Final Evidence

## Goal

Update only authoritative docs affected by the final implementation and run one final user-owned verification sequence.

## Inspect only

Primary authoritative docs:

```text
docs/architecture/portal-identity-session-legal-baseline.md
docs/SECURITY.md
docs/architecture/deployment.md
docs/architecture/payment-portal-data-model.md
```

Inspect/update `ARCHITECTURE.md` only if its existing transaction/identity/deployment summary is now stale.

Do not inspect `docs/engineering/CODING_CONVENTIONS.md` or `apps/web/AGENTS.md` unless the implementation introduced a genuinely durable coding rule that is not already documented elsewhere.

Plus final ANY-538 code only where required to verify an as-built fact.

Do not create a second identity source-of-truth document.

## Document

- real `email_verified_at` meaning;
- historical cleanup;
- unverified/sessionless registration;
- verification requires token + current password;
- resend/replay/concurrency;
- reset leaves unverified accounts unverified;
- session gating;
- Argon2 + PBKDF2 compatibility;
- password policy remains 8–128;
- auth abuse controls;
- SMTP/proxy requirements;
- four edge headers;
- unchanged bearer transport;
- provider/LBX/CSP deferrals;
- ANY-539 UI boundary;
- coordinated rollout/rollback;
- later ANY-504 invariant: authenticated Portal identity implies verified mailbox.

## AI prompt

Implement only Step 4 of ANY-538.

This is documentation/handoff only.

Inspect only the listed authoritative docs plus final ANY-538 code needed to confirm exact as-built facts.

Update the existing identity/session/legal baseline rather than creating another authority.

Document only behavior actually implemented in Steps 1–3. Explicitly record that password policy stays 8–128 and that common-password policy, MFA, session transport redesign, broad edge hardening, and Portal/mobile redesign were not introduced.

Record rollout/rollback and the ANY-504/ANY-539 handoff.

Do not run verification commands. Preserve Markdown formatting manually. Do not stage/commit/push.

Report changed docs and the final manual verification sequence.

## Manual final verification

```bash
python scripts/repo.py test-db up

npm run generate:check
npm run docs:check
npm run architecture:check
npm run test:api
npm run test:e2e
npm run check

python scripts/repo.py test-db stop
```

Also:

- rebuild final production API image;
- repeat Step-1 Argon2 production-container benchmark and record results;
- validate final Caddyfile;
- smoke registration -> verification -> login -> reset/session.

## Expected result

Authoritative documentation matches code and later ANY-504 work has one stable verified-identity prerequisite without inheriting unrelated security scope.

## Commit

```text
docs(security): publish verified account baseline
```

---

# Coordinated Rollout

The four commits are implementation checkpoints, not separate production releases.

In particular, Step 2 is not deployable by itself: it makes verification mandatory while Step 3 supplies the final production SMTP/proxy configuration and matching browser verification/recovery UX.

Cutover only after Steps 1–3 are complete and verified:

1. maintenance / stop predecessor API writes;
2. take pre-cutover DB backup;
3. provide final SMTP + proxy configuration;
4. run forward migration;
5. start final ANY-538 API;
6. deploy matching web build;
7. restore traffic;
8. smoke auth/verification/reset/session.

Do not run false-verification cleanup while predecessor API can still create registration-time verified Users.

Downgrade never fabricates old verification or revives sessions. Full rollback after migration requires restoring the pre-cutover DB backup with predecessor app/config.

---

# Definition of Done

ANY-538 is complete when:

- all 4 steps are implemented sequentially;
- password policy is still 8–128;
- new hashes use measured Argon2id;
- legacy PBKDF2 verifies and upgrades;
- `email_verified_at` means real mailbox ownership;
- historical fake verification and sessions are invalidated;
- registration creates no authenticated session;
- verification requires token + current password;
- unverified Users cannot authenticate normally;
- reset does not silently verify an unverified User;
- verification/resend is replay/concurrency safe;
- minimal login/registration abuse protection works without permanent lockout;
- production email and client-IP authority are adequate for those controls;
- only minimal edge headers are added;
- no MFA, common-password database, password-policy expansion, session rewrite, LBX CSP/provider scope, generic security framework, dedicated mobile/viewport hardening, or product redesign is introduced;
- later ANY-504 can rely on authenticated Portal identity implying verified mailbox ownership.
