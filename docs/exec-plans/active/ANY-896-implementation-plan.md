# ANY-896 — Accept generated passwords in registration and reset

Status: implementation and verification complete. The PR is still in review.

[Linear issue and agreed policy](https://linear.app/paveldik/issue/ANY-896/accept-password-manager-passwords-in-portal-registration-and-reset#comment-3693e348-8ee4-4494-9556-03bae85ad6d4)

## Objective and decisions

Users can paste a generated password or fill it with a password manager when
registering or confirming a password reset. Accept 12–128 Unicode code points
inclusive without mandatory character classes. Preserve the submitted string,
including leading and trailing spaces and decomposed Unicode. Defer checking
new passwords against a list of common or compromised values.

The shared backend validator owns the new-password policy. Keep the existing
HTTP contract, password hashing, sign-in with stored credentials, and reset
token and session behavior. The change requires no migration.

## Implementation

1. **PLAN-1 — Reproduce the HTTP rejection before changing the validator.**
   Add positive validator and API regressions for new passwords. Exercise
   registration and reset confirmation with a valid test token. In both
   flows, use a mixed-case alphanumeric password, a password whose only
   punctuation is `~`, and a password with leading and trailing spaces and
   decomposed Unicode, without ASCII letters or digits. Before editing
   `password_meets_policy()`, record the validator rejection and HTTP `400`
   with `password_policy_not_met` in both flows. If `TestClient` stalls, diagnose
   the test environment or repeat the run in a working isolated environment.
   Form and documentation work can proceed while HTTP verification is blocked.
2. Reduce `password_meets_policy()` to a length check using the existing
   bounds. Remove the class checks and punctuation constant. The two callers
   continue to pass the submitted string to hashing and return the existing
   `400 password_policy_not_met` when the length is out of range.
3. In registration and reset confirmation, replace the composition list with
   one localized length hint linked by `aria-describedby`. Remove the obsolete
   composition copy across all seven catalogs and make `password_policy_not_met`
   identify the 12–128 character range. Preserve password confirmation and
   `autocomplete="new-password"`. Keep length enforcement on the backend.
   Update the
   [documented password baseline](../../architecture/portal-identity-session-legal-baseline.md#new-password-policy)
   with the agreed policy and deferred list check.

## Acceptance and verification

- After changing the validator, verify HTTP success for all three samples in
  both flows. Replace the old character-class assertions with coverage for
  the new policy. Check 11, 12, 128, and 129 code points with supplementary-plane
  characters, and assert the HTTP policy error at 11 and 129 in both flows.
  Confirm that an 11-code-point password leaves a valid reset token available
  for a subsequent successful submission. Reuse the existing
  [policy and login tests](../../../apps/api/tests/test_passwords.py)
  and [reset tests](../../../apps/api/tests/test_api_password_reset.py).
- After registration and after reset, sign in with the exact Unicode sample.
  Try its trimmed and NFC-normalized variants separately and expect `401` for
  each. Keep the test for sign-in with an existing password shorter than 12
  code points.
- **PLAN-2 — Browser acceptance.** Update the existing
  [registration](../../../apps/web/e2e/email-verification.spec.ts)
  and [reset](../../../apps/web/e2e/password-reset.spec.ts) Playwright scenarios
  to check the accessible field description, localized error, and exact request
  value on desktop and mobile. Separately, in local Chrome with a test profile,
  exercise actual paste and password-manager autofill in each form. Compare the
  submitted value with the synthetic original. Reuse the reset scenario's test
  token and API interception. If autofill fails reproducibly, fix the affected
  fields and repeat the manual scenario. Record browser acceptance as pending
  if the manual check is blocked.
- Run the focused tests first. For the final check, use the isolated local app
  stack and test PostgreSQL.

  ```bash
  PATH="$PWD/.venv/bin:$PATH" RUN_E2E=true npm run check
  ```

  If the full check stops before the browser suite, run the affected scenarios
  separately against the isolated local app stack.

  ```bash
  npm run test:e2e -- email-verification.spec.ts password-reset.spec.ts
  ```

  Record the tested revision, results, and the reason for any blocked check.
