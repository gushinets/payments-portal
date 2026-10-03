# ANY-538 — Provider-Independent Email Verification + Password Policy

## Plan Overview

| Field | Value |
| --- | --- |
| Feature | `ANY-504` |
| Ticket | `ANY-538` |
| Overall status | `done` |
| Baseline | `main` @ `6ff3464c7e8bf63f8ca582026d2efcf45904511d` (`ANY-533` merged) |
| Execution order | reset/recreate `ANY-538` from baseline → Step 1 → manual verification → commit → Step 2 → manual verification → commit |
| Steps / commits | 2 |
| Migration | one data-only migration clearing predecessor false-positive `email_verified_at` |
| Public API | additive `user.email_verified`; new verification confirm/resend routes |
| Handoff | future `ANY-504` billing initiation must require verified email |

## How to Use This File

1. Do **not** implement this plan on top of the current broad `ANY-538` PR #126 implementation.
2. Before Step 1, make the branch equal to the baseline above plus this plan only. The superseded Argon2, `authentication_rate_limits`, login/registration throttling, session gating, SMTP/proxy/Caddy and edge-hardening changes must not remain.
3. Store this file at:

   ```text
   docs/exec-plans/active/ANY-538-implementation-plan.md
   ```

4. For Step 1:

   > Read `docs/exec-plans/active/ANY-538-implementation-plan.md` and implement only Step 1. Follow the prompt exactly. Do not work on Step 2. Do not repeat broad repository, Linear, ADR, or standards research.

5. Review the diff and manually run the checks at the end of Step 1. Commit only after they pass.
6. For Step 2:

   > Read `docs/exec-plans/active/ANY-538-implementation-plan.md` and implement only Step 2. Step 1 is complete and authoritative. Do not repeat broad research.

7. Review the diff and manually run the Step-2 checks. Commit only after they pass.
8. The implementation AI must not run tests, linters, type checks, Playwright, builds, docs/architecture checks, or repository-wide checks. Ruff formatting is allowed only for changed ordinary Python files.
9. Do not stage, commit, or push from the implementation AI.
10. If the repository materially contradicts a locked decision below, stop and report the contradiction instead of redesigning it.

## Context and Locked Decisions

`ANY-538` now closes only two pre-launch gaps:

1. `email_verified_at` currently claims mailbox verification without proof;
2. there are no production users, so the password policy can be strengthened before launch without legacy-user migration.

Architectural-review disposition: the backend/domain policy is the sole
password-validity authority. The final web implementation keeps localized
guidance and maps the backend `password_policy_not_met` result, but removes the
independently maintained TypeScript evaluator. `ANY-541` owns generated
backend/frontend API contract migration.

### Verified email

After this ticket:

```text
email_verified_at != NULL
```

means proven mailbox ownership.

Future external-customer creation / PurchaseIntent / billing initiation under `ANY-504` must fail closed while it is `NULL`. Those future billing entry points are not implemented here.

Email verification is **not** an ordinary login/session prerequisite:

- registration still creates the existing initial AuthSession;
- login still accepts an active user with correct credentials whether verified or not;
- existing sessions are not revoked because email is unverified;
- successful email verification does not create/replace a session.

Expose an additive API presentation field:

```text
user.email_verified = (user.email_verified_at is not None)
```

from registration, login, and session responses so frontend recovery/resend state is deterministic.

### Password policy

All newly established passwords (registration and password reset) must satisfy:

```text
12..128 Unicode code points
>= 1 ASCII uppercase A-Z
>= 1 ASCII lowercase a-z
>= 1 ASCII digit 0-9
>= 1 character from:
!@#$%^&*()-_=+[]{}:,.?
```

Passwords may contain Unicode, spaces, apostrophes, quotes, semicolons, punctuation, and other characters.

Do not trim, normalize, case-convert, escape, or mutate passwords.

SQL-injection safety remains a database/query concern; do not sanitize passwords to prevent SQL injection.

