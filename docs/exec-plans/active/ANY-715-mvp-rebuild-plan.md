# ANY-715 — Rebuild the MVP implementation from the functional-QA baseline

Status: Stages 0–4 complete; Stages 5–6 pending. Final rebuild QA and acceptance remain pending.
Prepared: 2026-11-05. Repository: `gushinets/payments-portal`. Reference PR: #154; delivery: a separate Draft PR created in Stage 0.

## 1. Outcome and execution instructions

Rebuild Step 8 from the smaller QA baseline, retain the necessary fixes discovered by review, and remove duplicate interpretation/write paths. Deliver working purchase preparation, account/payment Widget, browser-independent polling, UNKNOWN recovery, scoped inventory and minimal operator recovery. Do not reproduce the later readback subsystem under different names.

The owner explicitly chose this rebuild, polling-only MVP and publication through a new Draft PR from `refactor/any715-mvp` into `main`, starting in Stage 0. This document replaces the previous refactoring execution prompt, including earlier instructions not to push and later to rewrite PR #154. It is an implementation plan, not an instruction to restart broad architecture research.

- Execute stages 0–6 in order. If asked to execute one stage, complete that stage, its relevant checks and its specified publication, then report and stop. If asked to execute the whole plan, continue through all stages without requesting routine confirmations.
- Stage 0 creates the reviewable branch and Draft PR before refactoring starts. After each later completed stage and its relevant checks, make one coherent commit, normally push it to that same branch, and update the same Draft PR's progress/evidence. These actions are authorized; do not ask for publication permission again. Report the PR URL, commit and remaining checks.
- Read the named authorities and affected callers. Investigate further only to resolve a concrete contradiction or a failing required scenario.
- Do not rewrite the plan, generate a new design document, or run an open-ended review loop before implementation.
- Use one checked-in copy at `docs/exec-plans/active/ANY-715-mvp-rebuild-plan.md`; keep a short checklist/evidence section there. Do not add a handoff document for every stage.
- Repository documentation, code comments and commit messages remain English. Report progress to the owner in Russian.
- Preserve PR #154 and its `ANY-715` branch. Do not force-push, close the old PR, resolve review threads, mark the new PR ready, merge or deploy automatically. Stage 0 authorizes the new branch/Draft PR and subsequent normal pushes/progress-body updates, not those separate final actions or live financial operations.

## 2. Exact starting points

| Purpose | Commit |
| --- | --- |
| Rebuild baseline | `9e0cf6ec7bf690b40377b37c436d66ac72b5ea9d` |
| Reviewed implementation to preserve as reference | `591ee6cad0155563390c5d120da5fb89367455a5` |
| PR base used for the audit | `43943644d277244e8838a693f0d55348d202d7e5` |

The baseline is the rebased equivalent of ANY-715 `76ea1a7`, included in the historical functional QA on ANY-765 `74935d0`. This is not a new live QA result for the exact rebased SHA. Baseline PR diff: +12,013/-499; later head: +22,476/-855. These are PR additions/deletions, not repository LOC.

## Stage 0 — Preserve the original, create the worktree and publish a Draft PR

Outcome: the owner has a working GitHub link before implementation begins. Creating the Draft PR is part of this stage, not a later optional action. Application code remains at the QA baseline; only the execution plan and necessary documentation registration change.

1. Inspect `git status`, worktrees, branch pointers and the current remote PR head. Preserve uncommitted user work and any newer commits. Do not reset the user's checkout or overwrite an existing branch.
2. Create a local backup reference for the actual current PR #154 head, for example `backup/any715-before-mvp-rebuild-<short-head>`, and retain `591ee6c` for the audited comparison. Reuse an existing matching backup; do not move a mismatching reference. PR #154 and its remote branch also remain available as the original reference.
3. Create/reuse a separate worktree and rebuild branch **`refactor/any715-mvp`** based on the exact `9e0cf6e` SHA. If that branch already contains work from this plan, verify its ancestry and reuse it without resetting completed stages. Inspect an unrelated name collision instead of overwriting it. The audit's `analysis/any715-mvp` branch may exist only in the analyst's environment; do not assume it exists on the owner's machine.
4. Set up the normal worktree environment using repository instructions. Do not copy secrets or a sibling worktree's database configuration. Record the starting SHAs and baseline diff size once.
5. Leave the current remote `ANY-715` branch untouched during implementation. Changes after `591ee6c`, if any, are additional review material, not permission to discard them.
6. Do not reset/rebase dependent branches such as ANY-765 or other worktrees. Do not reset an application/shared database to make the old code run. Check the migration tip and whether a later build wrote data that the rebuilt reader must retain; use an isolated harness database for development and preserve original bindings/history. Record any compatibility follow-up required before the new PR becomes the final replacement.
7. Add this plan at `docs/exec-plans/active/ANY-715-mvp-rebuild-plan.md`, register it as required by repository documentation rules, and commit the Stage 0 documentation with an `ANY-715 - ...` title. Run the applicable documentation checks. Do not run or wait for full application QA just to open the draft; report any unavailable check honestly.
8. Verify the Git remote points to `gushinets/payments-portal`. Normally push the new branch and establish its upstream, for example `git push -u origin refactor/any715-mvp` when `origin` is that repository. Do not push `ANY-715` or use any force option. A non-fast-forward rejection means inspect and preserve the remote work, not overwrite it.
9. Find and reuse an existing open PR with this exact head branch and base `main`; otherwise **create a Draft PR now**. Suggested title: **`ANY-715 - Rebuild polling-only billing from QA baseline`**. Follow the repository PR template and include exactly one full Linear issue URL for ANY-715. The body must link PR #154 and identify the QA-baseline SHA, preserved original head, plan path, completed Stage 0 and pending Stages 1–6. Explain that polling-only/refactoring are planned outcomes, not already implemented; historical QA is not fresh QA for this rebuild. Keep acceptance boxes pending and report only checks actually run. When using `gh`, write the multiline body to a temporary file and use `--body-file`.
10. Confirm the remote branch contains the Stage 0 commit and the PR has base `main`, the correct head and Draft status. Return the **PR URL, worktree path, branch, backup reference, published commit and checks** to the owner. If asked for Stage 0 only, stop here. A request for Stages 0 and 1 continues into Stage 1 after publishing the draft.

