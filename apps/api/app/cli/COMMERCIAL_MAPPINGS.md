# ANY-664 Step 5 operator and dependency handoff

Step 5 is implemented in commit `9cb7e340`. The final review correction scopes
offer identity to tariff + service + period; the owner will commit/push it.
Only formatting and lint of affected Python files are run for this correction;
tests, generators, builds, migrations, Compose and live provider requests are
not run. Runtime acceptance of this correction and real
Kernel/LBX/commercial/legal enablement remain unverified.
Ruff format and Ruff check passed on the six affected Python files.

## Restricted command and configuration

Run the entrypoint from the repository root with the repository-root Python:

```bash
PYTHONPATH=apps/api ./.venv/bin/python -m app.cli.commercial_mappings query --offer-id selected-offer:v1:701:1001:901
PYTHONPATH=apps/api ./.venv/bin/python -m app.cli.commercial_mappings query --offer-id selected-offer:v1:701:1001:901 --revision 1
PYTHONPATH=apps/api ./.venv/bin/python -m app.cli.commercial_mappings dry-run --proposal /absolute/operator-inputs/proposal.json
PYTHONPATH=apps/api ./.venv/bin/python -m app.cli.commercial_mappings publish --proposal /absolute/operator-inputs/proposal.json --expected-previous-revision 0
```

`selected-offer:v1:701:1001:901` identifies the existing **SIMULATED** selection:
tariff `701`, tariff service `1001`, period `901`. It is never a production
default. Copy the complete `billing_offer_id` returned by `dry-run`/`publish`
into `query --offer-id`; a tariff ID alone does not identify an offer.
There are no `--actor`, `--real` or `--approved` flags.
Commands emit JSON; safe refusals use `detail.code` on stderr with exit code 1.
Each successful command includes its execution principal and command start time
in `operator_audit`. Publication permanently records principal, reason and time.
Keep operator inputs, audit reasons and approval references free of secrets and
customer/payment data. No raw source responses or credentials are output.

Use the existing required API environment and these typed settings:

- `MAPPING_OPERATOR_UIDS`: JSON array of allowed effective numeric process UIDs,
  for example `[29001]` in isolated tests. Default is empty. Configure the UID
  of the actual CLI process/container; a host username or `USER`/`LOGNAME` is
  irrelevant. The principal is `os-euid:<number>`, an execution account, without
  human attribution or any implied commercial/legal approval. Unsupported OS
  identity resolution fails closed.
- `MAPPING_ACCOUNT_ID`: one explicit billing-account scope, independent of
  source credentials. Tenant/region come from `INSTANCE_TENANT_ID` and
  `INSTANCE_REGION`; current supported deployment remains `anytoolai/ru`.
- `MAPPING_APPROVAL_FILE`: absolute path to a separately reviewed, versioned
  `ApprovedMapping` JSON artifact. It is configuration, never a proposal flag.
- `MAPPING_SOURCE_INPUTS_FILE`: absolute path to the Step 4
  `SelectedOfferInputs` JSON artifact proving selected account currency,
  credential binding, completeness, applicability and policy. For isolated
  tests the existing `apps/api/tests/fixtures/lbx/selected_offer/inputs.json`
  is explicitly simulated. Normal runtime never loads it automatically.
- `MAPPING_LOCK_TIMEOUT_SECONDS`: finite transaction lock limit, default 2s,
  bounded by remaining preflight time. This is Portal policy, not a provider SLA.

OS identity, deployment configuration, approval-artifact ownership and DB-secret
access form the trusted security boundary. An approval file is a configured
content/version reference, not a signature-verification service. The deployment
owner must control these files and settings independently of proposal authors.
Do not populate approvals from a publisher read as an automatic runtime action.

`query` needs only normal DB/instance settings, account scope and the UID
allowlist. Both source configurations and both input-file settings can be
absent. It constructs no source client, admission owner or event loop. For
source operations supply the existing `KERNEL_BASE_URL`,
`KERNEL_SERVICE_TOKEN`, `LBX_BASE_URL`, `LBX_EXTERNAL_BILLING_ACCOUNT_ID`,
`LBX_SERVER_USERNAME`, `LBX_SERVER_PASSWORD`, and shared `PREFLIGHT_*` policy.
The configured LBX account must equal `MAPPING_ACCOUNT_ID`. Existing all-or-none
source validation still applies; clear all source settings for offline queries.