Keep the current password hash/storage implementation unchanged.

Apply the composition policy only when establishing a new password:

```text
registration
password-reset confirmation
```

Do not apply it to:

```text
login
```

### Verification token

Reuse `magic_link_tokens` and add:

```text
MagicLinkPurpose.EMAIL_VERIFICATION = "email_verification"
```

`magic_link_tokens.purpose` is already `TEXT`; no purpose-column DDL is needed.

Token contract:

```text
secret: secrets.token_urlsafe(48)
stored: SHA-256(secret)
TTL: 24 hours
single-use
URL: /{routeLocale}/verify-email#token=<secret>
```

Plaintext token must never be persisted or logged.

Confirmation requires:

```text
valid token + existing authenticated bearer session for the exact token User
```

The verification link proves mailbox access. The authenticated session proves control of the Portal account.

### Resend

Resend is authenticated only:

```text
POST /api/auth/email-verification/request
Authorization: Bearer <existing session>
body: {}
```

No email address is accepted.

Use a 60-second cooldown derived from the newest outstanding verification token's `created_at`. Do not create a new rate-limit table.

### Locale

Reuse the `ANY-533` locale/delivery contract for:

```text
en / fr / it / de / es / ru / pt
```

with public `pt` delivery using Brazilian Portuguese (`pt-BR`).

### Historical data

There are no production users, but existing dev/pre-production rows can still carry false registration-time verification.

Add one data-only forward migration:

```sql
UPDATE users
SET email_verified_at = NULL
WHERE email_verified_at IS NOT NULL;
```

Do not revoke sessions. Downgrade must not restore those timestamps as verification evidence.

### Out of Scope for ANY-538

- Argon2/PBKDF2 migration;
- common/breached-password lists or strength libraries;
- login/registration throttling or `authentication_rate_limits`;
- timing equalization;
- session gating/revocation based on verified email;
- SMTP startup/readiness changes;
- proxy/Caddy/security-header/CSP work;
- MFA/passkeys or session-transport redesign;
- mobile/responsive hardening;
- `ANY-539` shell/catalog/product redesign;
- LBX/provider integration;
- external-customer/PurchaseIntent runtime;
- commercial legal wording/evidence changes.

---

# Step 1 — Implement backend email verification and password policy

**Status:** `done`  
**Commit:** `feat(identity): add email verification and password policy`

## Prompt

Implement Step 1 of ANY-538: add provider-independent email verification and the locked pre-launch password policy while preserving the existing registration/legal/session, login, password hashing, and password-reset architecture.

Do not implement Step 2 frontend work and do not restore the superseded broad ANY-538 hardening.

## Goal

After this step:

- registration/reset enforce the new-password policy;
- registration still creates the current User + legal evidence + AuthSession, but `email_verified_at=NULL`;
- the same registration transaction creates one verification token;
- localized verification email is scheduled only after commit;
- token + the existing authenticated bearer session can verify the email;
- authenticated users can resend after a 60-second token-derived cooldown;
- old false verification timestamps are cleared without session revocation.

## Relevant existing code

Work primarily in:

- `apps/api/app/domains/identity/passwords.py`
- `apps/api/app/domains/identity/router.py`
- `apps/api/app/domains/identity/password_reset.py`
- `apps/api/app/domains/identity/services/auth.py`
- `apps/api/app/domains/identity/services/password_reset.py`
- `apps/api/app/domains/identity/services/email_verification.py` — create
- `apps/api/app/domains/identity/errors.py`
- `apps/api/app/http/errors.py`
- `apps/api/app/http/request_locale.py` — create
- `apps/api/app/models/enums.py`
- `apps/api/app/models/identity.py`
- `apps/api/app/infrastructure/queries/identity.py`
- `apps/api/app/infrastructure/persistence/password_reset.py` — inspect only for token-mutation conventions
- `apps/api/app/infrastructure/persistence/email_verification.py` — create
- `apps/api/app/core/password_reset_email.py` — inspect email/fragment URL precedent
- `apps/api/app/core/email.py`
- `apps/api/app/core/email_verification_email.py` — create
- `apps/api/app/generated/locales.py`
- `apps/api/alembic/versions/20260924_0001_clean_first_install.py` — inspect only
- one new ANY-538 Alembic revision;
- focused identity/password-reset/email/PostgreSQL tests.

