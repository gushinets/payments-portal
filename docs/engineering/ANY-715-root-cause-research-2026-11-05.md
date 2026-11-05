# ANY-715: source interpretation, readback effects and recovery research

Status: research report for independent review; not an accepted specification or implementation plan
Date: 2026-11-05
Issue: [ANY-715](https://linear.app/paveldik/issue/ANY-715)
Parent: [ANY-504](https://linear.app/paveldik/issue/ANY-504)
PR: [#154](https://github.com/gushinets/payments-portal/pull/154)

## 1. Verified basis and conclusion

The working branch and GitHub PR head are both
`3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`. The base/merge-base is
`43943644d277244e8838a693f0d55348d202d7e5`. The working tree was clean before
research. Runtime code, accepted specifications, Git refs, the index, external
tickets and application databases were not changed. Diagnostic code runs in a
temporary archive of this head, against pytest-owned disposable PostgreSQL.

The recommended change is a bounded repair of interpretation and readback
effects, retaining the existing async HTTP client, synchronous resource-owning
transactions, durable worker, GET-only financial recovery and polling-only mode.
It requires neither a new scheduler nor a new financial state machine.

The common causes are:

1. Exception-first effective-term checking discards completeness information as
   soon as it encounters a difference. The normalizer subsequently equates that
   exception with a complete material reconstruction.
2. Preparation admission, proof of the original CREATE outcome and ongoing
   lifecycle interpretation share context-sensitive helpers. Ordinary terminal
   state is even a subclass of an identity/scope mismatch.
3. Readback has no explicit, shared effect for an independently sufficient
   negative fact. Depending on the caller, it is dropped, retained only as a
   binding observation, or turned into an urgent hint. A hint does not fence an
   already-read ACTIVE proof.
4. Failed reads of BOUND objects still reopen CREATE-recovery work. Its worker
   deliberately completes BOUND jobs without reading LBX. That is an unnecessary
   queue round trip, not subscription reconciliation.
5. Tests and review fixes predominantly exercised individual entrypoints and
   final states. Some tests strengthened a lower-priority interpretation rather
   than checking the accepted completeness contract.

The product result is proportionate: independent monitoring/recovery after the
browser closes, bounded source trust, safe uncertain-CREATE recovery and a small
audited operator path. The parent explicitly retains accepted purchases,
dedicated agreements, owner/effective-term checks and duplicate prevention.
Removing those guarantees would change the product. An optional webhook receiver
can be deferred independently; deleting it does not fix these causes.

### Sources and precedence

Read or reused at the unchanged head:

- Root/API/docs `AGENTS.md`, [workflow](AGENT_WORKFLOW.md),
  [conventions](CODING_CONVENTIONS.md), [architecture](../../ARCHITECTURE.md).
- [ADR 0005](../architecture/decisions/0005-external-billing-boundary.md),
  including its 2026-11-01 point-resource selection assumption.
- [External-billing baseline](../superpowers/specs/2026-09-15-external-billing-boundary-design.md),
  especially the mandatory completeness table, canonical binding, terminal
  lifecycle, finite LKG and trust sections.
- [Portal-Kernel baseline](../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  and [live-source amendment](../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md).
- ANY-504: current goal, dated C1-C4, Step 8 and non-goals. Its description was
  unchanged since the preceding audit; API `updatedAt` was
  `2026-11-04T02:31:27.504Z`.
- ANY-715: scope, owner financial-truth decision, invariants, deferrals and DoD;
  unchanged description, API `updatedAt` `2026-11-04T13:40:12.298Z`.
- All accessible issue comments (one on each ticket; no further pages), 13 PR
  review threads, the PR timeline and relevant fixes; refreshed at this head.
- [Completed implementation record](../exec-plans/completed/ANY-715-implementation-plan.md)
  and [operations guide](billing-background-operations.md): implementation
  evidence, not permission to override the baseline.
- [Integration map](../integrations/platform-kernel.md) and the actual downstream
  ANY-765 branch described in section 8.

C1-C4 are precise exceptions. They do not replace the mandatory commercial
completeness table. The implementation plan's statement about decisive negative
evidence is not authority to label a partial material reconstruction complete.
Tests, ordinary review replies and a green CI run cannot introduce that exception.

## 2. Review history and correction of earlier conclusions

| History | What it establishes |
| --- | --- |
| Committed refusal vs worker failure, then the same acknowledgement omission in recovery/inventory wrappers | A result/commit contract was fixed at one caller before its other callers were covered. |
| Inventory conflict resolution, urgency and unsent admission fixes | Safe refusal alone was insufficient: the original workflow also needed a reachable, audited recovery path and correct queue routing. |
| Customer conflict, terminal blocking codes, terminal recovery and closed-agreement inventory | Different paths interpreted the same owned source lifecycle differently. These were real defects, not evidence that lifecycle monitoring is unnecessary. |
| Terminal Widget refusal after terminal recovery was corrected | The early exception path still skipped the common readback effect. |
| Partial policy contradiction, then missing currency mapping | Difference, local interpretability and material completeness were conflated. |
| Cross-contour shared-database P1 | [Retracted](https://github.com/gushinets/payments-portal/pull/154#discussion_r4452322766): its setup violated the supported isolated data-plane contract. No new cross-contour runtime should be added for it. |
| Point-response self-ID P1 | [Retracted](https://github.com/gushinets/payments-portal/pull/154#discussion_r4470161620): it contradicted the accepted canonical point-URL assumption. Relationship, owner and discovery checks remain required. |

Corrections to the preceding research:

- The two original P1s are confirmed, including a valid but changed numeric local
  currency ID, not just a syntactically invalid ID.
- The earlier suggestion to preserve an urgent hint is necessary for hint-only
  evidence, but insufficient for an independently authoritative negative fact.
  New tests show the old ACTIVE apply still succeeds even when `/advance` has
  already bumped generation. Its subsequent urgent reread does work; the
  intervening positive projection is the unresolved part.
- The old test named `unknown_recovery` used `synthetic_prepare(uncertain=True)`.
  That leaves POSSIBLE_SEND, not UNKNOWN, and does not save a receipt. It was
  useful evidence for that path only. New tests explicitly establish UNKNOWN
  through `financial_pending()` and save a receipt through `record_receipt()`.
- The redundant-recovery test characterizes current behavior. Its PASS does not
  certify that behavior as desirable.
- Unknown lifecycle codes are an inherited Step 7/8 boundary inconsistency;
  not every related issue was introduced by ANY-715.
- A blanket immediate restriction or permanent commercial review based solely
  on `INCOMPLETE + known difference` must not be smuggled into this repair. The
  recommendation below preserves the baseline LKG rule and handles independently
  sufficient lifecycle/identity negatives separately.

## 3. Confirmed problems and evidence

| ID / scenario | Cause and source | Evidence | Consequence |
| --- | --- | --- | --- |
| P1-1: local currency configuration changes; LBX facts do not | [normalizer](../../apps/api/app/integrations/lbx/reconciliation.py), `normalize_subscription`, mapping/contradiction branches | Five-prior-state matrix, both `abc` and valid `2`; connection readiness still succeeds | COMPLETE_MISMATCH/complete evidence, blocked/ineligible projection and persistent commercial review caused by local configuration. |
| P1-2: terminal payment Widget read while an old ACTIVE proof exists | [recovery](../../apps/api/app/composition/purchase_recovery.py), `_recover_one` terminal exception | Both ended and closed; exact queue claim and old apply; no urgent claim available afterward | Positive facts remain, old apply is accepted, normal follow-up stays about 13 minutes away in these runs. |
| F-03: changed price plus missing total/period, or contradicted policy plus another missing field | [effective terms](../../apps/api/app/integrations/lbx/financial.py), `prove_effective_terms`; normalizer `commercial != INCOMPLETE` test for `complete` | 55-case persisted matrix; each partial-difference case emits COMPLETE_MISMATCH and `complete=True` | Lost completeness evidence and sticky review inconsistent with the mandatory baseline classification. No paid grant was observed in Step 8. |
| F-04: unknown state/block code in preparation/recovery | `prove_subscription` raises LbxScopeMismatch; reconciliation records lifecycle_unknown | Earlier bound Widget probes; new true UNKNOWN probes with/without receipt | A normalization error becomes financial_binding_conflict and MANUAL_REVIEW instead of incomplete proof/retry. |
| F-05: ordinary negative nonterminal readback | [financial writer](../../apps/api/app/domains/purchases/financial.py), `_bind_financial`, enrolls only new/terminal observations | Earlier block 1, block 3 and inactive Widget probes | Fresh negative information leaves prior positive facts and no urgent follow-up. Payment presentation itself can legitimately remain available. |
| F-06: terminal item seen in inventory | [inventory](../../apps/api/app/composition/purchases.py), `_inventory`, skips terminal/own competition; current inventory result carries no lifecycle effect | Earlier ended/closed inventory probes | A useful scoped hint is lost. The current inventory proof is not automatically a complete owner/seller/material proof for every item. |
| F-07: BOUND read fails and reopens CREATE-recovery | `financial_pending` BOUND branch; [worker dispatcher](../../apps/api/app/composition/billing_background.py), `recover_operation` BOUND fast path | Original redundant-cycle probe; new exact-claim cleanup tests | Recovery job is reopened then completed without LBX; subscription reconciliation remains unchanged. |

The old probes checking only absence of review, generation or successful `tick`
are not treated as proof of the entire desired result. Their narrower findings
are supported by source inspection and the strengthened scenarios below.

## 4. Commercial classifications and Application effects

### Independent conclusions

Material completeness must be computed independently of known differences.
`prove_effective_terms()` currently raises on a difference before discovering
missing fields; `normalize_subscription()` therefore cannot recover both facts.
A small pure term-inspection result should retain both. The existing
CommercialProof and reason tuple can still express the public internal outcome:

- Full required material reconstruction, no differences: COMPLETE_MATCH.
- Full reconstruction, actual material difference: COMPLETE_MISMATCH.
- Missing/unknown material, money interpretation or applicable policy evidence:
  INCOMPLETE, with separately retained known-difference reasons if present.

Identity conflicts and owned lifecycle negatives have their own proof predicates.
An INCOMPLETE commercial result does not erase a separately proven block/end or
customer identity conflict. Conversely, a partial commercial difference is not
silently promoted into one of those independent predicates.

### Input matrix

Each current result below was observed in PostgreSQL for all five priors, not
only in a unit normalizer. All cases use the same original accepted purchase.

| Input | Current commercial / `complete` | Contract result and effect |
| --- | --- | --- |
| Effective unit price differs; total absent | COMPLETE_MISMATCH / true | INCOMPLETE + known price difference; no new positive trust or permanent mismatch review from this partial proof alone. |
| Effective unit price differs; period length absent | COMPLETE_MISMATCH / true | Same; missing period is not reconstructed from the accepted snapshot. |
| `balance_blocks=0`, `dynamic_rent` absent | COMPLETE_MISMATCH / true | INCOMPLETE + known policy difference; do not claim full applicable-policy reconstruction. |
| Local currency mapping absent/invalid | COMPLETE_MISMATCH / true | INCOMPLETE with local mapping reason, not provider commercial conflict. |
| Configured numeric ID changes from 1 to valid 2; source remains 1/RUB | COMPLETE_MISMATCH / true | INCOMPLETE: the current local mapping does not interpret the observed source currency ID. |
| Complete effective price change, coherent supplied total | COMPLETE_MISMATCH / true | COMPLETE_MISMATCH; deny affected usability and create the scoped commercial review. |
| Complete supplied currency contradiction (`USD` vs accepted RUB) | COMPLETE_MISMATCH / true | COMPLETE_MISMATCH only when the source currency meaning and all other required material facts are established; this test is synthetic, not live non-RUB conformance. |
| Complete changed component identity/composition | COMPLETE_MISMATCH / true | COMPLETE_MISMATCH; do not weaken original accepted component checks. |
| Full known unsupported prepaid-policy proof | COMPLETE_MISMATCH / true | COMPLETE_MISMATCH; retain the real restriction/review. |
| Missing total only | INCOMPLETE / false | INCOMPLETE; finite LKG only. |
| Complete match | COMPLETE_MATCH / true | Eligible for the existing full reconciliation decision, subject to identity/lifecycle/calendar/review gates. |

A numeric policy currency ID differing from local configuration is not by itself
proof of another ISO currency. There is no immutable independently accepted
provider-currency ID in the current offer money value that could disambiguate a
bad local remapping from provider change. Do not solve this by inventing another
catalog, a currency mirror or a history migration. Fail interpretation as
INCOMPLETE. An independently established actual currency contradiction must still
be retained; mapping failure cannot turn it into a guessed match.

The USD-symbol probe characterizes the existing comparator under a supplied
meaning; it does not independently prove that an arbitrary provider symbol is a
canonical ISO/scale fact. An unrecognized symbol/ID without a validated money
interpretation remains INCOMPLETE. For a fully proved currency-change control,
the future test must supply that validated account-scoped interpretation as well
as the changed effective currency. No live non-RUB or account-configuration
conformance was established by this research.

Do not fix this by broadening connection readiness to all purchase prerequisites
or disabling the whole worker when mapping is missing. Provider-free deadlines
and safe original-object recovery must remain available; positive source proof
simply remains incomplete until its actual money/policy interpretation is proven.

### Five-prior-state consequence table

The table describes the recommended baseline behavior for a current, owned,
timely proof. "Usable" below concerns Step 8 facts for later paid derivation;
Step 8 itself grants nothing.

| Prior | INCOMPLETE, including known commercial difference alone | Complete matching positive proof | COMPLETE_MISMATCH | Independently proven owned negative |
| --- | --- | --- | --- | --- |
| First check; no positive history | Remain unverified/unusable; record reason; urgent retry | Establish facts and finite trust only through full reconcile | Ineligible/blocked; scoped review | Restrict now; no positive trust; no lifecycle-only commercial review |
| Previously allowed, inside old trust | Preserve previous supporting facts and their original finite deadline; no extension; urgent retry | Refresh within existing rules | Restrict now and review; old trust timestamps are not a new permission | Restrict now; fence older positive apply |
| Previously blocked | Stay blocked; incomplete data cannot unblock | May unblock only from full current proof and without real review/terminal revival | Remain unusable and review | Stay negative; preserve monotonic terminal rule |
| Expired trust | Remain unusable by the old deadline, even if stored financial tag is ALLOWED; no grace interval | Fresh full proof may establish new trust | Unusable and review | Unusable immediately; no trust extension |
| Existing genuine open review | Keep review and denial; no automatic resolution | Ordinary polling still does not clear review or refresh positive trust | Keep/add only justified scoped evidence | Keep denial; do not erase unrelated reviews |

Preserving finite LKG for INCOMPLETE is not issuing a new grant, minting a new
payment credential from insufficient required payment proof, or postponing a
known independent financial/identity negative. The baseline explicitly allows a
known material difference to accompany INCOMPLETE and defines complete mismatch
separately. A stronger blanket policy of revoking/creating persistent review on
any partial commercial difference would be a new policy, not part of this repair.

Current evidence differs from this table for the first five input rows: all five
priors enter/retain commercial mismatch review and blocked/ineligible facts.
Trust timestamps are not extended, but merely preserving timestamps does not
make that false review correct. The missing-only control correctly preserves
bounded prior facts, including an existing block/review.

Completeness also affects queue semantics: processed receipt markers, proof
telemetry and last verified proof must not turn partial evidence into successful
positive verification. A committed incomplete attempt may finish that attempt
and reschedule urgently; it must not consume a newer generation.

## 5. Calling paths and proof authority

| Path / functions | Evidence and current behavior | Required effect and next work |
| --- | --- | --- |
| Account-only Widget: `bootstrap_account` / customer proof | C2 customer identity/readiness/session proof; no purchase | Preserve independence from product availability, paid state, accepted offer and subscription proof. |
| Purchase Widget: `verify_payment_purchase` -> `_prepare` -> `_recover_one` | Fresh original customer, agreement owner/seller/key and subscription effective-term proof. Terminal exception returns 409 early. Nonterminal blocking can still mint payment presentation. | Keep fresh payment-specific proof and final session/fence checks. Apply a sufficient owned negative and its follow-up before terminal refusal. A financial block/unpaid state must not require ALLOWED as a prerequisite to payment. |
| `/advance`: `advance_purchase` -> `_prepare` | Reobserves bound objects; may claim a genuinely permitted unsent CREATE only after current admission. Terminal readback saves binding evidence/hint, without reducing positive facts. | Separate binding/outcome proof from send/payment admission. Preserve terminal original outcome; no new CREATE under closed agreement; apply sufficient negative facts for already bound subjects. |
| Readback after CREATE: `_prepare` -> `record_receipt` -> `_recover_one` | Receipt is a candidate until point proof; binding appends preparation evidence and enrolls the new subscription. | Bind only the original proven result, preserving request/key/consent/history. Preparation is never positive paid proof. Known negative may be recorded in the same binding transaction once a canonical local subscription exists. |
| Uncertain CREATE: `recover_financial` -> `_recover_one` | Customer pair + original agreement + bounded discovery/point proof; no new send authority. Bound operations are skipped by this use case. | POSSIBLE_SEND/UNKNOWN remain GET-only; receipt narrows the original candidate, never grants access. Supported terminal outcomes may bind. Incomplete proof retries; real conflict retains audited review. |
| Full background reconcile: `claim_reconciliation` -> `read_subscription_proof` -> `apply_reconciliation` | Four reads, source lease/fence, independent commercial/lifecycle conclusions and current provenance recheck | Remains the only positive fact/trust confirmation path. Partial evidence cannot be made complete by exception classification. |
| Background/purchase inventory: `_inventory_customer`, `_inventory`, `apply_inventory` | Discovery/point relationships, customer pair and per-candidate checks; terminal/own candidates may skip further agreement/material proof | A terminal foreign/neighbor item must not become the current product's review. For a precisely matched local subject, retain a hint. Apply a negative only if all proof required for that specific negative is actually present. Current successful inventory alone is not full positive subscription proof. |
| Operator inventory: `read_review_inventory` | Bounded stable membership; original ownership/effective terms for relevant nonterminal candidates; terminal exclusion | Preserve competition/isolation proof. Do not resolve a neighbor's review or infer paid state from terminal exclusion. |
| Operator resolutions: `resolve_review`, `prepare_resolution`, `authorize_original_binding`, `authorize_resolution` | Fresh source proof, original possible-send/request evidence, expected digests/fences, audit | Reuse normal original binding or full reconciliation with operator authorization. An incomplete difference cannot satisfy a complete restoration/binding requirement; no direct grant or arbitrary rebind. |

### Hint vs independently sufficient negative

| Observation | Authority and retained proof | Effect |
| --- | --- | --- |
| Callback, authenticated webhook or discovery row alone | Signal only; no authoritative owner/material proof | Durable scoped hint only. |
| Unknown numeric state/block, missing field, timeout, unavailable mapping | Normalization/interpretation incomplete | No invented block/end/conflict. Record safe reason and retry; prior LKG rules apply. |
| Canonical owned subscription is in a supported waiting/inactive/financial/admin block state | Timely point evidence plus original customer-key, canonical bound subscription/agreement relationship and required owner/seller scope checks | Authoritative negative for that original scope; restrict immediately, preserve evidence, invalidate older positive authority and enqueue reread. Missing unrelated commercial material cannot turn it into positive proof. |
| Canonical owned subscription ended | Same original-subject proof, supported terminal code | ENDED/BLOCKED negative; terminal rule applies after authoritative commit; no ordinary commercial review. |
| Original dedicated bound agreement closed | Authenticated canonical agreement point, original customer/key, owner/seller/agreement key, exact permanent local binding and held purchase; source time and local witnesses rechecked | Sufficient to reject use/payment of that original commercial relationship. Record the actual agreement-closure basis and restrict the precisely bound subscription; do not fabricate a complete four-point subscription proof. If no local subscription exists, this is a send-admission restriction and recovery must continue for an already possibly sent child. |
| Terminal item seen by current inventory with skipped seller/original-subject checks | Current evidence has less authority than full readback | Hint for an exactly identified local target; no projection write based on a foreign/insufficiently proven row. Alternatively collect the missing narrow checks before using the common negative transition. |
| Actual owner/key conflict, or fully reconstructed changed commercial terms | Existing independently justified conflict predicates | Keep current restricting/review owners. This research does not relocate all conflict transitions. |

The proof of a negative is proposition-specific. It need not prove paid calendar
or every commercial field, but must prove the intended original subject. A local
binding alone, an unverified candidate, an arbitrary foreign terminal object or a
late response is insufficient. A closed agreement does not authorize rebinding a
subscription which moved to another agreement.

## 6. Queue routing and financial recovery

Routing is decided from current locked state and permanent local relationships,
not from an old caller snapshot or an exception name.

| Current state | Route / completion |
| --- | --- |
| BOUND subscription + exact canonical local subscription | Source uncertainty/negative belongs to subscription reconciliation. Preserve the original completed CREATE evidence; do not reopen its CREATE-recovery row. |
| BOUND agreement, no local subscription | No subscription job can be fabricated. The agreement's completed CREATE needs no recovery. Inspect the child operation: unsent admission, or GET-only child recovery. Closure forbids a new child send. |
| POSSIBLE_SEND | Preserve original financial command/key/fence and active deadline; GET-only discovery/point proof; do not declare no-send from absence. |
| UNKNOWN + saved receipt | Read/prove that original candidate and retained relationships; preserve candidate/request/deadline. No second CREATE. |
| UNKNOWN without receipt | Bounded original-key/agreement discovery, zero/one/multiple handling, point proof; same immutable financial identity/deadline. |
| PENDING | Background does not send. Explicit authenticated advance may claim only after its current preflight. A closed bound agreement stops before child claim. |
| PROVEN_NOT_SENT | Completed typed no-send evidence remains authoritative. Background does not resend or escalate solely because the old deadline passes. Explicit continuation alone may use C4's new fixed active window. |
| MANUAL_REVIEW | Preserve genuine blockers and audit requirements. Deadline-only outcome review may converge through already-supported original GET proof; do not generalize that exception to commercial/identity/inventory conflicts. |

The required combined case is verified with actual UNKNOWN, both with and without
receipt: agreement BOUND and closed, original subscription visible as ended.
GET-only recovery binds the unique original subscription, preserves accepted
terms/key/operation/deadline/hold, sends no financial POST and grants no trust.
The current binder leaves the new local source unverified and enqueues it. The
recommended negative transition can record the proven negative in that same
binding transaction; it must not reject the original result because it cannot
be used for a new payment/CREATE.

Accumulated redundant BOUND recovery jobs can already be drained by the existing
worker's state-rechecked completion, without LBX I/O or rebind. New tests select
the exact recovery claim for both agreement-only and subscription cases. Keep
that compatibility path while stopping creation of new redundant work. Do not
mass-complete POSSIBLE_SEND/UNKNOWN/MANUAL_REVIEW jobs. A supposedly BOUND
subscription lacking its required local relationship is a provenance diagnostic,
not permission for a fresh CREATE or an unbounded discovery repair.

## 7. Recommended bounded solution and concurrency contract

This is the selected design direction, not an implementation sequence.

1. **One interpretation of source facts.** Reuse CommercialProof, existing
   ownership/effective-term concepts and a small Integration-owned lifecycle
   classifier. Inspect required material fields and differences independently.
   Return a supported terminal/blocked result as data, not a scope exception.
   An unknown code remains incomplete. Keep payment/send admission separate from
   proof that the original CREATE has an outcome. A small result/helper is enough;
   no general workflow registry or executor is justified.
2. **One short readback effect for a bound subject.** A shared Application unit
   records the real evidence and schedules the appropriate existing job. If the
   evidence independently proves a negative, it also restricts the precise
   subscription and invalidates older positive authority in the same transaction.
   Hint-only evidence queues work without pretending to have changed facts.
   Existing customer/identity/review restricting owners remain where they are.
3. **One positive owner.** Only the existing full authoritative reconciliation
   may positively confirm facts or renew `projection_valid_until`. The readback
   transition cannot unblock, clear a real review, extend trust, issue grants or
   release holds. Financially blocked/unpaid subscriptions remain payable after
   the required fresh payment proof; terminal relationships remain refused.
4. **Route by state.** Remove the BOUND reopening branch in `financial_pending`
   and the need for terminal-as-conflict special cases in `_recover_one` once
   their responsibilities are covered by the common result/effect. Preserve
   GET-only recovery of uncertain children beneath a closed agreement.

Concrete deletions/consolidations to evaluate in that bounded change:

| Current code | Selected change |
| --- | --- |
| `LbxFinancialEnded(LbxScopeMismatch)` and its `_recover_one` catch exception | Remove terminal-as-conflict from shared proof flow. A strict payment/send adapter refuses a normal terminal result after the necessary committed effect. |
| Repeated numeric lifecycle decisions in `prove_subscription`, `normalize_subscription`, `inventory_terminal` | One small Integration classifier. Keep purpose-specific proof/admission requirements; do not make payment depend on an already paid projection or current-cycle proof. |
| `allow_terminal` switches through financial proof and payment context special cases | Base original-object proof reports supported lifecycle as data. Admission applies its own restriction; uncertainty recovery may bind a proven terminal outcome. |
| `financial_pending` reopens work whenever its operation is BOUND | Stop reopening completed CREATE work; use the bound subject's readback effect. Preserve safe failure diagnostics on the original operation. |
| `new_subscription or observation.terminal` as the only readback scheduling condition | Keep initial enrollment and healthy-read schedule preservation; handle sufficient negative and incomplete/hint outcomes consistently instead of adding another isolated terminal branch. |
| `recover_operation` BOUND completion | Retain temporarily/permanently as a cheap compatibility drain, not as a reason to keep producing redundant jobs. |

This is not a proposal to delete `prove_effective_terms` owner/component checks,
inventory competition filtering, full reconstruction or existing operator
authorization. A shared classifier is not a shared permission to grant/bind/pay.

### Transaction and stale-result requirements

- Capture the original subject and local version before source I/O. Reuse the
  existing customer/operation fences, subscription reconciliation fence and
  supporting observation identity; a small immutable readback subject may carry
  those witnesses. Do not create a second durable version/lease mechanism.
- Release transactions before HTTP. At apply, lock the user first and follow the
  existing bounded business lock discipline, with queue locks last. Recheck
  tenant/region/origin/account, current customer pair and fence, held original
  purchase, immutable accepted/legal evidence, permanent operation/binding and
  the negative's precise subscription/agreement scope.
- Reject expired/late or locally superseded negative results as fact writes.
  In particular, compare the expected subscription fence **and** prior supporting
  observation/version: a newer positive apply may complete without incrementing
  its claim's fence. Fence comparison alone does not prove that a delayed negative
  is newer. A still-correctly-scoped hint may survive a stale fact attempt.
- A sufficient current negative advances the existing subscription fence and
  invalidates the old reconciliation lease/authority. Its old ACTIVE apply must
  fail. The exact handling of lease fields must retain the queue owner's finite
  cleanup/retry path; do not pretend to cancel its still-running HTTP task.
- Coalesce the urgent job with `hint=True` in the same transaction. Generation
  protects that job from an older completion. It is not a substitute for the
  subscription fence and is not proof of available execution capacity.
- Append evidence, projection restriction, fence invalidation and job atomically.
  Commit before raising an expected terminal/payment refusal. Rollback must leave
  all of them unchanged. Failed/uncertain commit acknowledgement must not be
  reported as a normal committed transition.
- Maintain the existing short complete Application units and bounded HTTP/DB
  resource ownership. Cancellation of a waiter is not cancellation of its DB
  commit or HTTP cleanup.

The new race probes characterize both sides: `/advance` commits an urgent hint,
the old ACTIVE apply still succeeds, and the next actual urgent reconciliation
records ENDED/BLOCKED. Widget commits no hint; no urgent claim is available and
only a later normal attempt corrects it. The recommended negative transition must
close the first gap as well as the second. Future tests must also reverse the
order: a stale negative cannot overwrite a newer full proof.

### MVP simplification boundary

| Candidate | Decision and preserved guarantee |
| --- | --- |
| Multiple lifecycle interpretations / terminal-as-scope exception / caller flags | Consolidate interpretation and separate admission. Removes repeated caller exceptions while preserving ordinary ended/blocked behavior. |
| Reopened BOUND CREATE-recovery | Remove production of that work; retain safe drain of old rows. Original create history and no-replay guarantee remain. |
| Full async-to-sync rewrite | Reject for this repair. HTTP is genuinely awaitable, DB/Application units are already synchronous; sync HTTP would not eliminate worker/request/CLI/lease-owner races. |
| Leases, subscription fencing, generation and local/urgent/normal capacity | Retain: each protects a distinct demonstrated property. Existing 62-case controls include cancellation, stale owners and independent local expiry. |
| Optional webhook receiver | Independent scope choice; polling-only is already supported. Deletion is not required to fix root causes and is excluded from the recommended repair. |
| Full operator UI, new queues/tables, generic scheduler, extra source mirrors | Do not add. Current requirements need the narrow audited CLI and existing storage only. |
| Remove consent, owner checks, uncertain-CREATE recovery or same-tariff product isolation | Reject: explicitly retained product guarantees, not equivalent simplifications. |

## 8. Evidence, stored state and downstream compatibility

### Evidence schemas and readers

Restoring commercial completeness can retain `subscription-reconciliation:v1`:
its documented classification meaning already requires complete material proof.
The existing reason tuple can retain a known difference alongside INCOMPLETE.
Do not rewrite historical observations in place or present their old incorrect
`complete=True` as newly verified evidence.

Do not relabel a prepared/binding observation as complete reconciliation merely
to make readers consume it. Preserve `prepared-subscription:v1` and
`financial-terminal:v1` as binding/preparation history. For independently
authoritative readback negatives, use one explicit negative-only evidence shape
(proposed name `bound-source-negative:v1`) identifying its actual agreement or
subscription basis, original local subject, source window and restricting fact.
It must not assert complete positive commercial/calendar proof. This is one
small versioned event format, not a provider framework.

The selected option therefore needs a narrow new negative evidence decoder at
its actual consumers, but no replacement of all existing v1 history. In current
ANY-715, inspect/diagnostics display schema/classification; worker outcome and
deadline-repair queries contain explicit reconciliation-v1 assumptions. Audit
those sites when adding negative-only evidence as a supporting observation.
An existing positive trust deadline remains scheduled; negative readback cannot
create a fresh positive lease. A first negative binding has no positive trust
to schedule or extend.

### Actual Step 9 consumer

Read-only inspection of ANY-765 / [PR #157](https://github.com/gushinets/payments-portal/pull/157)
at local and GitHub-confirmed head
`ff4f4cdbe03678b0f598288876dd563f07b4719e` found real consumers, not just future
designs. Its PR base is `4996a8b51a6779afa5f7ba3e2943021691b5b68b`; it does not
represent a fresh integration of the current ANY-715 head.

| Consumer at that head | Required compatibility |
| --- | --- |
| `domains/billing/paid_policy.py::paid_decision` | INCOMPLETE alone yields KEEP, full match may GRANT, independent negative/review DENY. Restoring classification changes partial-difference decisions intentionally back to baseline; genuine negatives still need explicit DENY evidence. |
| `reconciliation_facts.py::apply_source_facts` / `source_conflict` | Already extracts current fact transitions. Reuse this boundary in the combined implementation rather than inventing an incompatible second state reducer. |
| `paid_access.py::apply_paid_source`, `commit_paid_state` | A new immediate negative path must feed the existing negative paid derivation and commit revision/audit/outbox atomically with source restriction. Updating only ExternalSubscription would leave committed paid state stale. No such writes are to be implemented in this research or moved into bare Step 8. |
| `paid_read.py::_negative` | Explicitly accepts only reconciliation-v1 and reads identity, commercial, financial/lifecycle and read time. Add explicit negative-only evidence support; an unknown new schema currently becomes unavailable display, not proof of confirmed absence. |
| `paid_inventory.py` | Also applies source facts and paid decisions from proof; preserve known owned negative behavior while a neighboring candidate is incomplete. |
| `paid_deadlines.py`, work/deadline queries | Preserve supporting observation relationships and earlier effective deadlines. Do not defer a paid-state reduction to a later GET or source retry. |
| Operator proof/audit and SubscriptionProof extensions | Retain full-proof requirements and Step 9's optional cycle/access-end fields. Negative-only evidence must not satisfy restore/bind complete-proof admission. |

This is a concrete integration requirement for the future refactor, not a claim
that the changed design was run against Step 9 or the real Kernel. No Kernel wire
or shared runtime package change follows from it.

### Physical schema, queues and review history

No DB migration is inherently needed: existing TEXT/JSON evidence fields,
canonical relationships, observation IDs, subscription fencing and queue
generation support the selected change. This depends on retaining their physical
shape; a future implementation choosing extra persisted fields would need its
own migration justification. No public OpenAPI shape change is required by this
research design.

Keep existing work kinds/keys and fixed active UNKNOWN deadlines. Existing BOUND
recovery rows can drain through current locked completion; uncertain/review work
must remain live or explicitly audited. Do not reset source deadlines, financial
request history, original keys, receipts, scope holds or unrelated product work.

False review may already exist under the same reason code as real drift. A
matching poll currently preserves review/denial, as verified in the matrix.
Correcting configuration or normalization therefore does not repair such cases
automatically. Use fresh complete original proof and the existing audited
`restore-original` / eligible `bind-original` path. Old evidence sometimes records
only `unsupported_prepaid_policy`, not enough information to distinguish mapping
error from a real policy change retrospectively. Do not bulk-delete history or
auto-close every `subscription_commercial_mismatch` / `financial_binding_conflict`.

## 9. Verification ledger and acceptance criteria

### Reproduction environment and commands

Host workspace: `/home/wstanley/www/work_unirec/payments-portal`.
Isolated source archive: `/tmp/any715-root-cause-review`, produced by
`git archive 3c69c8de7cbb65c81a0a92b0cf99ff269723fff1`; runtime tracked files match
the inspected source. Extra files there are diagnostic tests only.

The canonical harness supplied `api_test_environment("api-postgres",
canonical_check_environment())`. Child processes use repository `.venv`,
`PYTHONPATH=<archive>:<archive>/apps/api`, and cleared development Kernel origin,
token and mock settings. All provider calls use synthetic transports. No
application/shared DB, real LBX mutation, payment, deployment, branch switch or
push/merge was performed.

Current research commands (the runner logs the expanded pytest command):

```bash
.venv/bin/python scripts/repo.py test-db up
.venv/bin/python /tmp/any715_contract_research_runner.py
.venv/bin/python /tmp/any715_contract_research_runner.py 'real_unknown_receipt or unbound_routing and (POSSIBLE_SEND or MANUAL_REVIEW)' corrected-fixtures
.venv/bin/python /tmp/any715_contract_research_runner.py unknown_codes_with_real_unknown_receipt unknown-codes
.venv/bin/python scripts/repo.py test-db stop
```

The runner invokes:

```text
<repository .venv>/python -m pytest -p no:cacheprovider -m postgres -k <selection> -q -s --tb=short /tmp/any715-root-cause-review/apps/api/tests/test_any715_contract_research_postgres.py
```

Temporary tests/runners/logs are local evidence, not committed runtime or durable
test-suite changes. The scenario descriptions and assertions in this report
remain the handoff if those temporary files are removed.

### Results

| Check | Result and actual scope |
| --- | --- |
| Refreshed source/ticket/PR comparison | Same head and unchanged source requirements; current remote head confirmed through GitHub API. |
| New commercial matrix | 55 PASS: 11 inputs x five priors. Captures actual proof classification/completeness, persisted facts, trust, review, queue metadata and immutable bindings; asserts no Step 9 writes. Characterization PASS does not certify the erroneous partial classifications. |
| New old-ACTIVE/negative races | 4 PASS characterizations: advance/Widget x ended/closed. Check generation, fence, due time, exact next work kind, actual next reconcile and final ENDED/BLOCKED without review. |
| New terminal evidence/enqueue rollback | 1 PASS: injecting enqueue failure rolls back binding evidence, generation and fact changes in that transaction. A future negative transaction still requires its own equivalent test. |
| New closed agreement + PENDING/PROVEN_NOT_SENT advance | 2 PASS: no child CREATE, no new source subscription and unchanged child admission/history. |
| New accumulated BOUND job cleanup | 2 PASS: exact agreement/subscription recovery claim completes with zero LBX reads and unchanged operation snapshot. |
| New ordinary PENDING/PROVEN_NOT_SENT GET-only routing | 2 PASS. |
| Initial new suite | 66 PASS / 6 fixture FAIL: synthetic model_dump included Decimal values not JSON-serializable by the mock transport. These were setup errors, not runtime findings. |
| Corrected six uncertain/review scenarios | 6 PASS / 66 deselected. Four actual UNKNOWN x receipt/closure cases, one POSSIBLE_SEND recovery and one genuine MANUAL_REVIEW refusal. The fixture correction only converts synthetic total/quantity/unit price to JSON-compatible numbers, matching the existing production-test helper. |
| Stronger unknown-code/receipt characterization | 4 PASS / 72 deselected, characterizing the defect: initial enum UNKNOWN is asserted, receipt presence is checked, unknown state/block creates false MANUAL_REVIEW; no binding or POST occurs and original key/deadline/receipt/hold remain. |
| Race-record cross-check | All four records show changed supporting observation and extended trust after the older ACTIVE apply, with unchanged subscription fence; final owned negative is reached through the asserted actual next work kind. |
| Actual ANY-765 pure policy | 4 PASS assertions using the unmodified `paid_policy.py` read from pinned ANY-765: complete positive -> GRANT; INCOMPLETE + known difference -> KEEP; independent negative -> DENY; genuine review -> DENY. This does not execute the combined DB/revision/outbox transition. |
| Prior controls, reused at unchanged head | 62 PASS, log `/tmp/any715-root-cause-controls.log`; cancellation, stale owners, negative/full reconciliation, review restoration and reserved local capacity. Not rerun in this continuation. |
| Earlier diagnostic probes, reused with narrower interpretation | Four original regressions and nine related probes exposed defects. Old POSSIBLE_SEND naming/generation-only/absence-of-review limitations are corrected above; these are not new runs. |
| Earlier redundant BOUND-cycle characterization | 1 PASS, `/tmp/any715-root-cause-diagnostic.log`; proves unnecessary work, not target correctness. |
| Documentation | `PATH="$PWD/.venv/bin:$PATH" npm run docs:check` PASS; whitespace/source-scope checks rerun before handoff. |
| Full canonical suite, browser E2E, Step 9 changed runtime and live LBX | NOT RUN in this research. No runtime change was made; no claim of fixed-code regression PASS or real provider conformance. |

Current logs: `/tmp/any715-contract-research-initial.log`,
`/tmp/any715-contract-research-corrected-fixtures.log`,
`/tmp/any715-contract-research-unknown-codes.log`. Detailed per-scenario
observations: `/tmp/any715-contract-research-results.jsonl`.

There are 76 distinct new PostgreSQL characterizations across these runs, not a
single 76-PASS aggregate run: initial 66 PASS / 6 fixture errors, the corrected six
PASS, then four additional PASS. The 55-case matrix was not rerun after fixing a
different synthetic uncertain-object fixture. All tracked runtime files were
byte-compared between the workspace and archive and were identical.

The final temporary diagnostic source SHA-256 is
`026c4cbd2a6947257e297eb99aab68f3f7549134fc03d6a5d8cabf3fd21ef4c8`;
runner SHA-256 is
`a88008d8ff7591159d713ffc4156c52324803f786a8c57ccc63d3f88dc6f9cdc`.

### Future refactor acceptance

1. All five-prior-state commercial consequences match section 4. Partial
   difference, absent mapping and a changed valid local ID cannot create false
   COMPLETE_MISMATCH/complete evidence or permanent commercial review. Full real
   price/currency/composition/policy differences still restrict and review.
2. Supported negatives have identical meaning across applicable entrypoints;
   unknown codes stay incomplete. Account-only C2 behavior stays independent,
   and unpaid/blocked subscriptions remain payable with fresh required proof.
3. Independently sufficient bound-source negatives restrict atomically before
   expected refusal and fence a previously read ACTIVE result. Hint-only evidence
   preserves a genuinely due urgent follow-up without pretending to forbid apply.
4. Test both source-result orders, lease expiry/reclaim, changed ownership/pins,
   same-tariff neighboring products, rollback and lost commit acknowledgement.
   Stale negative cannot overwrite newer accepted facts; old completion cannot
   consume a newer hint. A successful tick must identify the actual claim kind.
5. True UNKNOWN with/without receipt, and a BOUND closed agreement with uncertain
   terminal child, recover only the original result through GET; no new CREATE,
   no unproven paid trust and no mutated command/key/deadline/hold.
6. New BOUND read failures route to subscription work; old redundant jobs drain
   safely. Genuine MANUAL_REVIEW remains audited; PENDING/PROVEN_NOT_SENT do not
   gain background send permission.
7. Existing evidence remains readable. Any negative-only format has explicit
   readers and cannot pass as positive/complete restoration proof. The combined
   ANY-765 transition commits negative source state and paid revision/outbox in
   the same transaction, preserving frozen allowance/history and product isolation.

### Remaining uncertainty and closure

- The recommended baseline repair requires no new product-policy decision.
  Revocation or persistent review on partial commercial difference alone would
  be a separate stronger policy; do not add it implicitly.
- There is no provider source revision/atomic multi-GET snapshot. Repeating all
  reads or switching to sync cannot manufacture one. Local witnesses/fences
  prevent superseded local writes; live external ordering remains subject to
  the accepted point-resource contract and bounded observation windows.
- Mapping an arbitrary newly observed currency ID to ISO/scale cannot be inferred
  from its number. Close a real deployment's mapping uncertainty with that
  account's authoritative configuration/evidence; until then INCOMPLETE. This
  does not require a new general currency catalog or live financial experiment.
- Negative-only evidence and its local witness guard are a proposed design, not
  implemented or runtime-tested. Their proof obligations and exact consumer
  changes are identified above; implement and run the acceptance scenarios next.
- Step 9 compatibility is a source audit at the pinned open-PR head, not combined
  runtime verification. The future refactor must be integrated with that branch
  and tested at its resulting head, without reopening unrelated Kernel work.

Research ends here: the selected bounded solution, affected entrypoints,
transaction/proof obligations, existing-state treatment and acceptance checks are
defined. Detailed implementation sequencing and runtime edits are the next stage
after independent review of this report.