For explicit local development authorization in the same OS process context:

```bash
export MAPPING_OPERATOR_UIDS="[$(id -u)]"
```

Run that inside the executing container when the CLI runs in a container. It is
not a production default. Admission limits retain the existing process-local
ownership: one CLI evaluates one operation, and simultaneous CLI processes
multiply source capacity. Deployment operators must bound their process count;
this change introduces no distributed capacity or provider-SLA guarantee.

## Explicit input contracts

`composition.mapping_operator.MappingProposal` is schema version 1 and contains
`selection` (the existing `SelectedOfferRequest`), `technical` and a nonempty
audit `reason`. `TechnicalBinding` contains `product_id`, `metric_key`, `unit`,
strict positive integer `allowance` and `metric_basis` (`SIMULATED` or
`VERIFIED`). No quantity is inferred from price or LBX commercial units.

`SelectedOfferInputs.calendar` is required for each fresh dry-run/publication.
It contains `external_billing_account_id`, an explicit IANA `timezone`, and an
`evidence` reference/revision/basis covering that account's calendar. Missing,
wrong-account, unknown-zone or DOCUMENTED-only configuration refuses publication.
ACCOUNT_EVIDENCE must refer to independently confirmed account configuration;
SIMULATED is allowed only as simulated evidence in development/test. The example
Europe/Moscow zone is invented test configuration, not a confirmed LBX fact.
ANY-634 B10 did not establish a provider timezone. Never infer one from locale,
region, UTC or the host. The host must have the configured IANA zone available.

Composition compares the proposed `effective_on` with the configured account's
current date before and after source reads, using an injectable aware clock.
Both past and future dates refuse without substitution, including source reads
that cross account midnight. The existing policy interval `[valid_from,
valid_until)` and effective-price selection use that same validated date.
Calendar evidence is pinned in the selected digest and simulation provenance;
a calendar change therefore requires independent commercial reapproval. DB-only
query and browsing still accept valid immutable historical documents without a
calendar configuration. No subscription cycle/renewal interpretation is added.

`domains.catalog.mapping_evidence.ApprovedMapping` is schema version 1:

- `material`: exact `MappingMaterial`, containing scope, opaque selected
  offer/component/period/membership/effective-price references, complete Step 4
  material terms, technical binding, `digest_scope=selected_offer`, and the
  approved `selected_evidence_digest`. This MVP explicitly records
  `component_classification=CAPABILITY_BEARING` and
  `external_usage_reporting=none`.
- `approved_material_hash`: `sha256:` plus SHA-256 of
  `material.canonical_json()` UTF-8 bytes, using Step 4 canonical decimal/date
  serialization. This checks exact approved material, independently of the
  publication fingerprint and volatile observations.
- `revisions.technical`, `.commercial`, `.legal`: each has immutable
  `reference`, `revision`, `content_hash` (`sha256:<64 lowercase hex>`) and
  `basis` (`SIMULATED` or `VERIFIED`). Simulated references must start with
  `SIMULATED:`. Pin the separately approved technical quantity and exact
  commercial/policy/legal content. These hashes reference approved content;
  they are not fabricated legal approval or real producer conformance.

Amounts and selected commercial quantity in JSON use exact decimal strings;
JSON-number money is rejected. Dates are ISO calendar dates. Input files are
strict, reject extra fields and are limited to 1 MiB. Real-client transport
fixtures and the separately prepared simulated approval fixture live only in
test support. Tests never substitute a second normalizer or business evaluator.

`dry-run` requires that same independent exact approval and reports a candidate
evaluation with `persisted=false`; it creates no DB session. `publish` reads
both sources again and requires `--expected-previous-revision` (0 initially).
There is no reusable dry-run token or stored-digest shortcut. The provisional
Kernel remains SIMULATED even at a different compatible URL; any simulated
source/metric/approval taints the whole result. Only development/test permits
this path. Production fresh evaluation remains refused until separately
verified G1-G4 composition exists; the CLI cannot enable it.