Known baseline facts that do not need rediscovery:

- `register_user()` currently owns one transaction for User + registration legal evidence + AuthSession;
- it currently sets `email_verified_at=accepted_at`;
- `MagicLinkPurpose` currently contains only `PASSWORD_RESET`;
- `magic_link_tokens.purpose` is `TEXT`;
- password reset already stores only token hashes;
- password reset currently claims the token before replacing the password;
- `_normalize_request_language()` currently lives privately in the password-reset router;
- `get_current_session` / `authenticate_session()` remains bearer-session authority.

## Implementation

### 1. Add one backend password-policy authority

In `passwords.py` add constants equivalent to:

```python
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
PASSWORD_SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{}:,.?"
```

Add one pure helper/predicate with exact semantics:

```text
12 <= len(password) <= 128
contains >= 1 ASCII uppercase A-Z
contains >= 1 ASCII lowercase a-z
contains >= 1 ASCII digit 0-9
contains >= 1 character from PASSWORD_SPECIAL_CHARACTERS
```

Do not trim/normalize/escape/mutate the value.

Add:

```text
PasswordPolicyError
HTTP 400 -> password_policy_not_met
```

Enforce the helper:

- in `register_user()` before DB lookup/mutation;
- at the start of `confirm_password_reset()` **before reset-token claim**.

Request bounds:

- registration: 12..128, using shared backend constants;
- reset replacement: 12..128, using shared backend constants;
- login: keep 8..128;

Do not add a password library or change hashing.

### 2. Extract `Accept-Language` normalization

Move the existing ANY-533 normalization algorithm from the private password-reset router helper into:

```text
apps/api/app/http/request_locale.py
```

Expose:

```python
normalize_request_language(value: str | None) -> RouteLocale
```

Preserve behavior exactly and update password reset to use it.

Registration and verification resend must use the same helper. Do not import a private password-reset router function and do not create another locale parser.

### 3. Add purpose + data migration

Add:

```python
MagicLinkPurpose.EMAIL_VERIFICATION
```

No `magic_link_tokens` schema change is required.

Create one data-only Alembic revision after `20260924_0001`:

```text
upgrade:
    clear every non-null users.email_verified_at

downgrade:
    no data restoration
```

Explain in the migration that predecessor timestamps were not mailbox evidence and therefore cannot be reconstructed on downgrade.

Do not edit the clean first-install migration or touch sessions.

### 4. Add `email_verified` to existing user presentation

Extend `AuthenticationResult` / `SessionUserResponse` as needed so these responses all return:

```text
email_verified: bool
```

derived only from `email_verified_at`.

Apply consistently to:

```text
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/session
```

Do not otherwise change their status/token/session semantics.

### 5. Add focused verification persistence/service primitives

Create the focused service/persistence modules above.

Constants:

```text
EMAIL_VERIFICATION_TTL_HOURS = 24
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
```

Create token with `token_urlsafe(48)`, persist only SHA-256.

Persistence owns no outer commit/rollback.

Add only helpers needed to:

- lock active User by `user_id + tenant_id + region` with `FOR UPDATE`;
- read/re-read a verification token by hash/purpose/scope;
- conditionally claim a valid unused/unexpired token;
- invalidate outstanding sibling verification tokens;
- find newest outstanding verification token for resend.

Do not generalize password-reset persistence into a token framework.

### 6. Extend registration without changing session behavior

Keep `register_user()` as transaction owner.

