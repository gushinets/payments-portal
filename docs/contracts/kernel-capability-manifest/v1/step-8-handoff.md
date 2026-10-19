# ANY-664 Step 8: local conformance and source references

Status: source implementation; human verification pending. This handoff adds
no actual producer evidence and does not reopen Steps 1, 2 or 7.

```text
LOCAL_SPEC_CONFORMANCE=NOT_RUN
REFERENCE_SOURCE_CHECK=NOT_RUN
REFERENCE_WATCH_OPERATIONAL=NOT_YET_OPERATIONAL
REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED
```

## Dependency handoff and ownership

[The local checker](../../../../scripts/check_kernel_manifest_contract.py)
consumes the retained [JSON Schema](manifest.schema.json),
[literal fixture](fixtures/valid-manifest.json) and
[literal digest](fixtures/valid-manifest.digest). Its independent test oracle
interprets the pinned schema vocabulary and checks semantic hashing, uniqueness,
owner references and exact scope. New unsupported schema keywords fail closed.
Neither the mock nor Portal runtime imports this checker.

The checker starts the existing `ManifestMockServer` on ephemeral loopback
ports, owns its thread/server shutdown, and uses actual HTTP. It checks the
existing `PlatformKernelClient.fetch_manifest(budget=...)` through
`source_resources`, which owns its HTTP pool and admission lifecycle. The
typed result must retain SIMULATED provenance, selected capability semantics
and all returned products/metrics. Valid disabled/missing selections are
distinct from malformed manifests. Expected client errors remain
`kernel_manifest_invalid`, `kernel_scope_mismatch`,
`kernel_authentication_failed`, `kernel_scope_forbidden` and
`kernel_unavailable`. Deliberate scenario failures are expected within the
full suite; an explicitly selected corrupt `--scenario` makes the command fail.

The independently retained digest anchors the positive fixture. An additional
in-memory, visibly test-only second metric exercises shared product ownership
and order/timestamp stability without changing accepted fixture files. Served
OpenAPI must project the retained schema, resolve local references, preserve
auth/scope/status contracts and retain pinned, read-only Swagger configuration.

Step 7's optional Compose wiring and walkthrough remain unchanged. The checker
needs neither Compose nor PostgreSQL, a Kernel checkout, live LBX, nor a real
producer. It writes no mappings and grants no paid access. Existing simulation
containment and F1–F7 are retained; later purchase/recovery/paid-access capacity
and runtime proofs remain outside this step.

## Independent reference watch

[The reference script](../../../../scripts/check_kernel_references.py)
compares the default-branch source at one resolved commit per repository with
immutable pins. It reads only `api.github.com`, without redirects, retries,
public/private URL fallback, source execution or checkout. Limits are one
60-second operation, 5-second HTTP waits, 256 KiB per response and at most
14 GETs. No local conformance command contacts those sources.

