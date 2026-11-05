# ANY-715 — Unify LBX interpretation and bound-subscription readback

Status: approved for execution by the owner on 2026-11-05; Stages 1–4 implemented and behaviorally verified. Repository-wide validation caveat is recorded in Section 9.\
Destination: `docs/exec-plans/active/ANY-715-refactoring-plan.md`\
Issues: [ANY-715](https://linear.app/paveldik/issue/ANY-715), [ANY-504](https://linear.app/paveldik/issue/ANY-504)\
PR: [#154](https://github.com/gushinets/payments-portal/pull/154)

Revision summary:

- Added a distinct first-binding contract for UNKNOWN → BOUND, including atomic negative application and concurrent canonical-row creation.
- Included operator binding and review inventory callers, typed findings, preserved authorization and explicit MANUAL_REVIEW routing.
- Added partial-commercial negative integration scenarios and replaced workspace links with links relative to this plan’s destination.

## 1. Objective and verified baseline

Implement the accepted direction from the [root-cause report](../../engineering/ANY-715-root-cause-research-2026-11-05.md), including the subsequent clarification of observation ordering and first binding.

Verified planning baseline:

- Local branch: `ANY-715`.
- Local and PR #154 HEAD: `3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`; unchanged from the research.
- Existing workspace changes: the research report and its link in `docs/README.md`. Preserve them.
- ANY-504 and ANY-715 descriptions remain unchanged since the research.
- Inspected downstream ANY-765 / PR #157 HEAD: `ff4f4cdbe03678b0f598288876dd563f07b4719e`. Its existing observation-time guards are part of the integration baseline.
- Targeted reinspection confirmed the operator `allow_terminal=True` caller and the terminal inventory branch that currently drops readback signals.

The refactor will correct commercial completeness, give independently proven negative readbacks one atomic effect, and route recovery by current operation state. It will remove terminal-as-conflict handling, redundant BOUND binding/recovery work, and duplicated lifecycle interpretation.

Preserve async HTTP, short synchronous SQL transactions, existing workers and queues, finite trust, local deadlines, financial history, consent, product isolation, account-only Widget, and payment for eligible unpaid or blocked subscriptions.

No MVP scope change, webhook deletion, async rewrite, new queue, durable version mechanism, lease system, commercial store, or public HTTP contract is planned. Step 9 implementation remains outside clean PR #154.

## 2. Fixed implementation decisions

### Classification and admission

Introduce a small pure material-inspection result containing:

- Missing or uninterpretable required fields.
- Known commercial differences.

Inspect all applicable fields before deciding the classification. Preserve these conclusions separately in the existing proof `reasons`; do not add database columns.

Apply the following precedence:

1. Missing or uninterpretable mandatory commercial evidence → `commercial=INCOMPLETE`, `complete=False`, even when a difference is known.
2. Fully reconstructed material evidence with a difference → `COMPLETE_MISMATCH`.
3. Fully reconstructed matching material evidence → `COMPLETE_MATCH`.

Ownership conflicts and independently proven lifecycle negatives remain separate conclusions. Unknown lifecycle or blocking codes produce incomplete interpretation, without `financial_binding_conflict`.

Missing/invalid currency mapping, a valid but changed local currency ID that no longer interprets the observed source ID, or an unrecognized currency symbol produce incomplete money interpretation. A numeric ID or arbitrary symbol alone cannot establish another ISO currency. Retain genuinely proven currency conflicts when validated ISO/scale evidence exists; add no currency catalog or new non-RUB product capability.

Preparation and payment retain their purpose-specific proof requirements. They do not require a paid projection or full current-cycle proof. Their strict effective-term adapter checks completeness before converting a fully proved difference into a conflict.

For an already BOUND subscription, collect and apply independently sufficient negative evidence **before** converting incomplete material inspection into an expected strict-admission refusal. An exception from effective-term admission must not discard that negative.

### Readback contracts

Use two explicit pre-HTTP subject variants:

- `BoundReadbackSubject`: original purchase/customer/binding witnesses, canonical subscription ID, subscription fence, supporting observation ID, capture time and fixed deadline.
- `OriginalCreateReadbackSubject`: original customer/purchase witnesses, CREATE operation ID/kind/key/state/fence, saved-command and candidate/receipt witnesses, expected absence of a canonical subscription, capture time and fixed deadline.

The second variant is for first binding. It does not invent a subscription fence or supporting observation before a subscription exists.

Use typed normalized findings:

- `BoundSourceNegative`: actual agreement/subscription basis, source-read window, independently proved restricting fact and reasons.
- `ScopedReadbackFinding`: a sufficient negative or a hint tied to its original subject.
- `ReadbackApplyResult`: `APPLIED_NEGATIVE`, `HINT_ONLY`, or `SUPERSEDED`.

An internal decision requiring another read is not an externally acknowledged effect. Return an external outcome only after its required transaction succeeds.

### Common negative transition

Add one Application transition with:

- Short pre-HTTP subject capture.
- A transaction-owning wrapper for ordinary BOUND callers.
- A caller-transaction helper for original binding and inventory application.

The transition may append evidence, restrict source facts, advance the existing subscription fence and enqueue urgent reconciliation. It cannot renew trust, unblock, make commercial status eligible, resolve review, release holds, select a primary or grant rights.

Hint-only findings preserve only their permitted scoped scheduling effect. They do not change source facts or claim that immediate restriction succeeded.

### Transaction and ordering rules

Use the existing business lock order:

`user → customer/customer operation → original purchase/hold → financial operations → product scope → subscription → queue rows`

Financial operations retain deterministic ordering. Inventory locks affected business tuples in stable product/purchase order and validates its existing batch witnesses before changes. HTTP runs outside transactions.

After HTTP, recheck tenant/region/account/origin, current customer pair and fence, original purchase and hold, accepted/legal evidence, permanent operation keys/bindings and the exact negative scope. Create only the same provenance-only product scope already supported by reconciliation when it is absent; leave its primary unset in Step 8.

For an accepted negative, one commit contains:

- Versioned negative evidence and supporting-observation update.
- Restricting facts, preserving terminal monotonicity and genuine review.
- Incremented `reconciliation_fencing_token` and cleared subscription lease owner/expiry.
- Urgent `subscription_reconciliation` coalescing with `hint=True`.
- Preservation or repair of the existing positive trust deadline without extending it.

Do not finish or clear another queue owner. Invalidating subscription apply authority does not cancel its HTTP task. The old worker retains responsibility for its own finite cleanup/retry; generation prevents its completion from consuming the new hint.

### Exact BOUND race algorithm

Use source-read time, not commit order. New negative evidence stores `observed_at=read_finished_at`. Reconciliation observations already use that meaning.

Under the apply locks:

1. Validate the original fixed deadline, `captured_at ≤ read_started_at ≤ read_finished_at ≤ database_now`, permanent provenance and expected subscription fence.
2. Inspect the current supporting observation. An observation ID change alone is not a stale-result test.
3. Accept the negative when the fence matches and the current authority finished no later than the negative’s `read_started_at`.
4. Reject the original negative as superseded when a current authority demonstrably started after the negative finished.
5. A changed fence or overlapping/unorderable windows requires rechecking. Permit **one** fresh subject capture and reread within the same remaining I/O budget, then repeat the guards.
6. End or roll back the preceding transaction before any reread. Never hold SQL locks during HTTP.
7. If the retry is unavailable, incomplete or again fails currentness, commit only a correctly scoped urgent hint. Return `HINT_ONLY`; do not change facts or the subscription fence.
8. Changed ownership/provenance never becomes permission to hint another subject.

For legacy evidence without a full source window, its observation timestamp is a conservative upper bound. If it cannot establish ordering, use the bounded recheck path.

Add ANY-765’s existing `latest.observed_at > incoming.read_started_at` protection to the corresponding ANY-715 reconciliation apply path. Preserve it during integration.

Required outcomes:

- **Negative commits, then old ACTIVE applies:** the changed subscription fence rejects ACTIVE before any trust update.
- **Truly newer positive commits, then stale negative applies:** the positive’s source window rejects the old negative.
- **Old ACTIVE is read; negative captures witnesses and reads; old ACTIVE commits; negative applies:** ACTIVE’s source finish predates the negative’s start, so the changed observation ID does not reject the negative. Apply it atomically.

Expected terminal refusal follows a successful required commit. `HINT_ONLY` or stale application uses an existing retryable pending/stale error and cannot be presented as committed restriction. Commit failure or lost acknowledgement propagates through the existing infrastructure-error path.

### First binding: original CREATE → canonical BOUND subscription

First binding uses `OriginalCreateReadbackSubject`, not a fabricated BOUND subject.

Before HTTP, capture original CREATE/customer/purchase witnesses and expected canonical-subscription absence. Receipt presence narrows the candidate but grants no binding authority.

Under the normal apply locks, before the binder’s own mutations:

1. Recheck current provenance, original operation witnesses, saved financial command, allowed recovery state and canonical-subscription absence.
2. Require the existing original-CREATE proof: original send history, unique permitted candidate, ownership/seller/relationship proof and complete required original effective terms. For operator binding, also require its existing fresh full original proof and authorization.
3. If the canonical row is still absent, create it and perform binding/history, sufficient negative evidence, restriction/fence and urgent enrollment in **one binding transaction**.
4. Treat the binder’s own operation-fence rotation and preparation observation as outputs of this validated first-binding branch. They are not competing authority and do not trigger reread.
5. Keep this distinction structural: no generic “skip currentness” flag. Only the branch whose pre-mutation absence and CREATE witnesses were validated receives the first-binding context.
6. Return `APPLIED_NEGATIVE` only after the entire binding unit commits successfully.

If another caller has already created the canonical row:

- Do not treat its fence or history as this transaction’s own mutations.
- Do not adopt its current fence after HTTP to legitimize the earlier proof.
- End or roll back the initial binding unit, capture a real BOUND subject, and use the ordinary bounded reread/currentness branch.
- Count this reread against the same one-retry allowance and original budget/deadline.
- With insufficient budget, retain only an admissible scoped hint. Do not repeat binding/history or acknowledge negative application.
- A different canonical binding or stale operator case remains subject to existing conflict/stale rules.

A negative state or receipt alone cannot prove the original CREATE. If original binding proof is incomplete, retain original recovery/history and its existing work; do not create a hypothetical subscription merely to restrict it.

## 3. Sequential ANY-715 implementation stages

### Stage 1 — Make interpretation complete before classifying differences

**Observable result**

Identical LBX facts produce the same material and lifecycle conclusions across reconciliation, preparation, recovery and inventory. Partial commercial differences no longer create false permanent review.

**Files, functions and callers**

- [LBX financial interpretation](../../../apps/api/app/integrations/lbx/financial.py): add `inspect_effective_terms()` and one lifecycle classifier; adapt `prove_effective_terms()`, `prove_subscription()` and `inventory_terminal()`.
- [LBX reconciliation normalization](../../../apps/api/app/integrations/lbx/reconciliation.py): update `normalize_subscription()` to combine effective terms, applicable policy, agreement policy and money interpretability before classifying.
- [Reconciliation contracts](../../../apps/api/app/domains/billing/reconciliation_contracts.py): retain existing proof shape and enums; retain missing/unknown and known-difference reasons separately.

**Remove or consolidate**

- Remove exception-first material classification.
- Replace duplicated numeric lifecycle mappings with the shared classifier.
- Remove `LbxFinancialEnded` and the `allow_terminal` proof switches as all callers migrate in Stage 3.
- Keep actual ownership, seller, composition and accepted-term checks. Do not introduce point-response self-ID checks contrary to ADR 0005.

**Transactions and currentness**

This stage adds pure interpretation only. Existing claim/apply boundaries remain. Unknown or partial evidence cannot acquire send or binding authority.

**Stored-data compatibility**

No migration or historical rewrite. Keep `subscription-reconciliation:v1`; restore its intended completeness semantics. Existing genuine review remains open, including after a matching poll.

**Tests and completion**

Update existing reconciliation unit tests and the persisted matrix:

- Missing required data alone and with known price, period, composition or policy differences.
- Missing/invalid mapping and valid local remapping.
- Complete real material conflicts.
- Independently owned block/end despite incomplete commercial evidence.
- Unknown state/block codes.
- Five priors: unverified, allowed, blocked, expired and genuine review.

Change tests that currently assert defective partial `MISMATCH` behavior. Give real-conflict controls complete, coherent fixtures. An arbitrary `USD` symbol is an incomplete-interpretation control; a currency-conflict unit control must supply validated money meaning.

Done when classification and persisted consequences match the report’s intended matrix, including unchanged trust and no new mismatch review for incomplete evidence alone.

### Stage 2 — Implement atomic negative readback and ordering protection

**Observable result**

A sufficient current negative restricts the original subscription immediately and fences old positive work. Ambiguous or insufficient evidence produces an explicitly identified hint-only result.

**Files, functions and callers**

Add:

- `apps/api/app/domains/billing/readback_contracts.py` for both subject variants, typed findings, negative evidence and outcomes.
- `apps/api/app/domains/billing/readback.py` for capture, transaction wrapper and caller-transaction apply.
- `apps/api/app/domains/billing/reconciliation_facts.py` for source-only fact transitions extracted from current reconciliation, aligned with the existing ANY-765 ownership boundary.

Update:

- [Reconciliation apply](../../../apps/api/app/domains/billing/reconciliation.py): reuse source-fact ownership and add observation-time protection.
- [Work transitions](../../../apps/api/app/domains/billing/work.py): reuse enrollment, claim verification, generation handling and deadline scheduling.
- LBX/composition read boundaries: produce actual source windows and normalized negative bases without discarding findings on later admission failure.

**Remove or consolidate**

Move existing source-fact assignments into one owner. Reuse its negative operation from reconciliation and readback; retain a distinct full-proof positive branch.

Do not convert negative-only evidence into a complete `SubscriptionProof` merely to reuse a positive writer.

**Transactions and currentness**

Implement Section 2’s lock order, BOUND race algorithm and first-binding context. The ordinary wrapper owns its complete synchronous unit; binding and inventory use the helper inside their existing atomic unit.

An internal recheck decision writes no facts and acknowledges no restriction. Close the transaction before reread. Reuse the caller’s nonrenewable budget and existing apply safety margin; no reread refreshes financial deadlines.

**Stored-data compatibility**

Add `bound-source-negative:v1` in existing observation storage, with:

- Original local subject and accepted/provenance references.
- Agreement or subscription basis and restricting fact.
- Actual read start/finish, successful read names and reasons.
- Previous support and relevant fence witnesses.
- `completeness_classification=negative_only`.

Retain incomplete commercial classification and its reasons where present. Never assert complete positive commercial/calendar proof.

Keep `prepared-subscription:v1` and `financial-terminal:v1` as preparation/binding history. No physical migration, new work kind or new durable ownership field.

Keep `last_authoritative_read_at` and `projection_valid_until` unchanged. Preserve `ENDED`, existing ineligibility and review. Proven terminal revival remains a real conflict handled by its existing review owner.

**Tests and completion**

Add permanent PostgreSQL readback tests covering:

- All three required race orders through actual claim/read/apply functions.
- Overlapping windows, one reread, exhausted budget and explicit hint-only outcome.
- Changed binding, consent/hold, customer fence, subscription fence and expired work claim.
- Own versus foreign queue ownership; newer generation survives old completion.
- Failure before commit rolls back evidence, facts, fence and work.
- Failure reported after a real commit does not acknowledge success; later inspection/retry observes durable state without replaying CREATE.
- First-binding context excludes only the validated unit’s own mutations, never another caller’s authority.

Use controlled timestamps/barriers rather than sleeps. Done when every outcome proves its persisted effect and acknowledgement semantics.

### Stage 3 — Migrate ordinary and operator callers; route recovery by state

**Observable result**

Advance, payment presentation, post-CREATE readback, ordinary inventory and operator paths use the new contracts. Original CREATE recovery remains safe, including first terminal binding. BOUND read failures no longer reopen completed CREATE work.

**Files, functions and callers**

Ordinary paths:

- [Purchase composition](../../../apps/api/app/composition/purchases.py): `_find_financial()`, `_prepare()`, `_inventory()`, `advance_purchase()`, `verify_payment_purchase()`.
- [Shared recovery](../../../apps/api/app/composition/purchase_recovery.py): `_recover_one()`, `recover_financial()`.
- [Financial writer](../../../apps/api/app/domains/purchases/financial.py): `financial_pending()`, `_bind_financial()`, `bind_financial()`.
- [Background composition](../../../apps/api/app/composition/billing_background.py) and [recovery Application](../../../apps/api/app/domains/billing/background_recovery.py): locked routing, inventory application and compatibility drain.
- [Widget admission](../../../apps/api/app/domains/purchases/widget_admission.py): preserve final admission checks.

Operator paths:

- [Operator composition](../../../apps/api/app/composition/billing_operator.py): migrate `_find_financial(..., allow_terminal=True)` and the old preparation-observation construction to the new result and first-binding contracts.
- [Operator review inventory](../../../apps/api/app/composition/billing_review_inventory.py): replace the signal-dropping terminal `continue` with classification and scoped finding collection before competition exclusion.
- [Operator contracts](../../../apps/api/app/domains/billing/operator_contracts.py): extend `ReviewInventoryProof` with typed scoped findings and their pre-HTTP subjects.
- [Operator inventory](../../../apps/api/app/domains/billing/operator_inventory.py) and [operator review](../../../apps/api/app/domains/billing/operator_review.py): verify findings and apply them through the existing authorized writer, preserving atomic audit.

**Remove or consolidate**

Replace the context-sensitive recovery boolean with a small typed result distinguishing original outcome resolution, terminal state, permission to continue child GET recovery and readback apply outcome. `_prepare()` owns user/send/payment admission after the required effect.

Change `_find_financial()` to return inspected facts/findings rather than throwing away an independently sufficient negative when strict material admission is incomplete. Both ordinary and operator callers consume this result; no `allow_terminal` caller remains.

Remove:

- The terminal exception catch that refuses Widget before committing the effect.
- Rebinding and preparation-observation writes for ordinary already-BOUND reads.
- Unconditional BOUND recovery reopening in `financial_pending()`.
- Terminal-only negative scheduling in place of common negative/hint handling.
- Operator inventory’s unconditional loss of terminal readback signals.

Keep initial subscription enrollment and healthy-read scheduling.

**Transactions, routing and currentness**

Select the route under business locks and recheck it after HTTP:

- **BOUND with canonical subscription:** common readback/reconciliation path.
- **POSSIBLE_SEND or actual UNKNOWN:** GET-only proof of the original CREATE; use the first-binding subject while canonical subscription is absent.
- **PENDING / PROVEN_NOT_SENT:** existing explicit user-continuation rules; no background send or coincidental adoption.
- **MANUAL_REVIEW, deadline-only `external_create_outcome_unknown:*`:** may converge through the existing original GET-proof recovery rule. Preserve its existing evidence and case checks.
- **MANUAL_REVIEW, genuine identity/commercial/inventory conflict:** requires the existing authorized, audited resolution. An ordinary matching read or negative finding does not resolve it.
- **BOUND agreement without subscription:** inspect the child. Preserve/enroll original uncertain-child recovery; leave unsent children for explicit continuation. Create no subscription job without a canonical subscription.
- **BOUND child without its atomically required local subscription:** fail closed as unproven provenance; do not synthesize a row or financial conflict.

A closed agreement prohibits a new child CREATE but does not stop GET recovery of an already possibly sent child, including terminal candidates with or without receipt.

For first subscription binding:

- Capture original CREATE/customer/purchase witnesses and expected absence before HTTP.
- Validate them and the stronger original-CREATE proof before rotating operation fences or writing preparation history.
- If still absent, commit canonical row, binding/history, sufficient negative evidence, restriction/fence and urgent work together.
- Do not rerun BOUND currentness against the binder’s own preparation observation.
- If another caller created the row, close the unit and take the ordinary BOUND capture/reread path; retain the original deadline and retry allowance.
- Do not return `APPLIED_NEGATIVE` before the entire binding commit succeeds.

Only a verified owner may finish a running recovery claim. A request that binds an operation does not clear a foreign running queue lease; that owner later drains/retries against current BOUND state.

Existing BOUND recovery rows retain a locked, no-HTTP compatibility drain. Ensure canonical reconciliation enrollment exists when applicable; never fabricate a subscription reference.

**Inventory and operator application**

Ordinary inventory returns typed findings containing competition/incompleteness and scoped readback signals. Preserve useful findings before expected refusal. Apply a negative only when the existing read set proves its exact original subject and ownership; otherwise enqueue a scoped hint. Do not add full reconciliation reads for every candidate or infer ownership from tariff equality.

Operator inventory uses the same classification and scoped-effect rules:

- Capture canonical neighbors’ readback subjects in a short locked snapshot before source reads.
- Carry findings in `ReviewInventoryProof`; retain existing purchase, review and membership witnesses.
- Keep capture timestamps/deadlines outside stable snapshot-equality comparisons.
- A terminal candidate without a proven local original owner remains excluded according to existing competition rules; it is not adopted or assigned a fabricated subscription job.
- For a canonical neighbor, sufficient proof may restrict that neighbor and enqueue its work; insufficient but scoped evidence may only hint.
- Apply the target’s effect through its authorized target binding/reconciliation writer. Do not apply a duplicate target inventory signal against that writer’s own mutations.
- Use the final authorized original proof/read set for target negative application; do not let an earlier terminal read override a later superseding proof.

Verify operator authorization, fresh full original proof, expected fences, case digests, required inventory completeness and currentness **before** the unit’s own mutations. Neighbor effects and target resolution/audit commit in the existing authorized unit. Audit records the scoped outcomes without resolving neighbor reviews.

A hint-only finding cannot satisfy a mandatory operator proof or bypass stale authorization. Failed mandatory case/inventory checks retain the existing refusal and rollback behavior.

**Stored-data compatibility**

No migration. Preserve command documents, send fences/history, keys, receipts, deadlines, accepted terms, consent and holds.

Keep operator authorization and audit ownership. Only the cases already authorized by the existing resolution rules may be resolved. No automatic removal of genuine or neighboring review is introduced.

**Tests and completion**

Extend permanent Widget, recovery, inventory, operator and worker suites:

- Advance and purchase Widget × waiting, financial/admin block, ended and closed agreement.
- Blocked/unpaid payment remains available with fresh required proof.
- Account-only Widget stays independent of product/subscription proof.
- Actual UNKNOWN established through production transitions, receipt/no receipt, open/closed agreement.
- **First binding:** actual UNKNOWN with and without receipt → proven terminal original child → one commit saves canonical row, binding/history, negative evidence, restriction/fence and urgent work.
- Assert no reread caused by the unit’s own fence rotation or preparation observation.
- Concurrent canonical-row creation switches to ordinary BOUND capture/reread; no stale-proof bypass, duplicate canonical row or repeated binding history. Exhausted budget returns hint-only.
- Incomplete original-CREATE proof or receipt plus negative alone cannot create a canonical row.
- First-binding rollback and lost commit acknowledgement cover the whole binding unit while preserving previously committed CREATE/receipt history.
- Closed agreement with uncertain terminal child and with PENDING/PROVEN_NOT_SENT child.
- Deadline-only MANUAL_REVIEW recovery remains possible; genuine conflicts remain blocked without audited resolution.
- Unknown lifecycle retries without false review.
- No recovery POST and no repeated financial CREATE.
- Same-tariff products retain separate ownership, accepted terms and effects.
- BOUND failures create reconciliation work, not renewed CREATE recovery.
- Old BOUND jobs drain safely; foreign claims remain owned by their worker.
- Terminal original through `bind-original` retains fresh full proof, expected fences, case authorization and atomic binding/negative/audit.
- Terminal or blocked canonical neighbor in operator inventory receives only its correct scoped effect. It is neither adopted nor rebound; its review remains unresolved.
- Stale operator case/fence, incomplete full original proof and failed audit roll back the authorized unit.

Add a dedicated integration parameterization for **BOUND Widget and advance observing independent block/end with missing total or another mandatory material field**. Assert:

- The negative effect commits before any expected strict term/payment refusal.
- Commercial interpretation remains `INCOMPLETE`.
- Trust does not extend.
- No false commercial review is created.
- Original binding, consent, keys and holds remain intact.
- Complete supported blocked/unpaid payment controls still succeed.

Assert the actual next work kind, lane, due time and subsequent apply. Done when all applicable entrypoints retain their user result and every sufficient negative reaches the common transition before expected refusal.

### Stage 4 — Close history compatibility and validate clean Step 8

**Observable result**

New evidence works with Step 8 diagnostics, deadlines and operator checks. The PR contains permanent regressions and an accurate validation record.

**Files, functions and callers**

- [Work queries](../../../apps/api/app/infrastructure/queries/billing_work.py): `missing_deadlines()`.
- Work outcome/expiry functions and operator diagnostics/review/case grouping.
- Existing reconciliation, Widget, recovery, operator and worker test modules.
- [Billing operations guide](../../engineering/billing-background-operations.md) and this active implementation plan.

**Remove or consolidate**

Replace reconciliation-v1-only assumptions where a negative supporting observation is valid. Preserve deliberately full-proof-only operator admission.

Recognize `negative_only` as a negative outcome, never as positive verification or an automatic commercial mismatch.

**Transactions and currentness**

Deadline repair retains the original finite deadline and provenance even when support now points to negative evidence. A first negative with no positive trust does not acquire a trust interval.

Operator restore/bind retains expected observation/fence checks and fresh complete proof. Negative-only evidence cannot satisfy restorative or initial original-binding proof.

**Stored-data compatibility**

Read old schemas without rewriting history. No bulk closure of `subscription_commercial_mismatch` or `financial_binding_conflict`: historical false and genuine cases may share reason codes. Document fresh complete proof plus the existing audited resolution path.

Existing operator audit/history remains readable; new scoped findings add evidence without changing resolution authority.

No migration and no generated API change are expected.

**Tests and completion**

Promote useful research scenarios into permanent tests. Research PASS results characterize the old implementation; they are not fixed-code acceptance evidence. Reverse defective expectations and retain useful helpers in test factories rather than depending on `/tmp`.

Verify old evidence, malformed new evidence, deadline repair/expiry, genuine review persistence, audited restoration/binding and unchanged Step 9 tables in clean ANY-715.

Done when all Step 8 acceptance checks pass at the resulting HEAD, documentation describes the final behavior, and the diff contains no unrelated runtime cleanup.

## 4. Separate dependent integration with ANY-765

This stage runs on the combined branch after the Step 8 refactor is available. Its paid-state code does **not** enter clean PR #154.

**Observable result**

A committed negative source transition and the corresponding persisted paid-state reduction become visible atomically. A granted product cannot remain `CONFIRMED` merely because only `ExternalSubscription` changed.

**Files, functions and callers**

Integrate with ANY-765’s existing:

- `reconciliation_facts.py::apply_source_facts` and source-conflict ownership.
- `paid_access.py::apply_paid_source`, `commit_paid_state`.
- `paid_read.py::_negative`, `read_paid_access`.
- `paid_inventory.py::apply_discoveries`.
- `paid_deadlines.py`, reconciliation contracts and operator proof/audit consumers.

These paths are under `apps/api/app/domains/billing/` on the inspected ANY-765 branch.

**Remove or consolidate**

Merge the source-fact extraction into the existing ANY-765 owner; retain one reducer.

Extend the existing paid writer to accept typed negative-only input through an explicit DENY-only branch. Reuse its current primary/scope rules and whole-user semantic commit. Do not create a second paid projection or manufacture complete positive proof.

**Transactions and currentness**

Within the common caller transaction, after currentness checks and source evidence application:

1. Apply the negative to the affected current primary through the existing paid owner.
2. Run `commit_paid_state` for revision/audit/outbox.
3. Commit together with source facts, supporting evidence, fence and scheduling.

The same atomicity applies when the common helper runs inside first binding or an authorized operator unit.

Preserve both existing ANY-765 observation-time guards in reconciliation and inventory. No later worker tick or cabinet read may be required to revoke an already saved grant.

A negative concerning another product or non-primary subscription cannot revoke an unrelated valid grant.

**Stored-data compatibility**

Add an explicit `bound-source-negative:v1` decoder to paid reading. Validate subject, restricting fact and source window; retain the existing bounded negative-evidence freshness policy without modifying positive trust.

`paid_read` keeps its stored-grant semantics; correctness comes from atomic grant reduction. An unknown schema with no grant remains `UNAVAILABLE`, not confirmed absence.

Preserve existing evidence versions, optional `cycle` / `access_end_at`, allowance history, deadlines and operator full-proof requirements. No additional physical migration is planned.

**Tests and completion**

Run combined-branch PostgreSQL tests starting with a real persisted grant:

- Negative commit removes the affected grant; paid read reports confirmed absence through the explicit decoder.
- Revision, audit and outbox change atomically according to existing semantic-change rules.
- Duplicate negative does not create redundant semantic revisions/outbox entries.
- Rollback and lost commit acknowledgement cover both source and paid state.
- All three races preserve correct source and paid state.
- Incomplete commercial difference alone preserves finite existing state without trust renewal.
- Independently proved negative plus incomplete commercial evidence still denies atomically.
- Negative-only input cannot materialize allowance, select primary, renew trust or enter GRANT.
- First terminal binding does not create positive paid state.
- Operator-neighbor effects respect primary/product isolation and leave unrelated review unresolved.
- Genuine review and terminal revival retain their restrictions.
- Old schemas, cycle/access-end evidence and local deadlines remain readable.

Done only after tests pass on the resulting integrated HEAD. The research’s four pure policy assertions do not satisfy this gate.

## 5. Verification, handoff and limits

Use the repository-root `.venv`, disposable worktree PostgreSQL and simulated LBX. Do not mutate shared/production billing data.

During implementation:

- Format changed Python files with Ruff.
- Run focused unit and PostgreSQL selections for each stage.
- Run `.venv/bin/python scripts/repo.py lint api` for Ruff lint and formatting checks.
- Run `npm run architecture:check`, `npm run docs:check` and `npm run generate:check`.
- Start/stop the test database with `.venv/bin/python scripts/repo.py test-db up` / `test-db stop`.
- Run `npm run test:api:fast`, `npm run test:api:postgres`, then canonical `npm run check:fast` and `npm run check`, using the repository `.venv` on `PATH`.

Use existing reconciliation, Widget, background recovery and operator suites, including `test_billing_recovery_cli_review_postgres.py`, `test_billing_review_regressions_postgres.py` and `test_billing_lifecycle_review_corrections_postgres.py`, for affected permanent scenarios.

Record commands, resulting HEAD, failures and environment-limited skipped checks. Do not substitute historical CI or research results for current verification. No hypothetical 10,000-subscription load experiment is required.

Before handoff, inspect the cumulative diff for:

- Remaining `allow_terminal` callers or duplicated lifecycle classifiers.
- Broad exception conversion that discards independently sufficient negatives.
- First-binding code validating against its own mutations or adopting post-HTTP witnesses.
- Unauthorized queue completion or review resolution.
- Positive writes from negative-only evidence.
- Operator terminal findings lost before apply.
- Unrelated changes and generated-file drift.

Preserve actual browser/payment regression coverage through canonical checks. Live provider conformance and production enablement remain under ANY-504’s existing gates.

All repository links in this plan are relative to `docs/exec-plans/active/ANY-715-refactoring-plan.md`.

No unresolved product decision blocks this plan. LBX supplies no atomic multi-resource revision; the selected solution conservatively orders observable read windows and explicitly falls back to hint-only when ordering cannot be established within budget.

Execution is limited to the stage explicitly requested by the owner. Stage 4
is complete. The separate ANY-765 integration has not started.

## 6. Stage 1 execution record — 2026-11-05

- Branch retained: `ANY-715`; HEAD retained:
  `3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`.
- Initial worktree status contained only this untracked approved plan. The
  root-cause report named above and its claimed `docs/README.md` entry were
  absent at the start. The report link is preserved; no research content has
  been invented or rewritten.
- Added pure effective-term inspection with independent incomplete-field and
  known-difference results. Reconciliation combines effective terms, applicable
  tariff policy, agreement policy and money interpretability before choosing
  its existing commercial classification. Missing evidence takes precedence;
  the existing reasons preserve both incomplete and differing conclusions.
- Consolidated numeric lifecycle interpretation for reconciliation, preparation
  and inventory. Unknown codes are incomplete source interpretation rather than
  financial-binding conflicts. A closed agreement can still prove an end
  independently, without completing unknown subscription lifecycle evidence.
- Kept the strict purpose-specific effective-term adapter, ownership checks,
  `LbxFinancialEnded` and `allow_terminal` compatibility for Stage 3 callers.
  No transaction, public contract, evidence schema, migration or paid-access
  writer changed.
- Reversed defective partial-mismatch expectations and made complete conflict
  controls coherent. Added a persisted matrix over unverified, allowed,
  blocked, expired and genuine-review priors, plus preparation/Widget checks
  for incomplete material and unknown lifecycle evidence.

Validation against the working-tree implementation at the retained HEAD:

- Formatting: `.venv/bin/ruff format` on changed Python files — PASS.
- `.venv/bin/python scripts/repo.py lint api` — PASS (Ruff lint and formatting).
- `.venv/bin/python -m pytest -q -p no:cacheprovider
  apps/api/tests/test_billing_subscription_reconciliation.py
  apps/api/tests/test_any709_step3_purchase.py` — **141 passed**.
- PostgreSQL selection:
  `apps/api/tests/test_billing_subscription_reconciliation_postgres.py` and
  `apps/api/tests/test_billing_lifecycle_review_corrections_postgres.py` —
  **158 passed**, including the 120-case persisted matrix.
- Final PostgreSQL compatibility selection — **64 passed**:
  - Lifecycle corrections: `test_incomplete_financial_read_does_not_create_permanent_review`,
    `test_partial_policy_preserves_difference_without_classifying_mismatch`, and
    `test_financial_point_conflict_immediately_withdraws_trusted_subscription`.
  - Complete `test_billing_review_regressions_postgres.py` and
    `test_billing_recovery_cli_review_postgres.py` modules.
  - ANY-709 Step 3: `test_any709_step3_complete_preparation_and_historical_manage`,
    `test_any709_step3_linked_widget_retries_after_failed_point_proof`, and
    `test_any709_step3_material_mismatch_blocks_payment_but_keeps_account_view`.
- Both PostgreSQL runs used `.venv/bin/python -m pytest -q -p no:cacheprovider`
  with `scripts.repo.api_test_environment("api-postgres", canonical_check_environment())`
  to derive the disposable database from this worktree. The worktree server was
  managed with `.venv/bin/python scripts/repo.py test-db up` / `test-db stop`;
  pytest retained ownership of physical test-database creation and removal.
- `PATH="$PWD/.venv/bin:$PATH" npm run architecture:check` — PASS.
- `PATH="$PWD/.venv/bin:$PATH" npm run generate:check` — PASS; no generated drift.
- `PATH="$PWD/.venv/bin:$PATH" npm run docs:check` — FAIL solely on the preserved
  link to the absent `docs/engineering/ANY-715-root-cause-research-2026-11-05.md`.
  Restoring the original report remains a documentation prerequisite; it was
  already missing before implementation.
- During the first iteration, 12 old unit expectations asserted the defective
  partial-mismatch/currency behavior. Those expectations were corrected and
  superseded by the passing final unit run. The initial sandboxed run hung in
  framework HTTP testing and was interrupted; the bounded rerun with local I/O
  permissions passed. Docker and PostgreSQL also required local sandbox access.
- `git diff --check` — PASS. Cumulative review found only Stage 1 interpretation,
  tests and this plan; no unrelated runtime or generated changes. Compatibility
  callers deliberately retain their terminal switches until Stage 3.
- Full API partitions, `npm run check:fast`, `npm run check` and browser E2E were
  deferred to Stage 4 as explicitly requested for this execution.

Stage 1 behavioral acceptance is satisfied: incomplete material alone creates
no mismatch review and never extends trust; independently owned negatives still
restrict through existing reconciliation; genuine review remains open. No code
blocker for Stage 2 was found. No commit, push, merge or ANY-765 integration was
performed.

## 7. Stage 2 execution record — 2026-11-05

- Continued on `ANY-715` at HEAD
  `3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`, preserving all Stage 1 changes.
- Added explicit BOUND and original-CREATE subjects, normalized scoped negative
  findings and committed apply outcomes. The original-CREATE subject carries no
  invented subscription fence or supporting observation.
- Added resource-owning capture/apply units and caller-transaction application.
  BOUND currentness uses source windows, the existing subscription fence and a
  fixed original deadline. Observation-ID changes alone do not reject a negative.
  Composition permits one reread in the same remaining budget after closing the
  preceding transaction; exhausted or ambiguous evidence produces scoped hints.
- Accepted negatives append `bound-source-negative:v1` evidence, restrict source
  facts, rotate the existing fence, invalidate the subscription apply lease and
  coalesce urgent reconciliation atomically. Existing positive trust and its
  deadline remain unchanged. Queue owners are not finished by this transition.
- Extracted source-fact reduction into `reconciliation_facts.py`, keeping a
  separate complete-proof trust/eligibility branch. Added the observation-time
  guard to reconciliation apply. No paid-state writer or ANY-765 code was added.
- Added a transaction-bound first-binding context validated before canonical-row
  creation. Binding/history and negative application share that transaction;
  the context accepts only its own preparation/fence outputs. A concurrent
  canonical row requires a real BOUND capture/reread rather than post-HTTP fence
  adoption. Original effective-term and unique-candidate proof remain mandatory.
- Extracted the financial binding/history writer into
  `apps/api/app/domains/purchases/financial_binding.py`, preserving the existing
  `financial.bind_financial()` API and adding caller-transaction use. First-binding
  support lives in `readback_binding.py`. This keeps each module within the
  repository's 500-line architecture limit without an exception.
- Kept `LbxFinancialEnded`, `allow_terminal`, current recovery routing and ordinary
  and operator entrypoints compatible for their explicit Stage 3 migration.
  No new queue, durable ownership field, migration or public API was introduced.

Validation against the working-tree implementation at the retained HEAD:

- `.venv/bin/ruff format` on changed Python files — PASS.
- `.venv/bin/python scripts/repo.py lint api` — PASS (Ruff and formatting).
- `.venv/bin/python -m pytest -q -p no:cacheprovider` over
  `test_billing_readback.py`, `test_billing_subscription_reconciliation.py` and
  `test_any709_step3_purchase.py` — **153 passed**. Framework HTTP testing used
  local I/O permissions and a 90-second command limit.
- Final PostgreSQL selection, using `.venv/bin/python -m pytest -xq --tb=short
  -p no:cacheprovider -k 'not persisted_matrix'` — **75 passed, 120 deselected**:
  - Complete `test_billing_readback_postgres.py` (48 scenarios).
  - Existing `test_billing_subscription_reconciliation_postgres.py`, excluding
    the unchanged Stage 1 persisted matrix.
  - Complete `test_billing_recovery_cli_review_postgres.py`.
  - Worker tests `test_billing_worker_embedded_lifespan_smoke_and_reserved_local_progress`
    and `test_billing_worker_link_and_sweep_interleave_without_partial_enrollment`.
- The earlier broader PostgreSQL selection also exercised complete worker and
  lifecycle-correction modules: 136 passed and one readiness smoke test failed.
  Its worker used the disposable factory while HTTP readiness used the global
  environment DB session. The fixture now points both at the actual disposable
  PostgreSQL factory; it still executes the real readiness SQL check. The final
  selection passed that test. The enrollment interleave test now patches the
  extracted binding writer's enrollment seam.
- A subsequent run was interrupted after 35 passes and one fixture-setup
  `PreflightDeadlineExceeded` during ordinary purchase preparation. The final
  run passed the affected case and the whole selected set with unchanged runtime
  timeout policy. Initial fixture attempts to mutate immutable evidence were
  replaced with stale witness inputs or newly appended observations; no trigger
  or append-only protection was disabled.
- PostgreSQL environment was derived with
  `scripts.repo.api_test_environment("api-postgres", canonical_check_environment())`.
  Only this worktree's disposable server was used, via
  `.venv/bin/python scripts/repo.py test-db up` / `test-db stop`;
  pytest owned physical test-database creation and removal.
- `PATH="$PWD/.venv/bin:$PATH" npm run architecture:check` — PASS after splitting
  the binding modules; no architecture exception was added.
- `PATH="$PWD/.venv/bin:$PATH" npm run generate:check` — PASS; no generated drift.
- `PATH="$PWD/.venv/bin:$PATH" npm run docs:check` — FAIL only on the same absent
  root-cause report linked by this plan. The original link remains preserved.
- `git diff --check` — PASS. Review covered source-only writes, all three source
  window race orders, bounded reread/hint outcomes, currentness/provenance,
  first-binding context ownership, queue generation/lease preservation,
  rollback and lost commit acknowledgement. No unrelated runtime cleanup,
  paid-state changes, migration, branch switch, commit, push or merge occurred.
- Full API partitions, canonical `check:fast` / `check` and browser E2E remain
  deferred to Stage 4 under the execution request.

Stage 2 behavioral acceptance is satisfied. A sufficient current negative
commits its evidence, restriction, fence and urgent work atomically; stale or
ambiguous results cannot acknowledge that restriction. Trust never extends
from negative-only evidence. First binding includes original binding/history
and the negative in one caller transaction, while foreign canonical creation
uses the ordinary bounded BOUND reread. No code blocker for Stage 3 was found.
Entrypoint migration and the separate ANY-765 integration have not started.


## 8. Stage 3 execution record — 2026-11-05

- Continued on `ANY-715` at unchanged HEAD
  `3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`, preserving Stages 1–2 and the
  original research-report link.
- Migrated advance, payment presentation, post-CREATE recovery and explicit
  GET-only recovery to typed inspected facts and `FinancialRecoveryResult`.
  Strict admission runs after a required BOUND negative commit. Ordinary BOUND
  reads no longer bind again or append preparation history. Matching blocked
  and unpaid payment controls remain available; terminal payment remains refused.
- First binding captures original CREATE witnesses before HTTP and uses the
  transaction-bound context for canonical creation, binding/history, negative
  facts, fence and enrollment. Foreign canonical creation uses the bounded real
  BOUND reread; exhausted budget yields only a scoped hint and retryable refusal.
  Lost commit acknowledgement is never acknowledged as successful restriction.
- Locked routing preserves actual UNKNOWN and deadline-only review recovery,
  genuine review authorization, receipt narrowing and explicit no-send
  continuation. Closed agreements permit uncertain-child GET recovery but no new
  child CREATE. BOUND children without canonical provenance fail closed.
- Removed `LbxFinancialEnded`, every `allow_terminal` caller and the contextual
  payment/recovery boolean. Removed unconditional BOUND CREATE-work reopening.
  Old BOUND recovery work drains without HTTP and enrolls only real canonical
  subscriptions; foreign running claims retain their owner.
- Added typed inventory findings and canonical neighbor capture before HTTP.
  Ordinary inventory retains useful negatives before expected refusal. Operator
  inventory excludes the target effect, preserves membership/review witnesses
  and applies neighbor restrictions or hints with the target audit in one unit.
  Neighbor reviews remain open. Capture times are outside stable snapshot equality.
- Operator first binding validates existing authorization and fresh full original
  proof before its own mutations. The final full read supplies both the target
  effect and the actual point used for preparation history. Negative-only
  evidence stays commercially INCOMPLETE; full matching proof remains separate
  in the authorization audit. Stale fences retain `billing_review_stale`, and
  provider-ID uniqueness conflicts retain `purchase_review_required` after the
  complete failed binding/audit transaction has rolled back.
- Preserved the worker's DB delegate/limiter. A recovery worker switching to
  BOUND after concurrent binding must still prove its original recovery claim
  during apply; an expired or replaced owner cannot report successful progress.
- Split focused financial-read, inventory and binding orchestration modules to
  remain below the existing 500-line runtime limit. No migration, public API,
  generated contract, queue kind, paid-state writer or infrastructure was added.

Validation against the working-tree implementation at the retained HEAD:

- Ruff formatting and `.venv/bin/python scripts/repo.py lint api` — PASS
  (310 files checked/formatted).
- Final focused unit selection over `test_billing_readback.py`,
  `test_billing_subscription_reconciliation.py`, `test_any709_step3_purchase.py`
  and `test_billing_background_recovery.py` — **155 passed**.
- Initial caller/lifecycle/operator PostgreSQL selection — **128 passed**.
- Extended request/recovery runs exercised all ANY-709 Step 3, subscription
  inventory, concurrent inventory and background-recovery scenarios. Old
  expectations were updated for immediate waiting/terminal restriction,
  provenance-only scopes and completed BOUND CREATE work. Concurrency/fault
  injection seams now follow the extracted transaction owner.
- The extended ordering/caller/operator/worker selection finished with
  **204 passed and 2 failed**. Both failures were compatibility refusals
  (occupied provider ID and changed operator fence); both were corrected.
- Final affected PostgreSQL selection — **91 passed**: all operator bind-refusal
  controls, changed-fence refusal, atomic audit rollback, the complete 51-case
  `test_billing_readback_callers_postgres.py` matrix and complete background
  recovery fault tests. The matrix includes actual urgent claim and subsequent
  reconciliation apply, first-binding concurrency, receipt/no-receipt UNKNOWN,
  rollback/lost acknowledgement, terminal/blocked neighbors and account Widget.
- The extended selection also passed the complete Stage 2 readback race suite,
  related inventory case groups, recovery CLI review, operator inventory
  resolution and worker readiness/enrollment interleavings. Genuine-review
  fixture construction now uses the restricting writer for retained historical
  case combinations; ordinary GET routing remains blocked by genuine review.
- One intermediate fixture setup hit a PostgreSQL statement timeout while
  inserting original legal acceptance. The affected inventory/admission
  selection passed on rerun with unchanged SQL and runtime timeout policies.
  The first sandboxed unit invocation stalled in framework threadpool testing;
  it was stopped, and the bounded local-environment unit run passed.
- PostgreSQL runs used `.venv/bin/python -m pytest`, `-p no:cacheprovider` and
  `scripts.repo.api_test_environment("api-postgres", canonical_check_environment())`.
  Only this worktree's disposable server was used; pytest owned test-database
  creation/removal. Server lifecycle used `test-db up` / `test-db stop`.
- `PATH="$PWD/.venv/bin:$PATH" npm run architecture:check` — PASS.
- `PATH="$PWD/.venv/bin:$PATH" npm run generate:check` — PASS; no generated drift.
- `PATH="$PWD/.venv/bin:$PATH" npm run docs:check` — FAIL only on the unchanged
  missing root-cause report linked by this plan. The report was absent before
  implementation; its original link remains preserved.
- `git diff --check` — PASS. Cumulative review covered source-only effects,
  before-admission commits, original proof/absence witnesses, stale claims,
  scoped inventory/audit atomicity and compatibility callers. No unrelated
  runtime cleanup or unfinished Stage 3 branch remains.
- Full API partitions, canonical `check:fast` / `check`, browser E2E, history
  compatibility work and ANY-765 integration remain outside this execution.

Stage 3 behavioral acceptance is satisfied. No code blocker for Stage 4 was
found; restoring the original research report remains a prerequisite for the
final documentation check. Stage 4 has not started. No branch switch, commit,
push or merge was performed.

## 9. Stage 4 execution record — 2026-11-05

- Retained branch `ANY-715`, HEAD
  `3c69c8de7cbb65c81a0a92b0cf99ff269723fff1` and all uncommitted Stage 1–3
  work. Validation below concerns the resulting working tree, not a new commit.
- Deadline enrollment repair now accepts scoped `bound-source-negative:v1`
  support as well as reconciliation evidence. The existing positive-interval
  guard, original finite deadline and current supporting-observation provenance
  remain unchanged. A never-positive subscription acquires no expiry interval.
- Work telemetry classifies `negative_only` as `negative`, separately from
  verified, incomplete and conflict. It cannot update the last verified proof
  timestamp or manufacture commercial-mismatch review.
- Kept full-proof-only operator admission and case grouping. Negative support
  is a valid current observation expectation, but restoration still requires
  fresh complete matching proof, current fences, explicit authorization and the
  existing atomic audit. Historical reason codes are not bulk-resolved.
- Added permanent regressions for legacy preparation/terminal history, malformed
  new read windows, missing-deadline repair/expiry, zero positive trust and
  audited restoration from negative support. Test history is appended through
  a factory without weakening database immutability guards. Existing Step 9
  tables and access-primary assertions remain unchanged.
- Updated compatibility controls: terminal inventory fixtures supply a known
  blocking code; BOUND read diagnostics belong to the canonical subscription;
  incomplete first worker reads preserve negative-only, never-positive support.
  Isolation checks permit exactly the scoped urgent hint while comparing source
  facts, evidence, scope, leases and all other work fields strictly. Reconciliation
  controls now expect retained MANUAL_REVIEW and immediate waiting restriction,
  with no trust extension.
  All permanent tests use repository helpers rather than research `/tmp` files.
- Updated the billing operations guide with classification precedence, atomic
  negatives, read-window ordering, first binding, local deadlines and audited
  historical-review recovery. The owner restored the original research report
  during this stage; it is preserved unchanged, with its documentation-index
  and approved-plan links retained.

Focused and fast validation:

- `.venv/bin/python -m ruff format` on changed Python files and
  `.venv/bin/python scripts/repo.py lint api` — PASS, 311 files checked.
- `npm run architecture:check`, `npm run docs:check` and
  `npm run generate:check`, with the repository `.venv` on `PATH` — PASS.
- `npm run test:api:fast` — **1,769 passed**. Local optional Kernel mock/base
  URL/token settings were cleared only in child check environments; initial
  production-settings test failures from inherited development configuration
  are superseded by the passing run.
- `npm run check:fast` — PASS, including **38** web boundary/typecheck,
  **396** component and **1,769** fast API tests.
- Focused PostgreSQL reruns — **7 passed** for incomplete-inventory recovery
  and concurrent Widget opens; **3 passed** for legacy support and the new
  audited-restoration scenario; complete worker module — **25 passed**.
- Initial focused history tests exposed fixture-only assumptions: rewriting
  immutable evidence, observing Python tuples before JSON persistence, claiming
  an unrelated overdue local job, and retrying operator restoration without
  respecting its retained lease/fence. Fixtures now append/reload evidence,
  isolate the intended local deadline, and use current negative application
  plus fresh operator expectations. No runtime safety guard was relaxed.
- Intermediate full PostgreSQL/check runs were interrupted while compatibility
  assertions were corrected; they are not recorded as completed suite passes.
- A subsequent full canonical run completed with **982 PostgreSQL passes and
  nine failures** in seven queue-isolation assertions and two old reconciliation
  expectations. The tracebacks confirmed those exact compatibility assumptions;
  no runtime transition changed to accommodate them. The complete isolation
  module plus both corrected reconciliation scenarios then passed together:
  **24 passed**. Final canonical validation is recorded below.
- One repeat canonical attempt stopped on an unrelated 5-second
  `HeaderNavigation` component-test timeout. Its unchanged focused module then
  passed **14 tests** (232 ms test execution); no UI code or timeout policy
  was changed. The final full run supersedes this attempt.
- Browser payment regression:
  `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3215 npm run test:e2e --
  apps/web/e2e/any709-purchase.spec.ts --workers=2` — **16 passed**, desktop and
  mobile, against the production web build with simulated API/LBX Widget.
  The temporary server used `APP_PUBLIC_BASE_URL=http://127.0.0.1:3215`.
  An initial server invocation without that required metadata setting was
  stopped and superseded by this passing run.
- The complete browser suite and live provider/webhook conformance were not
  run. Canonical checks use `RUN_E2E=false`; the full local application stack
  was not started. Affected purchase/payment browser coverage ran separately
  above; existing ANY-504 enablement gates remain unchanged.

Final validation of the resulting working tree:

- `KERNEL_MOCK_ENABLED=0 KERNEL_BASE_URL= KERNEL_SERVICE_TOKEN=
  RUN_E2E=false PATH="$PWD/.venv/bin:$PATH" npm run check` completed all
  repository sections through PostgreSQL. Documentation, generated freshness,
  architecture, Python/web lint, **38** boundary/typecheck tests, **396**
  component tests, **1,769** fast API tests and the production web build passed.
- The PostgreSQL section finished with **990 passed, one failed** in
  **2,929.42 seconds**. All billing/Step 8 suites, including the corrected
  isolation/reconciliation assertions and new history/deadline/operator
  regressions, passed. The only failure was the unchanged
  `test_kernel_walkthrough_postgres.py::test_fresh_http_publication_faults_outage_restart_and_recovery`:
  `PreflightCleanupPending` during HTTP cleanup. The full canonical command is
  therefore **not recorded as PASS**.
- The entire unchanged Kernel walkthrough module was rerun using the same
  worktree PostgreSQL environment: **2 passed in 9.02 seconds**. This cleanup
  failure was not reproduced; no unrelated catalog/preflight fix or timeout
  change was introduced. The preceding complete PostgreSQL run had also passed
  both Kernel walkthrough tests. This is the remaining global-check caveat,
  rather than an unexecuted or failed Step 8 acceptance case.
- Final Ruff lint/format checks, documentation checks and `git diff --check`
  passed. The cumulative diff retains full-proof-only operator admission and
  old evidence formats, contains no `allow_terminal`/`LbxFinancialEnded`, and
  adds no migration, generated API drift, paid-access writer or unrelated
  runtime cleanup. No unfinished Stage 4 implementation remains.
- The worktree PostgreSQL server was stopped with
  `.venv/bin/python scripts/repo.py test-db stop`; the temporary web server is
  also stopped. Branch and HEAD remain unchanged. No commit, push, merge or
  separate ANY-765 integration was performed.

Stage 4 behavioral acceptance is satisfied. No new code blocker for the
separately authorized ANY-765 integration was found. Its paid-state integration
and combined-branch acceptance remain outside this completed execution.