Add a small result contract:

```text
RegistrationResult
  authentication: AuthenticationResult
  verification_delivery: EmailVerificationDelivery
```

`EmailVerificationDelivery` contains:

```text
recipient_email
verification_url
route_locale
```

Registration sequence:

1. validate existing consents;
2. validate new password;
3. preserve current normalization/duplicate check;
4. load registration legal documents;
5. create active User with current hash, existing `last_login_at`, and `email_verified_at=None`;
6. flush User;
7. create current non-commercial registration legal evidence;
8. create current initial AuthSession;
9. create one `EMAIL_VERIFICATION` token in the same transaction;
10. build authentication + delivery results;
11. commit once;
12. return `RegistrationResult`.

Preserve current scoped-email race handling. A duplicate/loser path returns no delivery result and schedules no email.

Registration route:

- accepts `BackgroundTasks`;
- normalizes request `Accept-Language`;
- calls `register_user`;
- schedules verification email only after successful service return/commit;
- returns the existing `registered + token + user` response with additive `email_verified=false`.

Delivery failure cannot roll back registration.

### 7. Add localized verification email

Create `core/email_verification_email.py`, mirroring password-reset email structure.

Provide:

```text
build_email_verification_url
render_email_verification_email
send_email_verification_email
```

for all seven locales.

URL:

```text
{APP_PUBLIC_BASE_URL}/{routeLocale}/verify-email#token=<urlencoded-secret>
```

Add a safe background wrapper that catches delivery exceptions and logs only generic outcome/reason. Never log email, plaintext token/hash, or verification URL.

Do not add queue/outbox/worker/SMTP-hardening scope.

### 8. Add confirmation endpoint

Add:

```text
POST /api/auth/email-verification/confirm
Authorization: existing bearer session
body: { token }
response: { status: "verified" }
```

Transport bounds:

```text
token 32..256
```

Errors:

```text
invalid/expired/used token:
400 invalid_or_expired_verification_token
```

Use `get_current_session`. The token must belong to the exact authenticated User.

Required sequence:

1. hash candidate token;
2. read candidate by hash + purpose + tenant/region scope without mutation;
3. reject generically if it cannot belong to the authenticated User;
4. lock the authenticated active User `FOR UPDATE`;
5. after acquiring the User lock, obtain a fresh `now = utc_now()`;
6. re-read/revalidate the token under the User lock;
7. require unused, unexpired, `EMAIL_VERIFICATION` purpose, exact User ID, exact normalized email, and exact tenant/region scope;
8. if User is already verified and the token is otherwise valid, return `verified` idempotently without session changes;
9. conditionally claim exact token;
10. set `email_verified_at=now`;
11. invalidate sibling outstanding verification tokens;
12. commit once.

Invalid, expired, used, wrong-user, wrong-email, and wrong-scope tokens all return `400 invalid_or_expired_verification_token`.

Do not create, revoke, replace, or otherwise mutate sessions during verification. Do not change `last_login_at`, password, legal evidence, or password-reset tokens.

The User lock is the confirm/resend serialization boundary.

### 9. Add authenticated resend endpoint

Add:

```text
POST /api/auth/email-verification/request
Authorization: existing bearer session
body: {}
response: { status: "accepted" }
```

Use `get_current_session`. Never accept an email address.

Under the scoped active User lock:

```text
already verified
  -> accepted, no token/email

newest outstanding token age < 60s
  -> accepted, no mutation/email

otherwise
  -> invalidate outstanding EMAIL_VERIFICATION tokens
  -> create one fresh 24h token
  -> commit
  -> return delivery data
  -> route schedules email after commit
```

### 10. Keep password reset otherwise unchanged

After the new policy passes, preserve the existing reset flow:

```text
claim token
resolve User
hash/write password
invalidate sibling reset tokens
revoke active sessions
commit
```

Do not set `email_verified_at`, create verification evidence/session, or invalidate verification tokens merely because password changed.

