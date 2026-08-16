# ANY-98 Next.js and npm security baseline design

Status: approved design
Date: 2026-08-15
Review follow-up approved: 2026-08-16
Linear: https://linear.app/paveldik/issue/ANY-98/obnovit-nextjs-i-eslint-config-next-i-ustranit-postcss-advisory

## Goal

Complete the smallest safe dependency update that aligns Next.js with its ESLint
configuration, removes the PostCSS finding reported by the ANY-84 filesystem
scan, and leaves no Critical or fixable High npm vulnerability in the refreshed
lockfile. The change must preserve the existing public checkout and payment
behavior.

## Baseline

- `next` is declared as `16.3.1`, while `eslint-config-next` remains on
  `16.2.9`.
- The current lockfile resolves Next.js to `16.3.1` and its PostCSS dependency to
  `8.5.23`. The local `node_modules` tree is stale and is not valid evidence for
  the final dependency graph.
- A package-lock-only `npm audit` no longer reports PostCSS, but reports
  Critical or High findings through Vitest/Vite, `brace-expansion`, and
  `nanoid`.
- The first ANY-84 Trivy artifact was produced before all recent dependency
  updates and reported Next.js, PostCSS, Vitest/Vite, `brace-expansion`,
  `nanoid`, and other npm findings. The final result must therefore be checked
  with a newly generated filesystem report rather than inferred from that
  artifact.

## Dependency strategy

1. Keep Next.js on the latest stable patch in its current major line and align
   `eslint-config-next` to the exact same version.
2. Update Vitest and `@vitest/coverage-v8` only as far as required to reach a
   fixed, mutually compatible release. Allow the lockfile refresh to select
   fixed compatible Vite, `brace-expansion`, and `nanoid` releases.
3. Preserve React 18, ESLint 9, and TypeScript 5. Do not adopt unrelated major
   dependency updates from the open grouped Dependabot pull request.
4. Prefer the fixed upstream PostCSS version already selected through Next.js.
   Add an npm override only if a current Trivy scan still reports that resolved
   PostCSS version as a fixable High vulnerability.
5. Do not run `npm audit fix`; dependency changes must be explicit and reviewed
   in `apps/web/package.json` and `package-lock.json`.

If an override is required, it will pin only PostCSS to a verified fixed patch.
The security documentation will state that the override must be removed once
all dependency parents, including Next.js, resolve a fixed PostCSS version
without it and both npm audit and Trivy remain clean after removal.

## Files and behavior

The expected functional change is limited to:

- `apps/web/package.json` for direct dependency alignment and the minimum test
  tooling update;
- root `package.json` only if an npm override is required;
- `package-lock.json` regenerated with npm 11 on the repository's Node 24
  baseline;
- `docs/SECURITY.md` only if an override needs a documented removal condition;
- an ANY-98 execution plan and verification evidence.

No application source, API contract, route, legal content, or payment logic is
expected to change. If a dependency update exposes an application regression,
the implementation will fix only the compatibility issue needed to preserve
the characterized behavior and will add or adjust a focused test first.

## Verification

The implementation will collect before-and-after dependency and security
evidence and then run:

1. a clean `npm ci` on the Node 24/npm 11 baseline;
2. `npm audit` without `npm audit fix`;
3. a current Trivy filesystem scan using the repository configuration, followed
   by the checked-in Trivy gate logic where applicable;
4. web lint, typecheck, production build, boundary tests, component tests, and
   component coverage;
5. the critical Playwright smoke against the real Next.js, FastAPI, and
   PostgreSQL stack;
6. the broadest supported canonical repository check;
7. a final diff review confirming that React, ESLint, and TypeScript majors did
   not change and that checkout/payment source behavior is untouched.

The task is complete only when no Critical or fixable High npm finding remains,
or a human-approved temporary exception with an expiration date is recorded.
The selected design does not plan to introduce such an exception.

## Risks and rollback

- A Vitest update can change test-runner behavior. Component and coverage runs
  guard the test infrastructure, while the existing browser smoke guards the
  public journey.
- A PostCSS override could diverge from Next.js's tested dependency graph. This
  is why the upstream resolution is preferred and any override requires full
  lint, build, component, and browser verification.
- The dependency and focused compatibility commits can be reverted without data
  migration or runtime state changes.

## Review follow-up: preserve document navigation on logout

The aligned `eslint-config-next` preset enabled
`@next/next/no-location-assign-relative-destination`. The initial compatibility
change replaced `window.location.assign("/ru")` in `AccountClient` with
`router.push("/ru")`. PR review identified that this is not behavior preserving.

`HeaderAccount` lives in `SiteShell` under the root layout, so a client-side
route transition does not unmount it. Its effect-level `cancelled` flag only
changes during unmount. A session request started before logout can therefore
resolve after the session token is removed and the session-change event clears
the header, then write the stale authenticated email back into the still-mounted
header. The previous full document navigation unloaded that state before it
could repaint.

The approved correction is deliberately narrow:

1. Remove `useRouter` from `AccountClient` and restore
   `window.location.assign("/ru")` after local token removal and the existing
   session-change event.
2. Add a line-level ESLint suppression for
   `@next/next/no-location-assign-relative-destination`, preceded by a comment
   explaining that full document navigation is required to discard root-layout
   session state and in-flight session requests.
3. Remove the test-only router push hook introduced by ANY-98 when no remaining
   component uses it.
4. Replace the router-specific assertion with coverage of logout session
   cleanup, and add a boundary regression test that records the required hard
   navigation contract. The boundary test must fail against the current
   `router.push` implementation before production code changes.

Keeping client navigation and adding request-generation or abort coordination
inside `HeaderAccount` was rejected because it broadens this dependency-security
task into shared session-state concurrency behavior. Introducing a global auth
store was also rejected as unrelated architecture work. The selected fix
restores the pre-upgrade behavior with the smallest surface area.

Verification for the follow-up consists of the focused red/green regression,
the complete component and boundary suites, web lint and typecheck, and a
production web build. No rendered UI, localization, API, payment, legal, or
database behavior changes, so new desktop/mobile visual evidence is not
applicable.