## Persistence, equality and failures

The Step 5 `MappingMaterial.billing_offer_id` property derives
`selected-offer:v1:<tariff_id>:<tariff_service_id>:<period_id>`; each opaque source
reference is percent-escaped independently before joining, preventing delimiter
collisions. Account scope remains separate. `references.offer` still means the
original LBX tariff ID, `references.component` the tariff service ID, and
`references.period` the period ID. Step 4 normalization and source evidence are
unchanged. This derived ID is not added to serialized approved material, so its
existing approval hashes and evidence fingerprints retain their meaning.

Publication, advisory locking, head/history lookup, stored-document validation
and operator query all use this complete ID. Two services or periods of one
tariff have separate histories, each starting at revision 1. A repeated
publication is idempotent only within that exact history. Existing immutable
rows and pins are not rewritten or deleted, and composite lookups never fall
back to tariff-only keys.

The existing `CommercialMappingRevision` table and first-install
`trg_guard_commercial_mapping_revision` guard are reused unchanged. **No new
migration or generation is required.** On an uninitialized local DB, a human
runs the existing `npm run migrate:api` before operator publication. No source
projection table is read or written.

`mapping_document.schema_version=approved-offer-v1` stores exact approved
material, approval revisions, `digest_scope=selected_offer`, reproducible LBX
selected evidence, the approved material hash,
source modes, manifest version/generation time, field
provenance, source observations, evaluated/published times, principal and
reason. `catalog_digest` pins only selected dependencies, never an atomic LBX
account snapshot; `catalog_version` is NULL because these reads prove none.
Persisted simulation never upgrades after environment or endpoint changes.
A genuine future revision means `PUBLISHED_APPROVED_UNVERIFIED_NOW`, never
evergreen SELLABLE. Simulated evidence is explicitly `SIMULATED`.

The publication fingerprint covers selected source identities/dependencies,
exact terms, technical binding/quantity, approval revisions and evidence mode.
It excludes all observation/publication timestamps and the full manifest
version, so an unrelated product change does not manufacture material drift.
Changed material must exactly match a separate replacement approval.
Changed technical or commercial material also requires a changed corresponding
approval pin; the same reference/revision cannot be rewritten with new content
or provenance. Editing an artifact hash does not reuse an old approval. After CAS and under
the existing account/offer advisory lock, the publisher checks all retained
revisions in that history, not only its head. Each technical/commercial/legal
pin keeps its original hash, provenance and corresponding material meaning;
an intervening revision cannot free an old pin. Truly unchanged content can
reuse a historical pin. History reads are streamed and share the remaining
publication deadline; no new table, registry or transaction owner is introduced.

After HTTP and cleanup, synchronous Application opens a short PostgreSQL
READ COMMITTED transaction, sets bounded local statement/lock timeouts, takes
the transaction advisory lock, then re-reads the account/offer head. Lock key
v1 is signed first 64 SHA-256 bits of compact UTF-8 JSON
`["payments-portal/commercial-mapping/v1", account_id, offer_id]`; the actual
SQL predicates and existing uniqueness remain authoritative. This serializes
first inserts too. Identical material returns the existing row before CAS,
including a retry using the previous expected revision. Otherwise a stale
expected revision conflicts; a matching expectation inserts latest + 1.
No UPDATE, DELETE, automatic rebase or provider mutation occurs.

Preflight expiry is rechecked after locking and immediately before commit;
DB waits never renew its absolute deadline. An uncertain commit triggers an
authoritative DB-only read of the attempted scoped revision. A matching row
is reported with `recovered_commit=true`; unresolved results return
`mapping_commit_uncertain_query_required`, without replay. Query the exact
account/offer/history before deciding on a new explicitly fresh attempt.