### 11. Focused backend coverage

Cover at minimum:

Password policy:

- 11 rejected; valid 12 accepted; 128 accepted; 129 rejected;
- missing uppercase/lowercase/digit/special is rejected;
- every allowed special character can satisfy the special-character requirement;
- Unicode/space/quote/apostrophe/semicolon characters remain allowed as additional characters;
- a valid injection-looking password containing quote/semicolon text registers and logs in normally;
- registration/reset share policy;
- invalid reset replacement does not consume reset token;
- login does not apply the new-password policy.

Verification:

- registration remains authenticated but stores `email_verified_at=NULL`;
- `email_verified=false` appears in register/login/session until confirmation;
- exactly one hash-only verification token is created in the registration transaction;
- duplicate registration schedules no email;
- registration locale drives email locale;
- migration clears false verification and leaves sessions;
- confirmation requires an authenticated bearer session;
- valid token + matching authenticated User succeeds;
- wrong-user, wrong-email, and wrong-scope tokens fail generically;
- expiry is evaluated using a fresh time obtained after the User lock;
- invalid/expired/used/replay behavior;
- confirmation creates/revokes no session and does not change `last_login_at`;
- authenticated resend verified/no-op, <60s/no-op, >=60s/rotate;
- old token fails after rotation;
- confirm/resend races converge through User lock;
- all seven email templates, including Brazilian Portuguese for `pt`;
- no plaintext verification secret in persistence/log assertions.

Prefer parameterized focused tests over duplicated setup.

## Scope constraints

Do not:

- change password hashing/work factor;
- add login/registration throttling or rate-limit tables;
- gate login/session on verified email;
- revoke sessions in the data migration;
- create a session during verification;
- make password reset verify email;
- add SMTP/proxy/Caddy/security-header work;
- touch billing/provider/LBX runtime;
- refactor unrelated identity/legal code.

## Automated checks

Do **not** run automated verification.

After implementation run only:

```bash
cd apps/api
python -m ruff format <changed-normal-python-files>
```

Do not stage/commit/push.

## After implementation

Report:

1. files changed;
2. password-policy helper and call sites;
3. registration transaction + post-commit delivery contract;
4. confirmation lock/claim transaction;
5. resend lock/cooldown/rotation;
6. migration behavior;
7. locale/email behavior;
8. formatting run;
9. exact manual commands below.

Manual checks:

```bash
python -m pytest -p no:cacheprovider \
  apps/api/tests/test_passwords.py \
  apps/api/tests/test_api_identity_session.py \
  apps/api/tests/test_api_password_reset.py \
  apps/api/tests/test_api_email_verification.py \
  apps/api/tests/test_email.py \
  -q
```

```bash
python scripts/repo.py test-db up

python -m pytest -p no:cacheprovider \
  apps/api/tests/test_alembic_postgres.py \
  apps/api/tests/test_identity_legal_persistence_postgres.py \
  apps/api/tests/test_email_verification_persistence_postgres.py \
  -q

python scripts/repo.py test-db stop
```

```bash
npm run check:fast
```

## Commit

Final commit name:

```text
feat(identity): add email verification and password policy
```

Status:

```text
done
```

---

# Step 2 — Add verification/password UX and publish the ANY-504 handoff

**Status:** `done`  
**Commit:** `feat(web): add email verification and password policy UX`  
**Depends on:** Step 1 completed, manually verified, and committed.

## Prompt

Implement Step 2 of ANY-538: expose the Step-1 password-policy and email-verification contracts in the existing localized Portal and publish the exact handoff future ANY-504 billing work must consume.

Step 1 is authoritative. Do not redesign its API/backend behavior.

## Goal

After this step:

- registration/reset UI mirror the backend password policy;
- every registration surface sends canonical route language metadata;
- frontend consumes `user.email_verified`;
- unverified users can resend after registration, login, reload, or later account visit;
- `/[locale]/verify-email` handles the fragment token safely;
- verification leaves the existing bearer session untouched;
- architecture docs state the future billing gate.

