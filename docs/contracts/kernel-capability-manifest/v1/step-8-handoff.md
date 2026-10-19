# ANY-664 Step 8: local conformance and deferred real Kernel API

Status: source implementation; human verification pending. This handoff adds
no actual producer evidence and does not reopen Steps 1, 2 or 7.

```text
LOCAL_SPEC_CONFORMANCE=NOT_RUN
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

## Owner decision and retained CI

On 2026-10-19 the owner removed external Kernel source monitoring from ANY-664:
the real Capability Manifest API does not exist yet. The dedicated workflow,
reference script and exclusive tests are removed without replacement. No daily
schedule, source-access credential or external-monitor status is required.
Historical source SHA and links in the [contract provenance](README.md#authority-and-provenance)
remain unchanged; they document origin, not actual API compatibility.
The retained Portal spec pin is `05d3fcb6a965fcd053d713f49669d1dd25c22978`;
the Kernel identity/composition pin is `079eb03e28d7a50b980795c63c3e4533b785d11f`.

[CI](../../../../.github/workflows/ci.yml) still runs the independent local
manifest checker and the existing fast test suite, including local negative
conformance tests. Mock, typed client, schema, fixtures and Step 7 walkthrough
remain intact. **The local provisional contract is checked; the real Kernel API
is unverified (DEFERRED_NOT_IMPLEMENTED).** Real API verification is a separate
mandatory task before real publication or sales, as specified below.

## Exact manual verification order

From `/home/wstanley/www/work_unirec/payments-portal`, with the existing locked
root `.venv` and web dependencies installed (Unix/WSL):

```bash
source .venv/bin/activate
./.venv/bin/python scripts/check_kernel_manifest_contract.py --local
./.venv/bin/python -m pytest -q apps/api/tests/test_kernel_contract_checker.py apps/api/tests/test_kernel_manifest_mock.py apps/api/tests/test_kernel_manifest_client.py
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
   historical source pins cannot substitute for that result.
4. Establish/renew actual producer wire-drift alerts before real publication or
   purchase. Reuse the existing Integration/configuration seam for a compatible
   endpoint; an incompatible endpoint requires a narrow reviewed reconciliation.
   Never weaken validation or promise URL-only switching across incompatibility.
5. Preserve G2 account-specific LBX evidence, G3 commercial/legal approvals and
   G5 later purchase/recovery/cycle/usage/E2E gates. Existing simulated mapping
   history stays simulated after any URL/environment change. Real production
   configuration remains refused until its separate enablement work is approved.

Implementation edits, static review, human command results and real-producer
conformance must be recorded separately. No tests,
checks, generators, migrations, workflows or live provider requests were run
by the Step 8 implementation agent; no Git writes were performed.

The final owner correction used read-only source/PR inspection, source edits and
formatting/lint only. No tests, build, integration checks, generator, migration,
workflow dispatch, commit or push was performed for the correction.

## CodeQL operator-output disposition (#3 and #4)

Both alerts use `py/clear-text-logging-sensitive-data`. At PR head
`a7e0b372a2d69102502dd576fd93052e05fc88d9`, the flagged sources are
`billing_offer_id`: CLI query/dry-run/publish (lines 59/87/108), plus the
walkthrough evaluation (line 104) and delegated query paths. The value is
`selected-offer:v1:<tariff_id>:<tariff_service_id>:<period_id>`, derived from
selected numeric source identities, not a password/token. JSON serialization
and `print(output)` are the intended machine-readable operator result.

The review also follows the whole document, not just that derived key:

- `authorize_operator` checks the effective OS UID against the explicit,
  default-empty `MAPPING_OPERATOR_UIDS` before proposal/approval/source-input
  reads, source calls or DB queries. Caller flags cannot choose the principal.
  The trusted boundary includes OS execution, environment/configuration,
  separately controlled input files and DB credentials; this is not an HTTP
  administrator authentication mechanism. An account allowed to replace that
  configuration is already inside this boundary.
- `reason`, approval/evidence references and revisions, policy text, scope,
  account IDs and publisher UID are deliberately preserved, including when
  querying immutable historical evidence. These values can be private. Type
  validation/hashes do not sanitize free text or prove a URL has no secret.
  Inputs must use credential-free document references (no signed/access-token
  URLs) and contain no credentials, card data or unnecessary personal data.
  Stdout and any redirected evidence must stay within the same restricted
  operator access boundary; do not send full results to shared application
  logs, telemetry, public CI artifacts or the browser.
- Fresh evaluation constructs a typed `MappingDocument` from normalized selected
  terms, explicit approvals and provenance. The selected dependency JSON is
  assembled field by field; raw provider payloads, unselected additional fields,
  Settings, DB URLs, HTTP headers, LBX username/password/auth token and Kernel
  service token are not serialized. Query validates stored scope/digests and
  returns the same immutable document. The public catalog uses its own DTO
  projection, not this CLI output.
- The walkthrough first requires development mode, authorized UID, worktree
  PostgreSQL database and the named simulated account; it uses recorded LBX
  transport and the ordinary Kernel client. Its prepare response is only a
  SIMULATED marker; dry-run/publish retain the same private result boundary,
  and query delegates to the authorized DB-only CLI.

Disposition: false positives for confidential data **logging** at these two
sinks: intentional private data is returned to its authorized local operator,
without a less-trusted log destination in these entrypoints. This is not a
claim that every string is public or generically redacted. No CLI field,
immutable audit value, permission, command behavior, scanner rule or suppression
is changed. Existing credential/unselected-PII canary coverage is in
`test_cli_dry_run_publish_and_query_use_same_real_path` and
`test_fresh_http_publication_faults_outage_restart_and_recovery`; those tests were
not run in this correction.

On 2026-10-19 GitHub confirmed both alerts
[#3](https://github.com/gushinets/payments-portal/security/code-scanning/3) and
[#4](https://github.com/gushinets/payments-portal/security/code-scanning/4) as
**Dismissed / false positive**. Both PR review threads contain the rationale and
are confirmed resolved. ANY-664 Linear requirements and PR #139 description are
aligned; the source correction remains local, with no commit/push or new CI run.

Formatting/lint passed for the affected Python code. To recheck the existing
operator/privacy regressions manually, use the PostgreSQL harness (which derives
the disposable test DB configuration) from the repository root:

```bash
./.venv/bin/python scripts/repo.py test-db up
npm run test:api:postgres
./.venv/bin/python scripts/repo.py test-db stop
```