Safe feature failures include `mapping_operator_forbidden`,
`mapping_operator_identity_unavailable`, `mapping_input_invalid`,
`mapping_approved_material_mismatch`, `mapping_scope_mismatch`,
`mapping_revision_conflict`, `mapping_storage_busy`,
`mapping_publication_expired`, `mapping_simulation_forbidden`,
`mapping_stored_evidence_invalid`, and `mapping_not_found`. Existing Kernel,
selected-offer and preflight error meanings remain intact. DB exceptions stay
DB exceptions inside the application; the CLI emits `mapping_database_error`,
without translating DB failure into a provider outage.

## Callable dependency handoff

- `composition.mapping_operator.fresh_mapping_evaluation(configuration,
  proposal, approval, source_inputs, principal)` owns async outer source I/O
  through the existing clients, common admission and Step 4 normalizer. It
  returns `FreshMappingEvaluation(document, deadline)` after closing resources.
  `deadline` is the original absolute monotonic work deadline; pass it unchanged.
  Tests may inject HTTP transports at this composition seam only.
- `domains.catalog.mapping_evidence.evaluate_mapping(...)` is the one
  synchronous vendor-neutral evaluator. `MappingDocument` is the one immutable
  schema/evidence validator. `publication_fingerprint(...)` defines equality.
- `domains.catalog.publication.publish_mapping(session_factory, evaluation,
  expected_previous_revision, deadline, lock_timeout_seconds,
  allow_simulated=False)` owns synchronous transaction/commit lifetime and
  returns stored revision, the separate current evaluation, insertion status
  and commit-recovery status. Each operation creates/closes its own Session;
  no connection is retained during source HTTP.
- `domains.catalog.publication.query_mapping(session_factory, scope, offer_id,
  revision=None, allow_simulated=False)` is the DB-only read capability for the
  next catalog step, independently of CLI authorization. It returns
  `StoredMapping(id, revision_number, document)`. Production/public readers must
  derive simulation policy from trusted environment, never a browser flag.
- `validate_stored_mapping(row, scope, offer_id, allow_simulated)` exposes the
  same validation policy for future catalog head selection. Select the latest
  row per exact account/offer first, then validate schema/mode/scope, column
  consistency and fingerprints. An invalid latest row must remain unavailable;
  never fall back to an older one. Explicit historical queries are distinct.
  Build safe public DTOs in the next step; full audit evidence is operator-only.

## Human verification order (not executed)

From `/home/wstanley/www/work_unirec/payments-portal`:

```bash
export PATH="/home/wstanley/www/work_unirec/payments-portal/.venv/bin:$PATH"
./.venv/bin/python -m pytest -q apps/api/tests/test_commercial_sellability.py
make test_db_up
./.venv/bin/python -m pytest -q apps/api/tests/test_commercial_mapping_postgres.py
npm run test:api:postgres
make test_db_stop
npm run architecture:check
npm run check:fast
npm run check
```

Use the existing worktree test DB configuration; pytest owns creation, migrated
schema and removal of the disposable `_tests` database. Do not point these tests
at a developer/application/production database. If direct pytest lacks the
worktree's test DB variables, use `npm run test:api:postgres` (the harness supplies
them). Existing DB guards require the current baseline migration; there is no
Step 5 schema upgrade. Generation is unnecessary because this step adds no
Portal HTTP contract.

The focused PostgreSQL suite includes the restricted CLI dry-run → publish →
query flow, positive real-client/normalizer/evaluator inserts, source outage and
saturated-admission-independent query, identical/different first-publication
contenders, stale revision CAS, separately approved replacement/history,
independent first revisions/query/idempotency for two services of one tariff,
rollback after flush, bounded lock wait/expiry, actual UPDATE/DELETE guard
refusal, uncertain commit acknowledgement and production/configuration-switch
simulation exclusion. Test fixtures certify no live provider or legal facts.

After independent review and human checks, record actual evidence separately.
Runtime/database/concurrency outcomes for this identity correction are **NOT_RUN**.
Real product release/metric/quantity, selected account/provider proof, approved
commercial/legal inputs, real Kernel conformance, and later purchase/paid-access
gates remain open. Local harness wiring and public catalog/browser work belong
to their later selected steps and are not implemented here.