## Relevant existing code

Work primarily in:

- `apps/web/src/shared/api/auth.ts`
- `apps/web/src/shared/password-policy.ts` — create
- `apps/web/src/shared/ui/AuthForm.tsx`
- `apps/web/src/shared/ui/auth-errors.ts`
- `apps/web/src/shared/ui/HeaderAccount.tsx`
- `apps/web/src/shared/ui/SiteShell.tsx`
- `apps/web/src/features/checkout/CheckoutClient.tsx`
- `apps/web/src/features/account/AccountClient.tsx`
- `apps/web/src/features/password-reset/PasswordResetConfirmClient.tsx`
- `apps/web/src/features/password-reset/errors.ts`
- `apps/web/src/features/email-verification/*` — create focused client/errors/index
- `apps/web/src/app/[locale]/verify-email/page.tsx` — create
- `apps/web/src/app/[locale]/auth-checkout/page.tsx`
- `apps/web/src/app/[locale]/account/page.tsx`
- `apps/web/src/generated/locales.ts`
- all seven `apps/web/src/messages/*.json`;
- `apps/web/e2e/email-verification.spec.ts` — create
- focused existing auth/account/reset/locale E2E files;
- `docs/architecture/portal-identity-session-legal-baseline.md`;
- `docs/SECURITY.md` / `ARCHITECTURE.md` only if their current summaries become stale.

Known frontend baseline:

- `AuthForm` and reset confirmation currently check only minimum 8 + confirmation;
- `submitAuth()` sends no `Accept-Language`;
- registration exists in both `CheckoutClient` and `HeaderAccount`;
- `AccountClient` reloads `/api/auth/session`;
- bearer token uses `anytoolai_session_token_v1`;
- `sessionChangedEvent` already refreshes session consumers;
- password reset already demonstrates fragment → `history.replaceState` → memory-only token handling.

## Implementation

### 1. Add one shared frontend password-policy mirror

Create `apps/web/src/shared/password-policy.ts`.

Match Step 1 exactly:

```text
12..128 code points
>= 1 ASCII uppercase A-Z
>= 1 ASCII lowercase a-z
>= 1 ASCII digit 0-9
>= 1 character from !@#$%^&*()-_=+[]{}:,.?
```

Use `[...password].length` for code-point length and direct special-string membership.

Do not trim/normalize/escape/mutate the value and do not add a library.

Return enough structured result for registration/reset to show localized unmet requirements without duplicating policy logic.

### 2. Update registration and reset UX

`AuthForm`, only in register mode:

- use the shared policy;
- preserve confirmation and both legal consents;
- show localized requirements;
- update old 8-character placeholder/help text;
- login mode remains existing-credential validation only.

`PasswordResetConfirmClient`:

- use the same helper;
- preserve fragment handling, confirmation, and successful session clearing;
- map backend `password_policy_not_met` to password-policy copy.

Map `password_policy_not_met` in normal auth error handling as a backend fallback.

### 3. Update auth API types/functions

Extend `AuthUser` and decoders:

```ts
email_verified: boolean
```

Add:

```text
requestEmailVerification(sessionToken, languageTag)
confirmEmailVerification(sessionToken, token)
```

Resend request:

```text
POST /api/auth/email-verification/request
Authorization: Bearer ...
Accept-Language: canonical tag
body {}
```

Confirm request:

```text
POST /api/auth/email-verification/confirm
Authorization: Bearer ...
body { token }
```

Keep existing registration/login token/status contracts.

### 4. Send locale metadata from both registration surfaces

Initial verification email locale comes from registration `Accept-Language`.

Use existing validated route locale only.

