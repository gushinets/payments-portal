# ANY-743 OpenTelemetry tracestate patch and evidence

Issue: https://linear.app/paveldik/issue/ANY-743

## Goal and approach

Use the upstream parser remediation without application parsing or observability
redesign. Preserve W3C propagation, correlation, configured OTLP signals and
telemetry privacy. Python 3.12, uv 0.12.7 and the checkout-root environment apply.

## Base and prerequisite

Fresh origin/main: `96d07236d25d17c9c5dca5f8884488dc4cabb682`.
PR #173 merged into main at that squash commit on 2026-11-16T16:14:09Z;
ancestry exit 0, certifi 2026.10.19 and the TLS verifier are present.
Managed worktree: `D:/.codex/worktrees/any-743-patch-opentelemetry/payments-portal`.
Branch: `codex/any-743-patch-opentelemetry`; initial HEAD equals base; clean.

## Execution plan

- [x] Verify prerequisite, inspect issue/comments, dependencies and request path.
- [x] Run baseline observability tests and demonstrate failing bounded regression.
- [x] Align direct pins and regenerate lock with pinned uv, preserving certifi.
- [x] Verify valid/malformed/oversized/pathological state and request correlation.
- [x] Exercise actual configured trace, metric and log exporters against loopback.
- [x] Build and verify final production image; obtain fresh filesystem/image scans.
- [x] Run focused/canonical checks; review diff and record limitations.
- [x] Fetch main again, reconcile if needed, prepare focused PR for human review.

## Upstream and compatibility

[Upstream advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h)
affects API through 1.45.0; 1.45.1 is the minimum patched release.
[Fix #5746](https://github.com/open-telemetry/opentelemetry-python/pull/5746)
replaces the unbounded regex splitter with literal comma splitting and whitespace
stripping. TraceContextTextMapPropagator rejects combined tracestate length over
8192 before calling TraceState.from_header (the low-level method itself has no
length limit). No local parser or scanner exception is introduced.

API, SDK and OTLP HTTP exporter: 1.44.0 -> 1.45.1.
FastAPI and SQLAlchemy instrumentation: 0.65b0 -> 0.66b1.
SDK requires API 1.45.1 and semantic conventions 0.66b1; instrumentation's exact
semantic/instrumentation pins require the matching family. Lock also aligns
ASGI instrumentation, util-http, proto and proto-common. Two newly required
exporter packages are exporter-http-transport and exporter-otlp-common 0.66b1.
No non-OpenTelemetry version changes; certifi stays 2026.10.19.

## Reachability and baseline

`app.main` calls configure_observability. It returns without instrumentation when
OTEL_EXPORTER_OTLP_ENDPOINT is empty. When configured, FastAPIInstrumentor installs
ASGI middleware; inbound header extraction calls the W3C propagator and upstream
TraceState parser before the application handler. Existing runtime smoke disables
OTel and proves liveness only. Package presence alone does not prove deployed
exploitation; gateway/server header limits can affect reachability.

Baseline lock check/install passed; existing observability tests: 11 passed.
New regression on unchanged 1.44.0: 3 failed, 3 passed. Both padded oversized
whitespace cases fail the discard assertion in subprocesses (20-second timeout),
and the instrumented oversized request retains vendor=value incorrectly.
The bounded CPU case is synthetic and subprocess-isolated; no deployed target,
raw malicious header logging or fragile millisecond threshold is used.

## Verification ledger

Patched observability suite: 19 passed; combined dependency selection: 77 passed. Tests assert valid state injection, remote
parent trace/span IDs, malformed/duplicate/oversized rejection, HTTP success,
X-Request-ID and JSON trace/request correlation, and absence of synthetic secrets
from captured server logs/spans/events. Pathological space/tab input is bounded.

`security/trivy/verify-api-telemetry.py` runs in a fresh process and imports the
actual app with OTLP configured and enabled. A disposable loopback collector
decodes protobuf for all three signals and verifies successful delivery, safe
payloads and continued liveness. It uses ASGITransport to avoid a real service;
the in-process HTTPX driver's URL logging is excluded from server telemetry.
This is controlled synthetic evidence, not production/provider acceptance.

Remaining verification results will be recorded against the final revision.
No schema, customer UI, billing, contour or peer contract changes are intended.

## Final local results

- Focused observability + dependency compatibility suite: **77 passed** (19
  observability cases included); Python lint and format checks passed.
- Final production build, existing runtime verifier, and enabled telemetry
  verifier including a handled synthetic exception: **passed**. All three OTLP
  signals delivered; exported data excludes query/auth/cookie/exception markers
  and exception stacktraces. Request success, safe 500 and later liveness pass.
- Fresh Trivy 0.72.0 filesystem vulnerability scan (including dev dependencies)
  and final image vulnerability/secret scan: target CVE and GHSA **absent**;
  inventory confirms API 1.45.1. See [scan summary](2026-11-16-any-743-scans.json).
  Unrelated findings remain (6 filesystem, 219 image); no policy/ignore changes.
- Exact image ID / local RepoDigest:
  `sha256:c731829cf40890164f930fd519feabc1334d754b148f7429863b08dbcbd8a383`.
  Image is local, not deployed or published. The standalone verifier is mounted
  read-only for checks, not added to the production image.
- `npm run lock:check:api`: passed. `npm run test:api:fast`: failed after
  75 passes at the localhost uvicorn smoke (`httpx2.ConnectTimeout`). Same
  failure was recorded before this task in ANY-740; no claim all local tests pass.
- `npm run check:fast`: docs/generation/architecture, lint/format, web boundaries,
  454 component tests and web lint passed; same localhost API smoke failed.
- `npm run check`: failed at the same localhost smoke (75 passed); preceding
  docs/generation/architecture/lint/web checks passed. Web production build and
  PostgreSQL stages were unreached locally. Fresh PR CI is pending.
- Initial compatibility assertion failure was resolved by updating only the
  five existing OTel expected pins. Initial generated artifact failures were
  CRLF checkout differences; canonical `npm run generate` normalized them with
  no source-content diff. A focused invocation without D: TEMP hit C: temp
  permissions; the corrected D: invocation passed all 77 tests.
- First filesystem scan omitted canonical cache/dependency exclusions and was
  stopped; fresh replacement used the existing standard exclusions and passed.
- Independent read-only review found no actionable correctness issues; the
  success-only exporter coverage gap was addressed with the exception journey.
- Pre-submission fetch succeeded; origin/main remains the verified base SHA.

No database migration, browser/customer UI journey, peer API or Platform Kernel
change applies. Existing telemetry behavior remains configuration-dependent;
these tests explicitly enable instrumentation and exporters. Availability checks
are bounded synthetic checks, not an assertion about deployed gateway limits or
an exploited endpoint. Human merge review remains required.

Runtime/lock source: `8437b5e27f3aa80b783f0f5edad744aa69713e36`.
[PR #174](https://github.com/gushinets/payments-portal/pull/174) is ready for human
review; no merge or deployment. The image was built from the identical
manifest/lock/application content before that commit was recorded. Earlier
pending-CI/local-failure entries above describe their original execution snapshot.
The [local Windows follow-up](2026-11-16-local-windows-verification.md#final-follow-up--2026-11-17)
records passing final fast commands, green implementation CI and fresh scan
evidence, plus the separate Next.js notice and recurring Docker clock limitation
that prevent claiming full local acceptance.
