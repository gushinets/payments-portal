# ANY-812 — Canonical enum guard and internal-contract rules

Status: active; Steps 1–2 implemented; rebased full check passed; human merge approval pending.
Created: 2026-11-03
Owner: ANY-812 delivery agent
Execution branch: `ANY-812`

## 1. Objective, authority and verified baseline

Deliver only [ANY-800](https://linear.app/paveldik/issue/ANY-800) steps 1–2 in
one reviewable PR targeting `main`: repair canonical enum ownership enforcement
and reconcile development/review rules. The owning delivery issue is
[ANY-812](https://linear.app/paveldik/issue/ANY-812).

Follow Mikhail Gushinets's approval of 2026-11-02 in ANY-800, the narrower agreed
rules in ANY-812, applicable [root AGENTS](../../../AGENTS.md),
[documentation AGENTS](../../AGENTS.md), API/web AGENTS where applicable,
[delivery workflow](../../engineering/AGENT_WORKFLOW.md),
[coding conventions](../../engineering/CODING_CONVENTIONS.md) and
[testing guidance](../../engineering/TESTING.md).
Architectural authority remains [ADR 0005](../../architecture/decisions/0005-external-billing-boundary.md),
the accepted external-billing and Portal–Kernel design baselines, and the narrow
live-source amendment linked by that ADR. This ticket changes none of their
commercial, trust or paid-access decisions.

Verified on 2026-11-03:

- GitHub `main` and local `origin/main` identify
  `366d902635a699c18b90e0a619f74bb6b0e680c2`. The local branch named `main` was
  older; do not use it without updating.
- The source checkout for the research/draft is `ANY-715` at
  `76ea1a73125c0ef44f3145df2c3a1bfb882c138c`, with an uncommitted Step-2 draft
  and unrelated branch changes. Preserve that working tree.
- Main declares 14 canonical enums; the guard inventories 13, omitting
  `ExternalCreateOperationState`. `WebhookDeliveryState` belongs to the parallel
  branch and must not be introduced by this ticket.
- Main still represents `BillingWorkItem.work_state`,
  `ExternalBillingWebhookDelivery.processing_state` and
  `ManualReviewCase.case_state` as plain strings. The draft's two-field inventory
  must be corrected when transferred.

Revalidated for the 2026-11-10 rebase: target `main` is
`0b4d150314fd29da515865524573dfbd8c705e37` and includes merged ANY-715 and ANY-765. It has
15 canonical enums, including `WebhookDeliveryState`; only
`BillingWorkItem.work_state` and `ManualReviewCase.case_state` remain
plain-string ORM states. The dated baseline and earlier verification below
describe the original source snapshots, not the current target. Preserve the
integrated worker, retained webhook enum/schema, generations, indexes, leases,
recovery behavior and ANY-765 paid-access derivation/schema while applying this
ticket's ownership/policy changes. The dated full-check PASS below belongs to
the November 3 base and does not certify this new target.

Planning evidence, obtained from temporary clean main snapshots:

- `test_repository_docs.py`, `test_model_enums.py` and
  `test_billing_reconciliation_models.py`: **209 passed** with
  `KERNEL_MOCK_ENABLED=0`.
- Documentation and architecture commands: **passed**.
- Existing direct-provider and removed-model architecture regressions:
  **2 passed**, 49 deselected.
- Old guard incorrectly accepts the omitted enum's duplicate, absolute/relative
  facade imports, and a future canonical declaration's duplicate/facade import.
  The canonical/provider positive probe remains accepted.
- Full canonical checks were not run during planning. Earlier ANY-715 results,
  including the TypeScript tooling failure, remain historical evidence.

Existing tests cover one canonical duplicate, removed facades, relative imports,
provider exceptions, approved enum values and text-backed persistence. They do
**not** establish complete inventory coverage, future-addition protection,
per-root discovery or authority-source failure handling. Reuse the existing
persistence assertions; add the missing guard regressions.

The prior research canvas, audit inventory and local draft are dated supporting
evidence, not prerequisites or normative sources. All essential requirements are
recorded here and in ANY-812. Planning validation returned **READY WITH GATES**:
before code edits, save this plan with repository-relative links and establish
an isolated branch from verified remote main. This document does not claim that
either approved implementation step is complete.

## 2. Ordered implementation

### A. Establish an isolated delivery baseline

- Create a clean `ANY-812` branch from freshly verified remote main using an
  isolated worktree. Preserve the dirty ANY-715 checkout; do not stash or move
  its changes into this delivery.
- Record the actual starting SHA and any intervening relevant changes here.
  Reassess affected tests before editing tooling.
- Keep this single English plan under `docs/exec-plans/active`; retain progress,
  discoveries, decisions and separate Step-1/Step-2 evidence here.
- Compare the uncommitted draft against its ANY-715 base and current main.
  Transfer only approved rule/review changes; do not cherry-pick the branch or
  import its worker, webhook, schema or operational documentation changes.
  If the local draft is unavailable, use the complete rules below and ANY-812
  rather than making that unpublished artifact a delivery dependency.

Completion: a clean, independently reviewable main-based branch contains this
plan, with no inherited ANY-715 implementation changes.

### B. Add regressions before correcting the guard

Extend [test_repository_docs.py](../../../apps/api/tests/test_repository_docs.py),
retaining the existing fixture approach.

- Supply realistic canonical authority source in ordinary synthetic
  repositories. Keep authority-absence fixtures intentionally incomplete.
- Parameterize duplicate-definition and forbidden facade-import cases over
  every canonical declaration in the execution baseline, including
  `ExternalCreateOperationState`.
- Add a future enum only to a fixture's canonical source, without updating
  `__all__`, exports or another inventory. Reject its external duplicate and
  absolute/relative facade imports.
- Exercise distinct supplied roots in the same process to expose
  checkout-global or cached inventory discovery.
- Cover missing, syntactically invalid and empty authority sources with
  actionable diagnostics.
- Preserve positive cases: canonical definitions, canonical imports/re-exports
  and unrelated Integration/provider enums. Preserve existing relevant
  absolute/relative forbidden-import paths.
- Retain removed-model, historical-enum and direct-provider restrictions.

Run the new cases against unchanged tooling. Record expected failures and their
precise assertions. Positive cases and unrelated existing guards must remain
green. These checked-in failures provide the required regression evidence;
planning probes alone do not replace them.

Completion: the missing guarantees have reproducible failing tests before the
tooling correction, with existing permitted behavior characterized.

### C. Implement the smallest ownership correction

Change [scripts/repo.py](../../../scripts/repo.py):

- Read and parse `apps/api/app/models/enums.py` relative to the supplied `root`
  on each checker invocation.
- Derive the inventory from top-level class declarations in this dedicated
  enum-owner module; require a readable, parseable, nonempty authority when an
  API application tree is present. Preserve the existing no-application-tree
  no-op behavior.
- Use that inventory consistently for duplicate detection and forbidden
  billing-facade symbol imports.
- Retain historical removed enum names as an independent fixed prohibition
  set. Preserve their use by removed-architecture checks.
- Remove the manually synchronized current-enum inventory and its dependent
  static union.
- Preserve `check_canonical_persisted_model_layer(root: Path = ROOT) -> list[str]`,
  existing import resolution and normal repository diagnostics. Missing or
  malformed authority must fail visibly rather than silently disable protection.

Do not import application/ORM modules, introduce a general enum-discovery
framework or add runtime assignment analysis. Public APIs, models, migrations,
persisted values and generated contracts remain unchanged.

Completion: all Step-B regressions pass, future declarations acquire protection
without another inventory edit, permitted cases still pass, and historical
removed-architecture guards remain effective.

### D. Reconcile rules and review inputs

Use [CODING_CONVENTIONS.md](../../engineering/CODING_CONVENTIONS.md) as the
detailed rule owner. Reconcile architecture/data-model explanations,
root/API/web AGENTS digests, delivery workflow, correctness checklist, review
configuration and documentation navigation.

The consolidated rules must establish:

- **Concrete shared structures:** required/optional fields and consumed nested
  shapes; appropriate dataclasses/value objects, boundary models/decoders or
  serialized `TypedDict`. Bare dictionaries, broad aliases and erased dataclass
  fields are insufficient; sufficient primitives need no wrapper.
- **Single vocabulary ownership:** enums for closed states/outcomes/kinds/scopes,
  `StrEnum` for textual Python vocabularies, canonical `app.models` ownership
  for persisted vocabulary. Use symbolic members throughout annotations,
  construction, defaults, assignments/transitions, comparisons/membership/match,
  queries/DML/upserts and results.
- **All model statuses/states:** include singleton ORM, dataclass and response
  states, even without transition code. Raw string types or string `Literal`
  unions are insufficient. Enum-member narrowing, boolean literals and actual
  schema/protocol tags remain legitimate; an owner constant can suffice for a
  single tag or diagnostic identifier. A singleton outcome is not a schema-tag
  loophole. Cover queue, review, observation, operator, catalog, health,
  diagnostics/metrics and local UI concepts where the slice owns finite meanings.
- **Complete use-path review:** cover client/server defaults, positive
  factories, CHECK constraints, partial indexes, serialization and UI consumers.
  Derive active SQL values from their owner or provide focused parity checks;
  use existing SQLAlchemy facilities. Retain historical migration and
  independent compatibility literals.
- **Actual boundaries:** validate external and structurally consumed retained
  data once, then preserve useful nested, helper and callable types inward.
  Annotations and `frozen=True` do not validate runtime input. Avoid repeated
  internal validation and decoders for unread retained data.
- **Proportionate construction and exceptions:** centralize repeated identity
  and initialization invariants without requiring factories everywhere; preserve
  intentional use-case differences and Application transition/transaction
  ownership. Permit genuine maps, opaque requests, physical JSON and necessary
  SDK/raw-decoding/redaction seams with an identifiable owner, consumer and
  reason. Known-key objects are not genuine maps. Preserve empty payloads absent
  a consumer requirement.
- **Compatibility:** preserve keys, omitted/null distinctions, spelling,
  versions, equality/coalescing, digests/fingerprints, identities, receipts,
  history, transactions, leases/fences, enqueue generations, counters and
  deadlines. Do not merge or rename `done`/`completed`.
- **Provider independence:** Portal concepts stay provider-neutral; Integration
  owns vendor DTOs, numeric protocol symbols (`IntEnum` where appropriate),
  normalization and unknown-value handling. Raw source values stay raw until
  their owning decoder; opaque IDs, arbitrary source codes/currencies, user text
  and ordinary quantities are not automatically enums. Locally recognized
  decision subsets have an owner. Do not impose LBX fields, calendars or
  currency policy on other integrations.
- **Generated authority:** preserve backend → OpenAPI → generated frontend
  contracts and the shared transport boundary. Local UI vocabularies have local
  symbols; backend enums are not hand-copied. Legal/locale/capability values
  retain their existing source/generation ownership. Type-only frontend
  generation remains explicit debt.
- **Incremental application:** apply rules to new/materially changed contracts
  and affected producers/consumers, not every declaration in a touched file.
  Require a current consumer/invariant benefit and KISS/YAGNI; apply DRY to
  repeated knowledge rather than similar syntax. Do not introduce speculative
  models, validators, factories, state machines, retries, registries, adapters
  or configuration. Explain bounded exceptions near code or in the PR, reuse
  existing debt ownership, and avoid per-field waiver registries or blanket
  casts/suppressions. Routine choices need no approval; unresolved behavior,
  supported/retained-value, compatibility, trust, authorization, ownership or
  unavoidable scope decisions require focused escalation with the smallest
  viable option. Do not request approval again for an existing decision.
- **Honest evidence:** distinguish a confirmed rule/enforcement gap from a
  reproduced runtime defect. A green suite or additional classes do not prove a
  missing guarantee. Documentation alone does not install a Python checker or
  migrate existing runtime contracts.

Include positive and negative examples: `ResolutionOutcome`/`ResolutionResult`
with optional `observation_id`, singleton `UserStatus`/`PersistedEnumType`
mapping, scattered raw outcomes, a fixed snapshot typed as `dict`, erased nested
dataclass fields, a legitimate map and an opaque provider request with typed
consumed evidence. Do not duplicate the full vendor DTO in Domain.

Specific reconciliation:

- Update [ARCHITECTURE.md](../../../ARCHITECTURE.md) and the
  [data-model reference](../../architecture/payment-portal-data-model.md) to
  describe the actual target's plain-string state fields and related
  kind/scope/classification debt truthfully. Preserve integrated ANY-715 schema
  and runtime facts without introducing additional runtime changes.
  TEXT/VARCHAR storage and existing `PersistedEnumType` remain;
  do not introduce PostgreSQL native ENUM.
- In [the reconciliation model test](../../../apps/api/tests/test_billing_reconciliation_models.py),
  rename the test and its “open” variables/comments to describe current
  enum/plain-text representation. Preserve every physical-schema assertion,
  including the target's text-backed `WebhookDeliveryState`. Existing debt does not permit new
  arbitrary runtime states, and this wording change does not implement narrowing.
- Replace the draft's “guard gap remains future work” wording with the completed
  ownership guarantee only after Step C passes. Other enforcement and migration
  limits remain explicit under ANY-800.
- Add [the correctness checklist](../../engineering/review-checklists/correctness.md)
  to the existing [AI-review configuration](../../../.github/ai-review.yml)
  `policy.always` inputs and link it from the delivery workflow. Keep AGENTS
  summaries concise and link the detailed rule owner; update
  [documentation navigation](../../README.md).
- Make pre-edit coverage assessment, bug regression-first evidence and
  behavior-preserving characterization explicit in the workflow. Reconcile
  testing guidance's blanket factory-migration wording with proportionate setup
  reuse, retaining shared fixture/resource lifecycle ownership.
- Keep essential requirements in committed guidance; do not add redundant rule
  systems or depend on unpublished audit artifacts.

Completion: conventions, current-state explanations, AGENTS digests, development
guidance and actual review inputs agree on every ANY-812 rule, with examples and
bounded exceptions; runtime and schema assertions remain truthful.

## 3. Verification and review

Run focused regressions before and after the fix, then the complete
repository-documentation, model-enum, reconciliation-model and architecture
test modules. For direct focused runs from the delivery worktree root:

```bash
PATH="$PWD/.venv/bin:$PATH" KERNEL_MOCK_ENABLED=0 PYTHONPATH=apps/api:. python -m pytest -q apps/api/tests/test_repository_docs.py -k canonical_persisted_model_guard
PATH="$PWD/.venv/bin:$PATH" KERNEL_MOCK_ENABLED=0 PYTHONPATH=apps/api:. python -m pytest -q apps/api/tests/test_repository_docs.py apps/api/tests/test_model_enums.py apps/api/tests/test_billing_reconciliation_models.py apps/api/tests/test_architecture.py
```

Use the delivery worktree's canonical root `.venv` on PATH and
`KERNEL_MOCK_ENABLED=0` for repository commands. Obtain dependencies using the
documented setup workflow; do not copy another checkout's runtime configuration.
Run:

```bash
npm run docs:check
npm run architecture:check
npm run generate:check
npm run check:fast
npm run check
git diff --check
```

- For the full check, use the supported worktree-local PostgreSQL lifecycle
  where available. Record passed, failed, blocked, skipped and unreached stages
  against the actual SHA.
- Recheck the historical TypeScript tooling failure on the clean execution
  baseline. If reproduced, isolate its evidence and owning delivery; do not fix
  unrelated tooling or weaken checks in this PR.
- No new persistence guarantee is introduced. PostgreSQL becomes mandatory for
  any actual persistence/migration change, which would require scope
  reassessment. SQLite probes are not concurrency evidence.
- Browser/provider journeys are not acceptance tests for this
  tooling/documentation-only change. Record them as not run unless required by
  another actual change. Local verification does not prove provider conformance
  or production launch readiness.

Review the full diff for correctness, ownership, compatibility, provider
independence and unnecessary machinery using the repository's independent review
guidance. Check all agreed rules against authoritative text, digests and actual
review inputs. Resolve findings and rerun affected checks; finish with the
broadest supported canonical verification. Record Step-1 and Step-2 review and
validation evidence separately within this one plan.

## 4. Progress, completion criteria and handoff

- [x] Read ANY-812, ANY-800 and Mikhail's approval; use the existing research and
  local draft without treating their branch snapshots as current main.
- [x] Revalidate main, assess existing tests and reproduce the ownership escapes
  using temporary repositories before implementation.
- [x] Self-validate the plan against the ticket, applicable instructions and
  actual main; resolve main/ANY-715 inventory and representation differences.
- [x] Establish the isolated main-based branch and save this plan; record the
  plan-only validation below.
- [x] Add checked-in failing Step-1 regressions before the correction.
- [x] Complete Step 1 with current/future inventory, facade paths, root isolation,
  authority diagnostics, permitted cases and historical guards passing.
- [x] Complete Step 2 with all agreed rules, examples, exception/escalation
  guidance and consistent authoritative/review surfaces.
- [x] Confirm that documentation/test wording distinguishes current
  representation debt from semantic openness and completed enforcement.
- [x] Confirm that no runtime/schema/wire change, Python checker rollout,
  generator migration, broad literal cleanup, factory/payload redesign or
  ANY-800 steps 3–8 entered the diff. No new paid-access authority, UI/legal
  change, speculative framework or unrelated baseline repair is authorized.
- [x] Record final-SHA checks and review findings with explicit dispositions;
  unresolved verification is not reported as passing.
- [x] Prepare one PR targeting main, titled
  `ANY-812 - Fix canonical enum guard and internal-contract rules`, linking
  ANY-812 and presenting separate Step-1/Step-2 evidence. Retain human merge
  approval; do not push/publish during this plan-only preparation.

Update this same plan throughout delivery and move it to `completed` only when
completion is supported by evidence. Do not mark the broader ANY-800 program
complete or introduce speculative child tickets. Broad refactoring is not a
condition for launching LBX Billing.

### Plan-only preparation evidence

- Created isolated branch `ANY-812` at the independently verified remote main
  SHA `366d902635a699c18b90e0a619f74bb6b0e680c2` on 2026-11-03.
- Saved this single plan with repository-relative links. The original dirty
  ANY-715 checkout was left unchanged; no branch-wide changes were transferred.
- The saved plan incorporates its self-validation and the complete agreed
  rules. At this preparation checkpoint implementation was unstarted; the only
  intended branch change was this execution-plan file.
- Plan-only verification: `npm run docs:check` passed; the new-file whitespace
  check reported no errors. Links are repository-relative and engineering text
  is English.
  Runtime/canonical implementation suites are not repeated for this document
  save; their execution remains required above when implementation occurs.

No implementation step is complete merely because this document exists.

### Step 1 implementation evidence

Completed 2026-11-03 on `ANY-812` from baseline `f961dd4`.
Only sections B–C were executed; Step 2 remains unstarted.

- Guard: derive canonical names from the supplied root's AST on every call;
  protect all 14 current declarations and future additions. Preserve the 21
  independent historical prohibitions. No runtime, schema or wire changes.
- Regression-first: **12 failed, 90 passed** before the fix. Failures covered
  omitted/future duplicate and absolute/relative facade imports, per-root
  discovery and authority diagnostics. After the fix: **102 guard tests passed**;
  the four focused modules: **352 passed**. Diff review found no blocking issues.
- Passed: docs, architecture, generated freshness, Ruff, whitespace, production
  web build and `npm run check:fast` (**1641 API**, **38 web boundary** and
  **395 component tests**).
- Canonical runs required execution outside the sandbox and process-only
  `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN=` to avoid sandbox
  `EPERM` and inherited development settings. Tracked configuration was unchanged.
- Initial full `npm run check`: **425 PostgreSQL passed, 1 failed**;
  the isolated repeat passed. Final full verification is recorded below.
- Test PostgreSQL was stopped. Detailed local logs and JUnit files remain under
  `.harness/evidence/ANY-812-step-1/`.

### Sections B–C revalidation evidence

Revalidated on 2026-11-03 at
`a7547854ec787f45c54c64363226df1cc0fc2b34`. Sections B–C were already implemented
in that commit before this execution. This pass is limited to their regression,
guard and verification evidence; section D (the ticket's Step 2) and ANY-800
Step 3 remain unstarted. No new tooling correction was necessary, and no commit
or push was performed.

- Reassessed the existing coverage before making any tracked edit: all 14
  canonical declarations, future declarations without export changes,
  absolute/relative facade imports, permitted canonical/provider cases,
  repeated calls across roots, and absent/invalid/empty/unreadable authority
  sources are covered. The 21 historical prohibitions remain independent.
- Reproduced the regression-first result using an isolated `git archive` of
  pre-fix `f961dd48a0b517b82fd49f12499a68360d263809`, with only the current
  checked-in `test_repository_docs.py` copied into that temporary snapshot:
  **12 failed, 90 passed, 184 deselected**. The live checkout's guard was never
  reverted. The failures were:
  - missing duplicate-definition and absolute/relative facade diagnostics for
    `ExternalCreateOperationState` (three failed `any(...)` assertions);
  - the future declaration's duplicate and two facade imports returned no
    errors instead of one (three failed `len(errors) == 1` assertions);
  - root-specific discovery missed `RootSpecificState` (one failed diagnostic
    assertion);
  - missing, syntactically invalid, empty and nested-only authority sources
    lacked the required path/reason/remediation diagnostic (four assertions);
  - the unreadable authority raised `IsADirectoryError` instead of returning
    an actionable diagnostic (one failure).
  The pre-fix removed-direct-provider and legacy-model architecture regressions
  also remained green: **2 passed, 49 deselected**.
- The same checked-in tests against the existing correction: **102 passed**.
  The complete repository-documentation, model-enum, reconciliation-model and
  architecture modules: **352 passed**.
- Passed: `npm run docs:check`, `npm run architecture:check`,
  `npm run generate:check` and `npm run check:fast` (**1641 API**, **38 web
  boundary**, **395 component tests**, plus Ruff and web lint).
- Full `npm run check` at this checkpoint: **425 PostgreSQL passed, 1 failed**;
  the isolated repeat passed. Final full verification is recorded below.
- Verification uses the canonical root `.venv` on `PATH` and process-only
  `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN=`. Canonical
  checks run outside the sandbox because the earlier execution established
  sandbox `EPERM` failures. No tracked environment/configuration was changed.
- Review against B–C and the correctness checklist found no further ownership,
  compatibility or unnecessary-machinery issue: the guard reads only source
  AST from each supplied root, has no application imports or cached inventory,
  and preserves import resolution and historical restrictions. Runtime,
  schema, persisted values and generated contracts remain unchanged. Browser
  journeys and live provider/observability probes are not acceptance checks
  for this tooling-only scope and were not run.
- Final evidence-only documentation and whitespace checks passed. HEAD remains
  `a7547854ec787f45c54c64363226df1cc0fc2b34`; the only new tracked working-tree
  change is this plan. This checkpoint precedes section D and final verification.
- Local logs, JUnit results and the pre-fix snapshot/command/test-hash metadata
  are under `.harness/evidence/ANY-812-bc-revalidation/`.

### Step 2 implementation evidence

Execution baseline: `7bfdb4d3fd845c72af4796097e57bb010cd52873` on 2026-11-03,
with a clean working tree. The current request explicitly enables section D,
the ticket's Step 2; ANY-800 steps 3–8 remain outside scope.

- Validated the prior B–C delivery before editing: all four focused modules
  passed (**352 tests**, 3.55 seconds). Existing red/green evidence and the
  read-only full review above remain applicable; no guard/runtime source has
  changed since those checks.
- Pre-edit coverage assessment: existing physical-schema/model assertions are
  sufficient characterization for the wording-only test change. Step 2 adds
  policy and review inputs, not runtime behavior, so no artificial runtime
  regression or new checker is introduced. Documentation links, review
  configuration, requirement coverage and assertion preservation need explicit
  verification.
- The original uncommitted rule draft is unavailable in the current neighboring
  worktrees. The original checkout now uses ANY-765; the retained ANY-715
  recovery worktree has unrelated changes. Neither was modified or transferred.
  Implementation follows the complete saved requirements and ANY-812.

- Requirement-to-surface review covers all twelve ANY-812 rules:
  - Rules 1, 6–8: conventions' structure/validation/construction section and
    examples retain concrete required/optional/nested contracts, typed helper
    paths, proportional construction and bounded maps/opaque-request seams.
  - Rules 2–4: conventions' single-vocabulary section covers all Portal-owned
    model states, singleton outcomes, symbolic use paths, defaults and active
    SQL parity; the correctness checklist reviews these same paths.
  - Rules 5, 9–10: source ownership/compatibility covers Integration numeric
    symbols and unknown handling, provider independence, omitted/null and
    history/identity/lease invariants, and the existing generated wire chain.
  - Rules 11–12: proportionality/exception/evidence guidance preserves
    KISS/YAGNI, incremental application, existing debt ownership, bounded
    exceptions, routine autonomy and focused owner escalation without
    speculative mechanisms or a new waiver system.
- Root/API/web AGENTS link the detailed owner instead of duplicating it.
  Architecture and data-model references name the three actual plain-string
  state fields, related representation debt and the completed AST guard,
  without importing ANY-715-only schema or claiming runtime narrowing.
  Type-only frontend generation remains explicit debt.
- Workflow now requires pre-edit coverage assessment, bug regression-first
  evidence and behavior-preserving characterization, links the correctness
  checklist, and records actual check statuses. Testing guidance retains
  shared fixture/resource lifecycle ownership while removing blanket factory
  migration on touched tests. Documentation navigation links the detailed
  rules and checklist.
- AI-review `policy.always` now includes the existing correctness checklist;
  parsed YAML confirms the three required always-inputs exist and the scoped
  API/web inputs remain intact.
- Characterization: the complete reconciliation-model test AST equals its
  baseline after normalizing only the approved test/local-variable renames.
  Every physical-schema assertion, including the plain-text webhook state,
  remains unchanged. All five Python example blocks compile; the positive
  result example preserves symbolic JSON serialization and omitted/null
  distinctions. No new production example types were introduced.
- Self-review against the ticket, boundaries and correctness checklist found
  one wording ambiguity: the API digest could imply textual enums for numeric
  vendor protocols. It was corrected to distinguish Portal-owned enums,
  textual `StrEnum` and Integration-owned numeric symbols. No remaining
  findings were identified; no runtime/schema/wire, paid-access, legal/UI,
  checker rollout or generator migration entered this Step-2 diff.
- Passed: focused modules **352 tests** (3.54 seconds), docs,
  architecture, generated freshness and `npm run check:fast` (**1641 API**,
  **38 web boundary**, **395 component tests**, plus Ruff and web lint).
  The complete check also passed these stages and production web build/
  TypeScript before reaching PostgreSQL.
  Final evidence-only documentation and whitespace checks passed as well.
- Pre-rebase full `npm run check`: **424 PostgreSQL passed, 2 failed**;
  the focused repeat had **1 passed, 1 failed**. The successful final full run
  below supersedes that verification status. Section D's implementation
  criteria are satisfied.
- Tested revision: HEAD `7bfdb4d3fd845c72af4796097e57bb010cd52873` plus the
  Step-2 working-tree changes. The non-plan patch SHA-256 is
  `b488be0cba7ed543e165ae67bf6f05d139711f93ab82b682268198c06efc17a9`;
  `verification-source.json` records per-file hashes. Evidence-only plan
  updates are excluded from that hash. At this verification checkpoint, Step 2
  had not been committed or pushed.
- Separate Step-2 local logs and characterization evidence are under
  `.harness/evidence/ANY-812-step-2/`. Browser/provider journeys and live
  observability probes are not applicable to this documentation/review-input
  change and are not claimed as runtime validation.

### Final verification — 2026-11-03

- Rebased onto main `43943644d277244e8838a693f0d55348d202d7e5`; verified
  implementation head: `b420b32b2022297af17483be8c7c6a6f3daddbd7`.
  All four implementation patches were preserved without conflicts.
- Focused modules: **352 passed**. Full `npm run check`: **passed**, including
  **1641 API fast**, **426 PostgreSQL**, **38 web boundary** and **395 component
  tests**, production web build/TypeScript, documentation, generated freshness,
  architecture, Ruff and web lint.
- Browser E2E was skipped without `RUN_E2E=true` and a running harness stack.
  Live provider journeys are not applicable to this tooling/documentation scope.
- Subsequent changes only update this plan; final documentation and whitespace
  checks passed. The test PostgreSQL server was stopped. Detailed local logs
  remain in ignored `.harness/evidence/ANY-812-rebase/`.

### Final delivery evidence

The original implementation base was
`366d902635a699c18b90e0a619f74bb6b0e680c2`; the current rebase base and verified
implementation SHA are recorded above. Steps 1–2 are implemented, with separate
evidence. [PR #160](https://github.com/gushinets/payments-portal/pull/160)
targets main and includes the ticket, template sections and current verification
results. No further implementation step is planned within ANY-812. Remaining
delivery work is CI disposition and human merge approval. The plan stays active
until those delivery items are resolved. ANY-800 steps 3–8 remain unstarted here.