- `SiteShell` passes `LANGUAGE_TAG_BY_ROUTE_LOCALE[locale]` to `HeaderAccount`;
- `HeaderAccount` passes it to registration `submitAuth`;
- `AuthCheckoutPage` derives the same canonical tag and passes it to `CheckoutClient`;
- `CheckoutClient` passes it to registration `submitAuth`;
- login does not need the header for this ticket.

Do not use browser-language inference.

### 5. Make unverified state recoverable

Use backend `user.email_verified`; do not create a second verification source of truth.

After successful registration:

- store existing bearer token;
- keep the user authenticated;
- show “verify before paid features” guidance;
- expose resend.

After successful login with `email_verified=false`:

- login remains successful;
- keep bearer token;
- show the same pending/resend state.

After reload/later visit:

- `AccountClient` reads `/api/auth/session`;
- when `email_verified=false`, show pending guidance + resend;
- verified users do not see that state.

`HeaderAccount` may keep its auth modal open in a focused verification-pending state after register/unverified login instead of closing immediately. `CheckoutClient` may show the same pending block in its authenticated branch.

If useful, create one small `EmailVerificationPending` component shared by those surfaces. Do not build a generic account-state framework.

Every resend:

- uses the current bearer token;
- sends the current canonical language tag;
- accepts no email address;
- treats `{status:"accepted"}` generically;
- does not reveal whether backend no-op'd for verified/cooldown state.

### 6. Add `/[locale]/verify-email`

Create the locale page + focused client.

On mount:

```text
read #token
store only in React ref/memory
history.replaceState(...) immediately
```

Never persist the verification token to localStorage/sessionStorage/cookies/query parameters.

Do not ask for the current password. Require an existing authenticated bearer session and an explicit Verify action; do not auto-submit.

If the page is logged out, retain the token only in memory and ask the user to sign in normally before confirmation. After sign-in, use the existing bearer token with the memory-only verification token.

Success:

- clear in-memory token;
- show verified;
- do not change/remove/create bearer token;
- dispatch `sessionChangedEvent` so session consumers refresh `email_verified`;
- if no local session exists, show normal sign-in guidance.

Errors:

```text
invalid_or_expired_verification_token
  -> one generic invalid/expired/used message
```

If there is no token:

- authenticated unverified user may resend;
- otherwise show sign-in/reopen-email guidance.

Navigating away intentionally loses the memory-only capability. Do not modify the global locale switcher just to preserve it.

### 7. Localize the new UX

Add `EmailVerification` copy in all seven message catalogs plus the registration/reset password-policy copy in their existing namespaces.

Cover:

- pending verification;
- resend;
- accepted resend;
- verify page;
- missing/invalid/expired token;
- success/sign-in guidance;
- password requirements/errors.

Do not change canonical RU legal statements or create a new locale registry.

### 8. Focused E2E

Cover at minimum:

Password:

- 11-character password rejected and valid 12-character password accepted;
- missing uppercase/lowercase/digit/special passwords are rejected;
- every allowed special character can satisfy the requirement;
- valid Unicode/spaces/quotes/semicolon passwords are accepted as additional characters without mutation;
- reset uses the same policy;
- login does not apply the new-password policy.

Verification:

- both registration surfaces remain authenticated and send canonical language tag;
- unverified login succeeds and exposes pending/resend state;
- account reload gets pending state from `/session`;
- resend sends bearer + language tag + empty body;
- fragment disappears immediately and no confirm fires on mount;
- logged-out verification keeps the token memory-only and requires normal sign-in before confirmation;
- bearer session + matching token verifies without replacing bearer token;
- session refresh reports `email_verified=true`;
- invalid/expired/used token is generic;
- logged-out/no-token path requires normal sign-in rather than email-address resend;
- `pt` uses the existing Brazilian Portuguese mapping.

Do not add dedicated viewport/mobile test matrices.

### 9. Publish the durable handoff

Update `docs/architecture/portal-identity-session-legal-baseline.md` with the as-built contract:

```text
email_verified_at != NULL = proven mailbox ownership
ordinary Portal authentication does not require verified email
future external-customer / PurchaseIntent / billing initiation must fail closed while email_verified_at IS NULL
```

Record the new-password policy and unchanged password-hash/session behavior.

Preserve:

```text
registration legal evidence = non-commercial
registration evidence cannot satisfy future purchase-bound legal evidence
```

Record only the operational prerequisite:

```text
before billing is enabled, verification email delivery must be configured and smoke-tested
```

Do not add SMTP readiness infrastructure.

Update `docs/SECURITY.md` and `ARCHITECTURE.md` only if their current statements become stale. Do not create a competing architecture document.

## Scope constraints

Do not:

- change Step-1 backend semantics;
- block login for unverified users;
- replace bearer sessions;
- add public email-address resend;
- persist verification token in browser storage;
- add password-strength libraries;
- redesign locale switcher, mobile layout, Portal shell/catalog/product UI;
- implement billing/LBX/provider behavior.

## Automated checks

Do **not** run automated verification, formatting, staging, commit, or push.

## After implementation

Report:

1. files changed;
2. shared password-policy UX;
3. registration surfaces sending locale;
4. `email_verified` API/UI flow;
5. resend recovery paths;
6. fragment-token lifecycle;
7. confirmation that bearer token is unchanged;
8. E2E/docs changes;
9. exact manual commands below.

Manual checks:

```bash
npm run generate:check
npm run test:boundaries:web
npm run lint:web
npm run typecheck:web
```

```bash
npm run test:e2e -- \
  apps/web/e2e/email-verification.spec.ts \
  apps/web/e2e/password-reset.spec.ts \
  apps/web/e2e/auth-legal-links.spec.ts \
  apps/web/e2e/account-logout.spec.ts \
  apps/web/e2e/locale-routing.spec.ts
```

```bash
npm run docs:check
npm run architecture:check
```

```bash
python -m pytest -p no:cacheprovider \
  apps/api/tests/test_passwords.py \
  apps/api/tests/test_api_identity_session.py \
  apps/api/tests/test_api_password_reset.py \
  apps/api/tests/test_api_email_verification.py \
  apps/api/tests/test_email.py \
  -q
```

```bash
npm run check
```

## Commit

Final commit name:

```text
feat(web): add email verification and password policy UX
```

Status:

```text
done
```

---

## Definition of Done for ANY-538

- Step 1 and Step 2 are separately implemented, manually verified, and committed.
- Superseded broad ANY-538 hardening is absent.
- Backend registration/reset enforce the same 12–128 + `A-Z` + `a-z` + `0-9` + allowed-special policy.
- Backend/domain validation is the sole password-policy authority; web guidance
  is non-enforcing and `ANY-541` owns generated backend/frontend API contract
  migration.
- Login proves existing credentials without applying the new-password policy.
- Password hashing/storage is unchanged.
- `email_verified_at` means proven mailbox ownership.
- Registration still creates/returns the existing session and bearer token.
- Registration stores `email_verified_at=NULL`, creates one hash-only verification token in the same transaction, commits, then schedules localized email.
- Verification requires the token + its exact User's existing authenticated bearer session and does not create/revoke/replace sessions.
- Authenticated resend uses no email body and no new rate-limit table.
- Confirm/resend races serialize through the scoped User lock.
- Verification capability is hash-only in persistence and fragment/memory-only in browser.
- `email_verified` is exposed consistently to registration/login/session UI.
- Registration/login/account reload all provide deterministic resend/recovery for unverified users.
- All seven locales are covered; `pt` remains Brazilian Portuguese.
- Future ANY-504 billing is documented to fail closed while `email_verified_at IS NULL`.
- No billing/provider/LBX, Argon2, auth-rate-limit, proxy/Caddy/SMTP-hardening, session-gating, MFA, mobile, or Portal-shell scope is included.