The Portal spec pin is `05d3fcb6a965fcd053d713f49669d1dd25c22978`.
Only service authentication and the manifest request/response/enabled/HTTP
sections are compared; historical import/freshness and AccessSnapshot are
outside the watch. The Kernel pin is
`079eb03e28d7a50b980795c63c3e4533b785d11f`. References are the actual pinned
bootstrap, ConfigRegistry, FreelancerSuiteBundle and ProposalAI `product.yaml`
paths recorded in the [contract provenance](README.md#authority-and-provenance).
Python AST and two product identity fields yield narrow identity fingerprints;
the five fixture product roots are compared without flagging additional
off-fixture products, guest quota changes, comments or unrelated repository
commits. These fingerprints are provenance signals, not API compatibility or
paid release proofs.

Reports include each source path, pin, observed commit and both fingerprints.
Exit `0` means `REFERENCE_SOURCE_CHECK=PASS`; `1` means
`CHANGE_REVIEW_REQUIRED`; `2` means `UNKNOWN_SOURCE_CHECK`. Inaccessible
sources, permission failures, rate limits, invalid responses and timeouts are
UNKNOWN. An accessible source with removed/changed reviewed structure requires
review. Known drift remains actionable if another read is unavailable;
`source_access_complete=false` records the incomplete evidence. Review the
specific source change before updating a pin/projection. Never refresh pins
automatically to silence drift.

[CI](../../../../.github/workflows/ci.yml) runs local conformance and the
existing fast test suite. The focused
[reference workflow](../../../../.github/workflows/kernel-references.yml)
runs on relevant Portal PR paths, manual dispatch and daily at **03:43 UTC
(11:43 Asia/Ulaanbaatar)**. GitHub schedules execute the default-branch workflow;
feature-branch presence does not activate a schedule. Each run has a five-minute
job limit and retains a separate JSON report for seven days. No provider writes,
issue/comment posting or Kernel CI are involved.

Configure `KERNEL_REFERENCE_GITHUB_TOKEN` as a fine-grained, read-only contents
credential with access to both named repositories; the normal Portal-only
`GITHUB_TOKEN` does not establish private Kernel access. Supply it through the
repository secret or local environment, never a CLI argument or checked-in
file. Missing credentials may work for public sources, but inaccessible private
sources (including fork PRs without secrets) yield UNKNOWN and a nonzero job.
Do not reinterpret this as a local schema failure or bypass it with a public URL.

`REFERENCE_WATCH_OPERATIONAL` stays `NOT_YET_OPERATIONAL` until the owner records
a successful **scheduled** default-branch run after merge: run URL, workflow
commit, event `schedule`, time, report artifact and source-access result. Manual
dispatch can establish connectivity but cannot prove the daily schedule fired.
The script conservatively emits NOT_YET_OPERATIONAL; retain deployment/run
evidence separately before recording VERIFIED in acceptance evidence.

## Exact manual verification order

From `/home/wstanley/www/work_unirec/payments-portal`, with the existing locked
root `.venv` and web dependencies installed:

```bash
./.venv/bin/python scripts/check_kernel_manifest_contract.py --local
./.venv/bin/python -m pytest -q apps/api/tests/test_kernel_contract_checker.py apps/api/tests/test_kernel_reference_watch.py apps/api/tests/test_kernel_manifest_mock.py apps/api/tests/test_kernel_manifest_client.py
```

Run each command below separately. **Each must print
`LOCAL_SPEC_CONFORMANCE=FAIL` and exit 1.** An exit 0 is a failed negative proof:

```bash
./.venv/bin/python scripts/check_kernel_manifest_contract.py --local --scenario partial
./.venv/bin/python scripts/check_kernel_manifest_contract.py --local --scenario invalid-reference
./.venv/bin/python scripts/check_kernel_manifest_contract.py --local --scenario digest-mismatch
```

Then run repository verification; no generated output was edited by Step 8:

```bash
npm run generate:check
npm run architecture:check
npm run docs:check
npm run check:fast
./.venv/bin/python scripts/repo.py test-db up
npm run check
./.venv/bin/python scripts/repo.py test-db stop
```

Separately, with the read-only credential already supplied in the environment:

```bash
./.venv/bin/python scripts/check_kernel_references.py
```

Record the exit code and JSON as source-reference evidence only. A missing real
producer remains DEFERRED even if both local and reference checks pass. After
the owner merges/deploys the workflow, inspect the first scheduled run on the
default branch in GitHub Actions and record the evidence described above.
Nothing in this handoff claims that a workflow has been dispatched or deployed.

## Real producer delivery gate (separate integration activity)

The Kernel API owner supplies the actual authoritative endpoint OpenAPI,
canonical positive/negative response fixtures, producer commit and deployed
tenant/region/service-auth configuration. Do not invent producer artifact paths
or a delivery date. The Portal integration owner must pin those artifacts and:

1. Compare actual schema/strictness, complete-response behavior, byte-level
   semantic digest, timestamp/order stability, auth encoding, TLS, HTTP errors,
   tenant/region authorization and browser exclusion with the provisional v1.
2. Verify the actual deployed selected product and paid metric/unit/enablement,
   separately approved quantity and release. The test metric and local token
   never provide this evidence (G1/G4).
3. Run real consumer-versus-producer conformance, including malformed/partial,
   duplicate/owner/scope/digest/auth failures and multiple metrics per product;
   record the deployed producer commit and actual PASS/FAIL. Local mock PASS and
   source-reference PASS cannot substitute for that result.
4. Establish/renew actual producer wire-drift alerts before real publication or
   purchase. Reuse the existing Integration/configuration seam for a compatible
   endpoint; an incompatible endpoint requires a narrow reviewed reconciliation.
   Never weaken validation or promise URL-only switching across incompatibility.
5. Preserve G2 account-specific LBX evidence, G3 commercial/legal approvals and
   G5 later purchase/recovery/cycle/usage/E2E gates. Existing simulated mapping
   history stays simulated after any URL/environment change. Real production
   configuration remains refused until its separate enablement work is approved.

Implementation edits, independent review, human command results, schedule
operation and real-producer conformance must be recorded separately. No tests,
checks, generators, migrations, workflows or live provider requests were run
by the Step 8 implementation agent; no Git writes were performed.

Executed commands were limited to read-only `pwd`, `rg`/`rg --files`, `cat`,
`sed`, `git status --short`, `git diff --stat` and `git diff -- <changed files>`,
plus read-only GitHub file fetches at the recorded Kernel pin. Source changes
used `apply_patch`. The checker, reference watch, workflows and all verification
commands above have not been executed.
