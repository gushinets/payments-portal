# ANY-830 independent review

Reviewed source `6e3c8a2c39d0c017b57820116c9a5e21a4ae20ae`, PR #190 against
fetched main `550263e644b49baa01d313de32ddaf1db0016b08`. Scope covers the 17
ticket keys, N01, the affected tests and deployment contracts, and GitHub
discussion. The canonical ledger records individual keys and scanner status.
[Ledger](findings.md) · [PR #190](https://github.com/gushinets/payments-portal/pull/190)

## Reconciliation

The merge base was `1584c3fc75e7966b4aeb6c314be8c5300bc35df6`. The task
worktree fast-forwarded to the existing PR head `ea1f1151efd8eda0f4ff34f642fbbdbd79c15b5d`
before merging main. The textual conflict was in
`apps/api/tests/test_deployment_contract.py`. Both sides appended independent
tests. The resolved file keeps the ANY-830 permission assertions and the
main-side Dockerfile package purge and native runtime inspection tests,
including their rejected and accepted cases.

The automatic merge also combined two settings contracts. Main requires
PostgreSQL with psycopg in production, so the prior SMTP test fixture's SQLite
URL caused both positive production cases to fail. The fixture now uses a
syntactically valid PostgreSQL URL for production without connecting to a
database. The negative cases check that SMTP is the only validation error.
The automatic merges also retained main's LBX payment delay setting and the
development LAN and production SMTP example changes. No generated files
needed conflict resolution. The initial run had 160 passes and two failures.
After reconciliation, all 162 focused Python cases and both Node cases passed
using native Git Bash on Windows. GitHub returned `mergeable: true` for the
recorded source revision and base.

## Findings in impact order

1. **Production mail could send credentials or recovery and verification links
   over plaintext (N01, high consequence, high confidence).** The operator
   must configure a host and turn TLS off, and the relay must accept plaintext.
   Settings now reject that combination in production before delivery. Missing
   host still disables email and a local SMTP sink still works when the
   development or test operator disables TLS. The default remains enabled.
   The sender runs STARTTLS before login and sending and propagates failures
   without a plaintext retry. The context test checks certificate and hostname
   verification with a real Python context and a fake SMTP transport. The
   settings matrix checks the startup contract. Neither test establishes a
   real relay's support, certificate chain, or hostname. Deployment with an
   active non-STARTTLS relay, including an implicit-TLS-only endpoint, will
   need a STARTTLS-capable endpoint. The sender already used SMTP with
   optional STARTTLS before this change.
   [Python SMTP client](https://docs.python.org/3.12/library/smtplib.html#smtplib.SMTP.starttls)
2. **Inherited review permissions exceeded individual job needs (F10–F13,
   latent configuration risk, high confidence in static scope).** GitHub
   reports workflow `357232766` as `disabled_manually`. If enabled, creation
   of a PR comment starts the gate, which checks the literal command and
   the actor's repository role before launching the reusable review.
   A job token exists before that role check. Gate calls are collaborator
   permission lookup (implicit repository metadata read), pull request read
   and PR issue-comment creation (`pull-requests: write` covers both), and
   check create/list/update (`checks: write`). The finalizer calls only check
   update. The caller needs the union of the pinned workflow's requirements.
   The preflight and review jobs declare Actions, contents, statuses, checks
   and PR reads. The pinned client reads archives/content, PR metadata/diffs,
   workflow runs/jobs/logs, check runs, and combined commit statuses. The
   publisher reads Actions artifacts, updates or creates PR comments and
   check runs and creates PR reviews. The YAML contract test checks all
   three local permission maps. Both gate and reusable call keep the write
   permissions they consume. Every existing job needs checks write, so F13
   removes implicit authority for future jobs only. Any future re-enable
   still depends on repository Actions policy, reusable workflow access and
   secrets. No live calls were made with an Actions job token.
   [GitHub App endpoint permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps) ·
   [Reusable workflow permissions](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#nesting-reusable-workflows) ·
   [Pinned reusable workflow](https://github.com/gushinets/ai-pr-review/blob/c1351f2e944006dbddb04f16aebb1c77b17f2900/.github/workflows/reusable-ai-pr-review.yml) ·
   [Pinned API client](https://github.com/gushinets/ai-pr-review/blob/c1351f2e944006dbddb04f16aebb1c77b17f2900/src/github/github-client.ts) ·
   [Pinned publisher](https://github.com/gushinets/ai-pr-review/blob/c1351f2e944006dbddb04f16aebb1c77b17f2900/src/github/publisher.ts)
3. **Default Next development trust included a LAN address (F17, conditional
   local exposure, high confidence).** The pinned Next 16.4.2 implementation
   checks the configured host list on internal development HTTP and WebSocket
   paths. The extra literal previously authorized a matching origin on any
   reachable development server using the default. Localhost, its
   subdomains, and the server's supplied hostname are added by Next itself.
   The regression exercises the actual config import for both an unset
   variable and an explicit host list. It does not start a browser or assert
   the framework's response. Developers using an extra LAN origin must
   configure it explicitly. The initial example placed the setting in the
   repository root environment template, which the normal host-side Next
   invocation does not load. A local Next environment-loader check confirmed
   that only the web project's `.env.local` was read in this case. The
   example now directs developers to that file or the launch environment.
4. **Main superseded one historical false-positive disposition (F07, evidence
   correction, high confidence).** The flagged public character-set constant
   was never a credential. ANY-896 removed composition rules and now checks
   password length before hashing. The current Sonar main lookup returns
   `FIXED` for the original key. The correct remaining action is to record
   the main result. [ANY-896 PR](https://github.com/gushinets/payments-portal/pull/195)

## Per-finding adjudication

| ID | Verdict and confidence | Source trace, counter-evidence, and test limits |
| --- | --- | --- |
| F01 | Supported, high | `docker-compose.yml:46` contains a usable public fallback DSN for the development database. The database port is published to loopback. Same-host clients and backend-network peers are within reach. Production Compose supplies its own DSN. Deployment tests and source establish the intended configuration, with no isolation guarantee against a local peer. Preserve the fallback within that boundary. |
| F02 | Supported, high | `scripts/repo.py:482` emits a DSN consumed by migration/API runtime from local harness configuration. The local role is intentionally usable. File protection limits incidental exposure and leaves a co-resident caller able to use the known default. Production config does not consume the generated development environment. |
| F03 | Supported, high | `scripts/repo.py:3601–3624` writes to the `Path` selected by the operator's directory or the runner-owned glob before parsing. The exact Sonar flow starts at JSON content and follows the string argument to `write_text`. That argument controls output bytes. JSON fields cannot set the receiver path. Existing tests exercise custom names, redaction and upload gating. They do not claim safe use with a concurrently writable or symlink-controlled report directory. Keep the CLI under the caller's filesystem authority. |
| F04 | Supported, high | `apps/api/app/core/email.py:27–32` supplies a default verifying context. The test checks hostname verification and `CERT_REQUIRED`. A trust store and matching peer identity are required. N01 addresses the separate pre-existing opt-out. |
| F05 | Supported, high | `.github/workflows/ci.yml:204–206` retrieves the job-owned API readiness body and feeds it to `json.load(sys.stdin)`. Python runs a fixed `-c` argument, with bytes arriving on stdin as data. Invalid JSON or an unexpected status fails the probe. A service that supplies a plausible status can satisfy this probe. The production gate separately runs PostgreSQL tests and migrates the job-local database before starting the image. |
| F06 | Supported, high | Sonar's current sink is the fallback `subprocess.run` at `scripts/repo.py:4281`. The absolute interpreter and script precede operator CLI arguments, with shell execution off. The distinct test/check branches use an interpreter option terminator and fixed script. The real-venv regression covers that test/check branch. The fallback is confirmed by source inspection. Local interpreter or checkout replacement is outside this CLI boundary. Main already contains targeted comments on the distinct branches from `dac00ead`. ANY-830 introduces no suppression. |
| F07 | Needs correction, high | The historical false-positive verdict is supported. The flagged assignment is gone from `apps/api/app/domains/identity/passwords.py` in current main. Current password entry points use the new length bounds, while the separately salted hash remains. Record the upstream Sonar fix. |
| F08 | Supported, high | `.github/workflows/ci.yml:96` seeds the job-local PostgreSQL service with a known fixture password used by the migration and smoke process. Production application mode in the smoke test does not select a live production database. Hosted startup provides integration evidence. Preserve the fixture. |
| F09 | Supported, high | `scripts/repo.py:477` supplies the development role password to PostgreSQL itself. F02 covers the same credential's DSN consumer. Local peers can use it. Preserve matching dev bootstrap values. |
| F10 | Supported, high | `.github/workflows/ai-pr-review.yml:150–155` gives only the reusable call Actions read. The pinned client reads run, job and artifact metadata. Removing this permission from the caller could deny the callee's declared access. |
| F11 | Supported, high | `.github/workflows/ai-pr-review.yml:150–155` gives only the reusable call statuses read. The pinned client queries combined commit status. Gate/finalizer check operations require a separate Checks permission. |
| F12 | Supported, high | `.github/workflows/ai-pr-review.yml:10–12,150–155` retains PR write for gate comments and review publication. Finalizer receives only Checks write. The workflow's role check and disabled state limit the practical exposure. |
| F13 | Supported, high | `.github/workflows/ai-pr-review.yml:10–12,150–155,170–171` explicitly grants each current job the Checks write it needs. The empty workflow default constrains subsequent jobs. The number of current token holders stays the same for this scope. |
| F14 | Supported, high | `security/trivy/verify-api-runtime.sh:140` calls `docker port` for the published loopback port, sends no credentials, and compares a fixed liveness body. A local Docker context is required. The Docker build/runtime smoke verifies the service in CI. |
| F15 | Supported, high | `security/trivy/fixtures/non-compose/insecure-pod.yaml:6` omits an explicit automount decision. A live cluster could attach its default service-account token if someone applied it. The tracked workflow scans it as data and checks that the fixture yields misconfigurations. Its assertion is file-level, with no guarantee about the exact Sonar rule. |
| F16 | Supported, high | `security/trivy/fixtures/non-compose/insecure-pod.yaml:7` omits a memory limit, which would matter for an actual scheduled workload. No repository deployment applies the fixture. Keep the negative input and the file-level scanner coverage check. |
| F17 | Needs correction, high | `apps/web/next.config.mjs:6–17` now defaults to an empty additional allowlist. Explicit operator input is still trimmed and converted to hostnames. Both controls run in the canonical web boundary suite. The root example now names the actual opt-in locations for the normal developer command. |
| N01 | Supported, high | `apps/api/app/core/settings.py:179–191` rejects TLS-off only when both production and a nonempty host apply. The configured sender, missing-host branch, and existing reset-delivery tests establish the runtime boundary. Relay policy is operational evidence outside this review. |

The follow-up reconciles the tests with main and corrects the LAN setup
instructions. The review also corrects the ledger and qualifies its evidence for the
exact scanner flows, declared workflow access, pinned Next behavior, and
negative fixture coverage. The disabled workflow and production SMTP were
not exercised. This review cannot verify live host isolation, site-specific
relay trust, or administrator permissions. Sonar PR absence is a different
observation from the original key's main status. Four proposed false-positive
dispositions and seven intentional-use reviews remain for Sonar issue
administration. The five changed findings still need post-merge main
validation. See [verification and current counts](summary.md).