If GitHub authentication or publication is unavailable, finish the local preparation and give the exact failed operation and required unblock; do not claim a PR exists or substitute a second local-only branch. No extra confirmation is required for the Stage 0 push/PR itself. Re-running Stage 0 must reuse the same branch/PR and preserve existing implementation work.

Subsequent stages append commits to this same branch and update this same Draft PR. Use the PR body and the plan's short progress section for status; do not create a new PR or unsolicited review comments for every stage.

## 3. Authority and fixed scope

Read root/API/Web/docs `AGENTS.md` as applicable, `ARCHITECTURE.md`, the relevant coding conventions, and these sources in precedence order:

1. `docs/architecture/decisions/0005-external-billing-boundary.md`, including its exact dated references.
2. [ANY-504](https://linear.app/paveldik/issue/ANY-504), section **Accepted ANY-709 contract decisions — 2026-10-31**, C1–C4, and Step 8; [ANY-715](https://linear.app/paveldik/issue/ANY-715) scope/acceptance.
3. `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`: commercial decision table, identity, UNKNOWN, trust and background work.
4. `docs/superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md` within its stated scope; the Portal–Kernel September contract only for Step 8/9/10 boundaries.

Do not read the entire ticket graph. The old completed plan, old QA, review comments and `591ee6c` are evidence/reference implementations; they do not override this authority chain.

| Accepted decision | Preserve exactly |
| --- | --- |
| C1 | Direct product links; live offers for new purchases; immutable accepted purchase terms/history. No approval-file certificates, periodic catalog mirror or price-change relinking. |
| C2 | Account Widget is independent of a purchase. Payment Widget still requires the exact owned prepared purchase and fresh required proof. |
| C3 | Customer-only conditional retry after complete empty discovery within the bounded explicit opening, retaining the provider-email-uniqueness assumption and other restrictions. Do not extend it to agreement/subscription CREATE. |
| C4 | A genuinely new explicit attempt after typed `PROVEN_NOT_SENT` has a new fixed active recovery window; immutable original history remains. UNKNOWN/GET/retry scheduling never authorizes another financial POST or renews that window. |
| Point-resource decision, 2026-11-01 | Authenticated canonical point URL selects the resource. No new returned-self-ID-versus-URL defense against hypothetical provider violations. Keep owner, original key, seller, agreement, tariff/composition and immutable binding checks. Discovery/receipts are candidates. |

Keep one embedded worker, PostgreSQL durable work, normal ~15m/urgent <=5m/stable inventory ~6h, finite source trust <=6h, provider-free deadlines, bounded HTTP/DB resources, short claim/apply transactions, immutable consent and original financial commands. No paid grants, allowance accounting, `access_revision`, Kernel invalidation delivery or Step 10 date/wire redesign in this change.

Do not switch ORM/async architecture, add Celery/Redis/services, design multi-contour shared-DB defenses, introduce generalized proof engines or benchmark hypothetical 10,000-user loads. Do not edit accepted specification bodies to make implementation tests pass.

## 4. Final ownership of behavior

| Responsibility | Existing owner to evolve |
| --- | --- |
| LBX field/lifecycle interpretation | `apps/api/app/integrations/lbx/reconciliation.py` and narrow pure helpers in `integrations/lbx/financial.py` |
| Known subscription claim, observation and projection update | `domains/billing/reconciliation.py`, orchestrated by `composition/reconciliation.py` |
| First financial binding only | `domains/purchases/financial.py`; existing original-operation proof and send fence |
| Original CREATE recovery orchestration | `composition/purchase_recovery.py`; share it with interactive recovery/operator binding |
| Inventory membership and competition | One implementation extracted/evolved from `composition/purchases.py::_inventory` and `domains/purchases/inventory.py`; used by admission, worker and operator |
| Review authorization and atomic audit | Existing `domains/billing/operator_review.py` and `operator_contracts.py` |
| Scheduling/claim ownership | Existing `domains/billing/work.py`, `background_recovery.py` and `jobs/billing.py` |

Prefer changes in these owners. A small extraction is justified when it removes actual duplication/cycles; file splitting alone is not simplification. Use existing `SubscriptionProof`, `ReconciliationSubject`, `SubscriptionCandidateSubject`, `OriginalOperationProof`, `ReviewResolution` and `WorkClaim`. Extend a contract only for a demonstrated caller need.

## Stage 1 — Correct and centralize interpretation

Primary files: `integrations/lbx/reconciliation.py`, `integrations/lbx/financial.py`, `domains/billing/reconciliation_contracts.py`, `tests/test_billing_subscription_reconciliation.py`.

Implement the following table once; adapt contradictory existing tests to the authoritative meaning, not to the old implementation:

| Evidence | Required interpretation/effect |
| --- | --- |
| Complete owner + complete accepted material terms/policy + supported active/unblocked state + required cycle facts | Eligible for a positive source observation; only the shared fenced writer may refresh finite trust. |
| Missing material terms/policy/currency interpretation, including absent local currency mapping | `INCOMPLETE`; no new permanent commercial-conflict case and no trust extension. Known differences may remain diagnostic reasons. |
| Full material commercial reconstruction proves a difference | `COMPLETE_MISMATCH`; restrict the affected scope and enter review. |
| Proven owner/relationship contradiction | Identity conflict remains decisive independently of commercial completeness. |
| Proven canonical waiting/blocked/ended state with the ownership evidence required for that decision | Ordinary negative; persist it even if unrelated tariff/commercial data are incomplete. No automatic financial-binding conflict. |
| Missing/unknown lifecycle information without a proven negative | Incomplete; never invent active, terminal, dates or payment settlement. |
| Local contention, expired claim or source timeout | Retryable uncertainty, not provider conflict or no-send proof. |

Specific corrections:

- `state=3` with recognized blocking values `0`, `1`, `3` is terminal. Valid agreement closure is terminal evidence. Unknown codes remain incomplete.
- Separate original identity/effective-term proof from whether the object can still be prepared or paid. `prove_agreement()` / `prove_subscription()` must not encode normal termination as an identity mismatch consumed by broad exception handlers.
- Commercial completeness concerns the material facts applicable to this purchase; do not demand unrelated optional fields. Preserve zero-connection-price applicability rules. Current catalog price does not replace accepted effective subscription terms.
- Read canonical ownership/subscription facts before a potentially slow tariff-policy read so a timely negative need not be lost behind that read. Preserve absolute budgets and rejection of late responses.
- For an already bound subject, proven customer/closed-agreement ownership plus its retained canonical binding can establish an agreement-based negative even if the subscription read is unavailable. Keep that minimum negative proof distinct from complete commercial/positive proof. It cannot establish a first binding for an unknown candidate.
- Keep date-only LBX values as calendar evidence. Preserve existing period/trust limits; do not invent UTC instants or recalculate charges.

Acceptance: compact parameterized pure tests cover the table, especially missing total plus changed period/price, absent currency mapping, blocked with missing terms, closed agreement and terminal blocking variants. Positive matching, historical accepted price and immediate identity-conflict cases remain covered.

## Stage 2 — One claimed path for already bound subscriptions

Primary files: `composition/reconciliation.py`, `domains/billing/reconciliation.py`, `composition/purchases.py::verify_payment_purchase`, `composition/billing.py`, `domains/purchases/widget_admission.py`; relevant HTTP/worker tests.

1. Extend the existing orchestration to return the committed observation/result needed by a caller. Keep one normalizer and one existing projection writer; do not introduce an alternative negative-only readback writer.
2. Acquire and commit the existing per-subscription lease/fence **before** source reads that can update a known subscription. Perform HTTP outside DB transactions, then verify ownership, immutable provenance, lease, customer/operation fences and source-read time bounds in the short apply transaction.
3. Migrate payment Widget and already-linked `advance` away from `_prepare -> _recover_one -> bind_financial`. They verify the original bound subscription through this path. Operator reconciliation already uses it; preserve that reuse.
4. Payment admission requires successful committed fresh identity/commercial proof, a supported nonterminal state, no blocking review, and the existing final session/email/customer/purchase check after Client readiness. Waiting/unpaid or financially blocked can be payable; they do not imply paid access. Incomplete proof and ended objects cannot mint payment presentation. Account-only Widget stays independent under C2.
5. If another reader owns the lease, return a bounded retryable busy/pending result and preserve due work. Do not start an unclaimed read or an optimistic reread protocol. Map contention to existing user-facing pending/busy handling, not permanent review or a silent click failure.
6. Keep the HTTP read budget distinct from the short DB apply. An enclosing Widget I/O timeout must not discard a timely proven negative merely because a later optional read timed out. Reuse the worker's `bound_scope=False` pattern only where appropriate, with all actual source calls still budgeted and final credential admission deadline-checked. Do not add detached tasks or global timeout rewrites.
7. Preserve cancellation cleanup/resource accounting. Cancellation/crash before commit is not durable evidence; recovery relies on finite leases/polling. Never return successful payment verification before the apply commits.
8. Retain atomic customer-wide and purchase-scoped review restriction. A customer conflict restricts its linked subscriptions; a financial/product conflict restricts only its scope. Preserve old source timestamps as history. Invalidate stale operation/reconciliation proofs so a later operator restore cannot make an old in-flight ACTIVE proof valid again.

Scheduling detail: a normal reconciliation job may finish only its own queue claim. HTTP/operator observations coalesce follow-up work without clearing another worker's lease/new hint. Stage 4 inventory-origin applies must validate the inventory claim but must not finish that customer job as a subscription job.

Acceptance: actual HTTP payment path, worker and operator use the same committed projection transition. PostgreSQL tests cover busy lease, expired old owner, old ACTIVE versus later negative, customer conflict and operator restore during an old read. Add no `ReadbackSubject`, `ReadbackRecheck`, `APPLIED/HINT_ONLY/SUPERSEDED` protocol or second projection chronology.

## Stage 3 — Narrow original financial recovery and first binding

Primary files: `composition/purchase_recovery.py`, `composition/purchases.py::_find_financial/_recover_one/_prepare`, `domains/purchases/financial.py`, `composition/purchase_observation.py`, `composition/billing_operator.py`, existing original-operation contracts.

- Share one GET-only original-operation recovery between advance, worker and operator. It handles POSSIBLE_SEND/UNKNOWN and permitted reviewed original operations. `BOUND` goes to Stage 2 or is a no-op for a completed recovery job; it never rebinds or appends another preparation observation.
- Before first binding require saved original command/key, actual possible-send history, original dedicated agreement, unique complete candidate discovery where required, point ownership and applicable accepted effective terms. Negative state alone, a receipt, empty discovery or matching tariff never proves an original operation.
- Recover an original ended subscription or closed agreement when the required original proof is complete. Persist the historical binding and known negative in the first-bind transaction using the same interpretation. A recovered closed agreement must not lead to a new subscription POST. A terminal subscription is not payable and cannot become a positive grant.
- New subscription preparation has zero positive trust until a complete authoritative reconciliation. Preserve the distinction between preparation and paid proof; missing cycle dates on a legitimate waiting subscription do not make its original creation unprovable.
- Keep the current transactional binder and original send fence. If another transaction has already bound the same object, reload and use the known-subscription path; reject/discard a stale candidate proof. Do not apply pre-binding source evidence to an existing canonical subscription without its lease.
- An ambiguous financial POST stays GET-only; preserve C3 only in customer bootstrap and C4 only for a completed proven-unsent explicit financial continuation.
- Preserve automatic resolution of a deadline-only case when the original object is proved. Real commercial/identity/inventory conflicts require the authorized operator path. No arbitrary new ID adoption, manual paid flag or release of an uncertain purchase hold.
- Remove duplicate operator source reads: collect the required original evidence once for that attempt, normalize it once and reuse it for the existing authorization/bind/audit transaction.

Delete obsolete bound-object branches from `_recover_one` / `_bind_financial` when migrated, rather than retaining them for old tests. Search production callers before removing `escalate_overdue_financial` or other apparent dead helpers; preserve any real CLI capability through the existing durable deadline owner.

Acceptance: lost reply/delayed discovery, deadline-only recovery, terminal original result, closed original agreement, conflicting candidate and concurrent first bind are covered. Assert financial POST count and immutable command/fence/history, not only the returned HTTP code.

## Stage 4 — One scoped inventory check and a usable operator exit

Primary files: `_inventory` in `composition/purchases.py`, `domains/purchases/inventory.py`, `composition/billing_background.py`, `domains/billing/background_recovery.py`, `composition/billing_operator.py`, `domains/billing/operator_review.py`.

1. Extract/evolve one bounded inventory implementation reused by pre-send admission, background inventory and operator review. Keep the existing size bound, complete pagination/discovery requirements and stable re-list checks. Do not let a pending original candidate hide a later real competitor.
2. Identify known subscriptions/products from permanent original local bindings, not `LINKED` versus `MANUAL_REVIEW`. Another product's valid binding remains its binding during review; its term conflict must not become the current product's inventory conflict.
3. An own possible-send/UNKNOWN (or evidenced deadline-only review) candidate on the original dedicated agreement is pending recovery, not automatically a foreign subscription. Only Stage 3 can bind it. Multiple/unproved candidates remain uncertainty/conflict according to the actual evidence.
4. For a known canonical candidate, acquire its existing subscription lease before point reads that produce lifecycle effects; use Stage 2 interpretation/apply. Discovery results are candidates and cannot update projections. Do not reuse a point-result cache captured before that subject's lease. A busy candidate makes inventory incomplete and schedules retry; it does not create a second read/write path.
5. Each known-subscription observation may commit independently under its lease. Validate an inventory-origin `WorkClaim` against its customer/current ownership in that apply; call subscription scheduling without completing the customer claim. Finish customer inventory only in its own existing apply. A lost claim cannot report successful completion or erase another owner's work.
6. A valid closed agreement/terminal subscription is not a live competitor. Keep any timely canonical negative already applied even when later inventory discovery is incomplete. Never clear a review from an incomplete inventory pass.
7. Before financial send, a competitor blocks admission. For `PENDING`/`PROVEN_NOT_SENT` without a bound subscription, keep no-send evidence and the ability to retry explicitly after correction; do not manufacture a permanent financial-review state. Invalidate stale pre-send snapshots by rotating relevant unsent fences under the existing lock. Do not release holds or schedule a financial POST.
8. Extend the existing `restore-original` / `bind-original` operator actions to resolve the exact inventory-related cases that this implementation creates. Reuse the common fresh inventory check plus the required original/known-subscription proof. Keep principal authorization, expected case/operation/observation fences, related-case validation and atomic audit. Resolve only proved related cases; no blanket clearing or manual DB edits.
9. For operator `restore-original`, claim the target subscription once and keep that lease through its source proof and shared inventory check. Inventory reuses the target's already claimed reads; it must not independently claim/apply that target and consume the expected reconciliation fence. Target projection, exact case resolution and audit commit together through the existing apply. Other affected subscriptions may commit their independently claimed negatives without resolving the target case.
10. The common inventory result distinguishes an original pending candidate from a competitor. Pre-send admission waits on that candidate; `bind-original` may proceed only when Stage 3 also proves the saved original operation completely. Do not make all pending inventory an unresolvable operator failure, or relax candidate identity to make the action succeed.
11. Recheck local binding/operation versions used by inventory at commit. Track versions returned by this attempt's own committed transitions instead of comparing to a knowingly stale starting snapshot. Never reload arbitrary concurrent changes after source I/O and treat them as the original proof's subject; unexpected changes require a fresh attempt. Do not create a new general witness/rebase protocol.

Acceptance: two products sharing a tariff remain isolated; own UNKNOWN recovers; true competitors block; unsent conflict can later resume; active-review conflict has an audited exit; a stale operator command fails; incomplete discovery cannot silently clear a conflict. Operator and worker must not own separate candidate/lifecycle classifiers.

## Stage 5 — Finish bounded worker fixes and remove deferred receiver

Worker files: `domains/billing/work.py`, `background_recovery.py`, `composition/billing_background.py`, `jobs/billing.py`, `core/settings.py`.

- Preserve `retry_work()`'s acknowledgement contract and check its result in every caller. False/stale ownership is not committed progress. Do not introduce a second retry abstraction to fix an ignored boolean.
- Incomplete/conflicting inventory must enter the urgent lane as well as receive an urgent due time. A clean completed pass may return to normal priority only if no newer generation/hint is pending.
- Port the bounded worker timeout fix (`1e0e931`): default 60s, maximum 240s, preserving claim/apply margin and urgent retry cadence. Keep the local lane independent of slow provider I/O and preserve restart/enrollment, queue generation and cancellation semantics.
- Port the small early-click session-guard fix from `3c69c8d` and its component regression in `apps/web/src/shared/session/use-session-operation.ts` / `apps/web/tests/components/any709-step2.test.tsx`. No UI redesign.

Polling-only removal:

- Remove the new receiver registration and receiver-only implementation: `http/billing_webhook.py`, `integrations/lbx/webhook.py`, `domains/billing/webhooks.py`, `domains/billing/webhook_contracts.py`, `infrastructure/queries/billing_webhooks.py`, `infrastructure/persistence/billing_webhooks.py` once references are gone. Remove receiver processing hooks from reconciliation.
- Remove receiver enablement/auth settings and propagation from settings, env examples, Compose/harness, generated OpenAPI/TypeScript contracts and operational docs. The endpoint remains unavailable/404 and cannot accidentally be enabled.
- Preserve pre-existing schema/history tables and the Step 8 worker migration. Do not add a table-drop migration merely to remove an unused optional receiver. Existing inbox rows are retained history; document that this build does not process receipts.
- Replace receiver-only acceptance with one polling-only scenario proving no callback/webhook is required and no endpoint request changes billing facts. Preserve reusable isolation, duplicate-work and hint-generation tests through the remaining real enqueue paths. Delete only tests of removed receiver behavior, not unrelated guarantees.
- Update the runbook, architecture/current-status references and navigational guides to say polling-only. Use `npm run generate`; never edit generated contracts directly. Do not restore the later 2,000-line completed plan or 900-line refactoring plan into this rebuilt PR; reference historical commits when needed.

Acceptance: ordinary purchase and worker operation survive webhook absence, HTTP 404 cannot grant/mutate anything, retry acknowledgement/priority/cadence are correct, and no receiver configuration or processing import remains active.

## Stage 6 — Verify the smaller implementation and finalize the new Draft PR

### Focused scenario matrix

Use existing factories/fixtures and parameterization. Avoid copying a complete PostgreSQL fixture per reported example or multiplying every input by every entrypoint. Pure classification gets a small table; reachable entrypoints get representative integration cases; actual concurrency gets PostgreSQL tests.

| Scenario group | Required assertions |
| --- | --- |
| Normal user journey | Live offer -> acceptance -> one original agreement/subscription -> payment Widget; account Widget also works without a purchase. No paid access inferred from callbacks. |
| Commercial evidence | Full match/mismatch; missing total/policy/currency with a known difference; old accepted price versus new catalog price; no false permanent review or trust extension. |
| Lifecycle across callers | Previously trusted ACTIVE -> blocked/ended/closed agreement through worker, payment verification and inventory; ordinary negative committed, old positive cannot overwrite; payment blocked for terminal, not merely unpaid. |
| Financial uncertainty | Lost reply, late discovery, UNKNOWN deadline, no-send explicit continuation, original terminal binding; no duplicate financial POST and no rewritten accepted history. |
| Product isolation | Shared tariff, sibling in review, own pending candidate, additional true competitor, incomplete list and closed competitor agreement. |
| Recovery and operator | Restart/backfill, fixed active deadline, unsent admission retry, inventory review resolution, unrelated/stale case refusal, atomic audit and restriction. |
| Ownership/concurrency | Competing leases, expiry/reclaim, operation/customer fence changes, old ACTIVE versus later negative/restore, inventory queue-owner loss, newer hint generation, failed commit and cancellation. |
| Degraded provider / polling-only | Outage does not renew six-hour trust; local expiry/deadline work continues; no browser or webhook needed; finite retry and truthful progress/health. |
| Browser behavior | Early click, pending/busy presentation, session change during I/O, no credential returned for stale admission; desktop/mobile flows remain usable. |

Run focused tests after each stage and format/lint touched code. For final verification, use the repository's Python 3.12 / Node 24 / PostgreSQL 18 / pinned uv environment and normal harness:

```bash
npm run repo:doctor
python scripts/repo.py test-db up
npm run generate
npm run check
```

`npm run check` is the final canonical command; consult its current wiring and run any required PostgreSQL/browser check it does not include through the existing aliases (`test:api:postgres`, `test:e2e`). Do not rerun whole suites after every tiny edit. Stop the isolated test server when finished. Missing tooling or a skipped suite must be reported, not converted into PASS.

For real LBX functional QA, reuse the established isolated stand/worktree, approved test identities and any existing authorization for that test scope; do not ask for it again. Verify purchase/Widget, polling after browser closure, stored identities and accepted terms, repeated opening, and operator visibility. Provider writes or charges outside that authorization need a concrete owner decision; prepare those cases for the owner when authorization/credentials are absent. Label synthetic transition/concurrency coverage as SIMULATED; do not claim natural renewal or final Kernel quota enforcement.

Historical evidence: [functional QA report](https://linear.app/paveldik/document/any-715-itogovyj-otchyot-funkcionalnogo-qa-2026-11-03-08767e6ffa49), [PR QA comment](https://github.com/gushinets/payments-portal/pull/154#issuecomment-6595517495). These establish earlier behavior, not PASS for this rebuild. The analyst ran baseline non-PostgreSQL checks and diagnostic probes; those do not validate the proposed new lease-based routing.

### Reference fixes to preserve by behavior

| Historical commit | Keep / change |
| --- | --- |
| `4996a8b` | Keep inventory-review exit and correct retry acknowledgement/routing; implement through shared inventory, not a parallel operator classifier. |
| `b727b44` | Keep own UNKNOWN/deadline-only candidate handling and unsent-admission fencing. |
| `f1921b1` | Keep sibling-product isolation during review. |
| `94ca836`, `b3936bc` | Keep normal terminal/closed-agreement handling, original terminal recovery and customer-wide restriction. Do not copy known-commercial-difference-before-completeness policy where it contradicts the normative table. |
| `1e0e931`, `8bee7b6`, `3c69c8d` | Keep timeout bound, immediate financial-conflict restriction and early-click fix. |
| `65a889a` | Historical documentation restoration; no runtime behavior to port. |
| `591ee6c` | Consult useful classification and race scenarios. Do not import its readback subject/capture/order/recheck/binding subsystem or retain production helpers used only by tests. |

Do not cherry-pick this sequence wholesale. A review thread is not a requirement by itself: map each material remark to the actual scenario, authority and final test/fix; keep retracted self-ID/mixed-contour defenses out of scope.

### Completion and handoff

- One canonical known-subscription claim/read/apply path; one original financial binder; one inventory classifier; minimal audited operator actions. No old bound-rebinding fallback retained for fixture compatibility.
- Necessary Step 8 behavior and ADR exceptions preserved; optional receiver explicitly removed; no schema/framework expansion or later-step feature work.
- Every added runtime abstraction identifies the old branch/duplication it replaces or the concrete missing MVP behavior it provides. Report net runtime/test/docs changes against both `9e0cf6e` and the preserved current head. Final runtime must be materially smaller than `591ee6c`; do not achieve this by deleting acceptance coverage or hiding code in generated/dynamic wrappers. Do not promise a fabricated exact LOC saving.
- One short final section in this plan: completed stages, exact tested SHA, check results/limitations, removed paths, size comparison, and review disposition. Prepare PR title/body around the final polling-only outcome and fresh evidence; do not describe historical QA as current.
- Push the verified final stage normally to the new branch and update the existing Draft PR with its final scope and fresh evidence. The new PR is the proposed primary implementation; keep it Draft until the owner requests otherwise. PR #154 remains preserved and may be closed as superseded only after the owner's final decision. No rewriting of `ANY-715` or force-push is part of this workflow. Prepare the old-review-to-new-fix/test mapping; reply to or resolve threads only when instructed, without erasing discussions or implying approval.
- If the proposed reuse demonstrably cannot satisfy a required invariant, record the smallest reproducible counterexample and the exact unmet requirement. Do not silently recreate the rejected subsystem or weaken the invariant. Continue independent bounded work and surface that specific design decision to the owner.

Progress: Stage 0 [x]; Stage 1 [x]; Stage 2 [x]; Stage 3 [x]; Stage 4 [x]; Stage 5 [ ]; Stage 6 [ ].

## Stage 0 evidence — 2026-11-05

- Preserved PR #154 and its local/remote `ANY-715` head at
  `591ee6cad0155563390c5d120da5fb89367455a5`; backup reference:
  `backup/any715-before-mvp-rebuild-591ee6c`. No newer remote commits were
  present. Existing worktrees and dependent branches were left untouched.
- Created `refactor/any715-mvp` at the exact Section 2 baseline in the separate
  worktree `/home/wstanley/www/work_unirec/payments-portal-mvp`. The original
  untracked uppercase-name plan remains untouched in the owner's checkout;
  this lowercase path is the only checked-in rebuild plan. Stage 0 changes
  only this plan and its registration in `docs/README.md`.
- `repo:setup` completed with Python 3.12.13, Node 24.14.0, npm 11.11.1 and
  uv 0.12.7. An ignored `.harness/bin/python` launcher supplied the missing
  shell `python` command for initial setup; subsequent commands use
  `PATH="$PWD/.venv/bin:$PATH"`. Dependencies live in this worktree's own
  `.venv` and `node_modules`; no sibling configuration or secrets were copied.
  npm reported 21 dependency audit findings (14 moderate, 7 high); dependency
  changes and audit triage are outside this documentation-only stage.
- Generated a fresh isolated harness: project `payments-1fd59ebf`, database
  `payments_1fd59ebf`, PostgreSQL port `32503`, web/API ports `30503`/`31503`.
  No `.env` or nonempty external secret fields are present. No application or
  test database was started, reset, migrated or otherwise written by this stage.
- Offline Alembic head: `20261028_0005`. Migration files and canonical ORM
  models are identical between the baseline and preserved head. The original
  project's PostgreSQL container is stopped; its on-disk revision and rows
  were not queried or changed, so existing-data compatibility is not PASS.
- Compatibility follow-up before final replacement: inspect a safe copy of
  the retained later-head data, verify its actual migration revision and test
  preservation of original customer/financial bindings, immutable accepted
  terms, observations, review cases and work generations. The later head can
  write `bound-source-negative:v1` observations with `negative_only` /
  `source_negative` classifications; retain those rows and ensure the rebuilt
  reader/shared writer respects their negative facts. Schema equality alone
  does not establish behavioral compatibility. Never downgrade/reset the
  original database to run the baseline.
- Checks: `repo:doctor`, `repo:setup`, `harness-smoke`, offline `alembic heads`,
  `npm run docs:check` and `git diff --check` passed. Application files remain
  byte-for-byte at the baseline. Full `check:fast` / `check`, PostgreSQL,
  browser and real LBX QA were not run for this documentation-only stage;
  historical functional QA is not fresh validation of this rebuild.
- Publication: normal push of this Stage 0 documentation commit to
  `refactor/any715-mvp`, with a Draft PR into `main`; the exact published SHA,
  PR URL and remote/Draft verification are recorded in its body and the owner
  report. PR #154 remains the original reference. Stages 1–6 are pending.

## Stage 1 evidence — 2026-11-05

- Corrected the shared LBX normalizer: missing material effective terms,
  applicable policy or configured currency interpretation is `INCOMPLETE`, even
  alongside a known difference. Only complete reconstruction can produce a
  commercial mismatch. Original-key/owner/relationship conflicts remain
  decisive independently of commercial completeness; point URL selection
  follows ADR 0005 without returned-self-ID comparisons.
- Centralized supported lifecycle codes in a small Integration helper. State 3
  with blocking 0/1/3 and valid agreement closure are ordinary terminal
  negatives. Unknown/missing codes remain incomplete. Complete retained
  customer/agreement ownership can prove a closed-agreement negative for an
  already bound subject when its subscription read is unavailable; a candidate
  cannot use that minimum proof for first binding.
- Separated original agreement/effective-term proof from preparation/payment
  readiness. Existing callers retain explicit readiness checks, so termination
  refuses payment without creating a financial-binding conflict. Shared
  claimed routing and original terminal binding remain Stages 2–3 work.
- Customer/agreement/subscription reads now precede tariff policy. Every call
  is checked before dispatch and after either a value or a scope error against
  the same absolute budget. Timely negatives survive an unavailable late policy;
  late subscription values/errors cannot become facts or identity conflicts.
- Preserved accepted historical prices, zero-connection-price applicability,
  calendar precision and existing finite trust. No new projection writer,
  proof protocol, HTTP contract, ORM/model or migration changes were introduced.
- Focused verification: 107 pure/read-budget/purchase tests passed in
  `test_billing_subscription_reconciliation.py` and
  `test_any709_step3_purchase.py`; 15 tests passed in
  `test_billing_subscription_reconciliation_postgres.py`, using only the
  worktree's disposable database and the repository's test-environment helper.
- An initial broad `npm run check` passed docs/generation, architecture, API/web
  lint, 38 web boundary tests, 395 component tests, 1,718 fast API tests and
  production build. Its PostgreSQL partition exposed four obsolete healthy
  fixtures without `current_blocking`; the run was interrupted after 112 other
  passes. Added the recognized blocking value to that fixture, preserving all
  no-duplicate-CREATE/recovery assertions; all four affected cases then passed.
- Owner execution preference: run only necessary affected checks at intermediate
  stages; do not run every database test after every stage. The repeated full
  check was stopped at the owner's request before its PostgreSQL partition.
  Full `npm run check` is NOT reported as PASS. Browser E2E, real LBX QA and
  retained later-head database compatibility were not verified in this stage.
- Final documentation and touched-file lint/format/diff checks passed. The
  isolated PostgreSQL server was stopped; retained databases, original branch,
  backup reference and PR #154 were not changed. This stage is one commit on
  `refactor/any715-mvp`; its published SHA and verification are in Draft PR #161.
  Stages 2–6 remain pending.


## Stage 2 evidence — 2026-11-05

- Payment Widget and bound advance now use the existing subscription
  claim/read/apply orchestration, also used by worker/operator reconciliation.
  Its small result carries the subject, proof and observation ID only after
  apply commits. Removed the bound preparation/rebinding route and its obsolete
  verification flags; first binding and unknown-outcome recovery remain Stage 3.
- Subscription leases commit before point reads. Apply additionally validates
  financial-operation states/fences. Busy/stale user attempts return existing
  retryable `purchase_pending` without unclaimed GETs, duplicate CREATEs or
  replacement preparation observations. No alternative projection writer,
  readback protocol, schema or HTTP contract was added.
- Payment requires committed complete identity/commercial proof, supported
  nonterminal lifecycle and the combined final admission after Client readiness.
  Waiting/blocked remains payable; incomplete/ended cannot return credentials.
  Account-only Widget remains independent. Bound HTTP budgets preserve timely
  negatives through optional policy expiry; all source calls and final
  credential admission retain absolute deadline checks.
- Customer conflicts atomically restrict all linked subscriptions; financial
  conflicts restrict only their purchase. Both invalidate source leases/fences,
  preserving historical source timestamps and preventing an earlier ACTIVE
  proof from regaining validity after customer/operator restoration.
- Own subscription queue claims alone may finish their work. HTTP/operator
  applies preserve another owner's lease/hints. Inventory-origin apply validates
  its current customer claim but leaves that job to its existing inventory owner;
  inventory routing/classification changes remain Stage 4.
- SIMULATED LBX verification on the worktree's disposable PostgreSQL: 18 new
  bound-path cases and 41 selected existing regressions passed (59 total).
  Covered actual HTTP payment/advance, worker/operator, lease contention and
  expiry, stale ACTIVE versus later negative/restore, product/customer scope,
  final admission races, inventory queue ownership/hints, failed commit and
  cancellation with finite-lease retry. Two affected fast suites passed 107
  tests. Touched-file Ruff lint/format, architecture and documentation checks,
  and `git diff --check` passed.
- Only selected affected tests were run, per owner preference. Full check/DB
  suite, browser E2E, live LBX and retained later-head data compatibility remain
  unverified. No generated contract change was needed. Updated the existing
  runbook/index; stopped only this worktree's isolated test server. Publication
  is one normal commit/push to `refactor/any715-mvp` and a progress-body update to
  Draft PR #161; its body records the exact tested/published SHA. PR #154 and
  the original branch remain preserved. Stages 3–6 remain pending.


## Stage 3 evidence — 2026-11-05

- Reproduced the lost-reply terminal-original failure: complete original
  subscription proof still left the operation UNKNOWN. Advance, worker and
  operator now share one GET-only collector in `composition/purchase_recovery.py`.
  Saved command/key/date, actual possible-send history, dedicated agreement,
  candidate discovery, customer ownership and accepted effective terms are
  checked before first binding. Operator points are read once and normalized
  once; the same original proof feeds authorization, binding and atomic audit.
- The existing binder checks original request digest, operation/customer
  fences, current review, source times and queue ownership. First binding of
  a proved ended subscription or closed agreement preserves its historical
  relationship and known negative in that transaction. Supported negatives are
  BLOCKED; otherwise initial financial status is UNVERIFIED. All new bindings
  have zero positive trust, and waiting creation needs no invented paid dates.
- `domains/purchases/preparation.py` replaces the old binder's initial-facts
  branch inside that same transaction; it cannot update an existing canonical
  subscription. Prepared evidence includes the redacted original proof. A
  closed original agreement is retained in product-scoped
  `prepared-agreement:v1` history; advance and the locked financial claim block
  a new subscription POST even if a later point read changes that closure.
- Removed bound-object re-observation/rebinding. A concurrent first binder
  discards the losing candidate proof and reloads through claimed subscription
  reconciliation. Recovery of an already bound financial operation, including
  one placed in review, performs no source reads; leftover jobs finish without
  reopening uncertain recovery. Customer recovery retains its distinct rules.
- Preserved GET-only UNKNOWN, typed proven-unsent explicit continuation/C4,
  immutable accepted/request/deadline history, original holds, deadline-only
  automatic resolution and audited handling of real conflicts. No arbitrary
  provider ID adoption, paid grant, schema/HTTP change or generated edit.
- Production-caller search found no CLI/runtime consumer of the separate
  `escalate_overdue_financial` scanner or its query. Removed both; tests use the
  existing durable deadline claim/apply owner. The legacy NULL-active-window
  migration scenario now verifies enrollment at the retained original deadline.
- SIMULATED LBX + disposable PostgreSQL: 9 new original-recovery cases and 55
  selected existing regressions passed (64 unique scenarios across targeted
  runs). Coverage includes lost/ambiguous replies, delayed discovery, terminal
  originals/closed agreements, first-bind races/rollback, original-history
  refusal, operator single-read proof/audit/refusals, deadline-only/C4 recovery,
  sibling preparation, queue completion and Stage 2 caller regressions.
  Two affected fast suites passed 107 tests. Final touched-file Ruff
  lint/format, architecture, docs and diff checks passed.
- Per owner preference, no full check/DB suite was run. Browser E2E, live LBX,
  retained later-head data compatibility and final rebuild QA remain unverified.
  The isolated test server was stopped. One normal commit/push updates
  `refactor/any715-mvp` and Draft PR #161; the exact tested/published SHA is in
  that PR body. Original branch/backup/PR #154 remain preserved. Stages 4–6
  were not executed.


## Stage 4 evidence — 2026-11-05

- Replaced the separate pre-send/background inventory loops and sibling lookup
  with `composition/purchase_inventory.py`; removed the unused agreement-purchase
  query after checking all callers. Admission, worker and both existing
  operator actions use the same bounded discovery, stable re-list and scoped
  candidate classification. Permanent original bindings identify known products
  even during review; a sibling's term conflict remains its own reconciliation
  case, including when a paid-cycle calendar is incomplete.
- Known subscriptions claim their existing lease before point reads and use the
  shared Stage 2 normalizer/apply. Each observation commits independently and
  returns its own committed purchase version. Busy leases make inventory
  incomplete; timely blocks/ends survive later incomplete discovery. An
  inventory-origin apply validates its customer claim without finishing it;
  only the customer inventory apply finishes that job.
- A proved original UNKNOWN/possible-send or deadline-only candidate waits for
  Stage 3 recovery. Later competitors are still checked. Closed agreements and
  terminal subscriptions are not live competitors. No inventory path binds a
  candidate, releases an uncertain hold or schedules a financial POST.
- Competitors before send rotate unsent admission fences under the existing user
  lock without replacing PENDING/PROVEN_NOT_SENT or original request/deadline
  history with permanent review. An explicit advance after correction resumes
  the same purchase/operations. Locked send/apply/resolve transactions recheck
  every local purchase/operation version used by inventory; newly added holds
  or unexpected concurrent changes require a fresh attempt. Customer identity
  conflicts retain the existing customer-wide refusal and send restriction.
- Extended restore-original/bind-original for the exact evidenced inventory
  cases created by this implementation. Restore claims the target once, reuses
  its reads through the inventory scan and commits facts/case/audit together.
  Bind accepts its own pending candidate only with the saved-original proof.
  Evidence-linked related inventory/canonical/deadline cases resolve atomically;
  unrelated reviews remain open/refused. The audit records inventory scope,
  pending originals, principal, expected versions and normalized original proof.
  Sibling negatives can commit without resolving the target or sibling review.
- Added 15 SIMULATED-LBX/disposable-PostgreSQL scenarios for these boundaries.
  Updated existing tests to assert retryable unsent admission, permanent binding
  isolation, leased read sets, independently committed negatives and stale
  refusal rather than the removed caches/permanent unsent review. Existing
  command/history/hold/financial-POST assertions remain; unsent continuation now
  explicitly checks immutable history and changed admission fences.
- SIMULATED LBX + isolated PostgreSQL: 115 selected scenarios passed; the
  post-edit focused rerun passed 30 scenarios, including two additional cases
  (117 unique selected PostgreSQL scenarios across targeted runs). Cabinet
  listing/pagination/user-isolation regressions are included. Four focused fast
  suites passed 121 tests. Touched-file Ruff lint/format, architecture, docs and
  diff checks passed. Exact tested/published SHA is recorded in Draft PR #161.
  No full DB suite/check, live LBX, browser E2E or retained-data compatibility
  validation is claimed. The isolated test server was stopped before handoff.
- Only Stage 4 is delivered. Worker retry acknowledgement/priority/timeout,
  optional receiver removal and final rebuild QA remain Stages 5–6. No migration,
  HTTP/generated contract, paid grant, legal/specification or Kernel change.
