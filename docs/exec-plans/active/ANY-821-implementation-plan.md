# ANY-821 — Quiesced terminal resolution rebuild plan

- Owning issue: [ANY-821](https://linear.app/paveldik/issue/ANY-821/implement-quiesced-audited-resolution-for-purchases-stuck-in-unknown)
- Current PR: [ANY-821(#191)](https://github.com/gushinets/payments-portal/pull/191)

## 1. Decision

An operator can conclude a stuck purchase after proving the outcome of both
original financial operations. The decision is audited and releases only that
purchase's hold. The saved link shows the result and lets the customer begin a
new purchase with current terms and fresh consent. An unresolved outcome keeps
the purchase in manual review, retains the hold, and prevents another financial
CREATE.

Terminal purchase resolution and exact late-case closure run during quiesced
maintenance. The operator stops and drains Portal processes and one-off commands
that can affect the customer, obtains final evidence, and keeps the system
quiesced through commit. The commands perform no LBX I/O. Use the existing
billing fences, exact-object cases, and paid-access reducer. The rebuild scope is
the Linear issue and its verification matrix.

## 2. Git recovery point

- Research snapshot: `e804c2983f183c506ccb9cfe0c0886855f791a01`. Preserve it as the
  reference for reproduced defects, fixtures, and individual regressions.
- Reduction source: `3b4985e152e4475fcd47d0ef10b9cc2cf0bc793d`. This includes
  the initial terminal writer, CLI, saved-link flow, exact late-object case, and
  audited-ID and rollback guards. Its predecessor `a54ad1e3` implements the bulk
  of the feature.
- The local `origin/main` was at `550263e644b49baa01d313de32ddaf1db0016b08`
  (ANY-674) when this plan was validated. Verify the current target base at
  implementation time and carry the two reduction commits onto it in a local
  rebuild branch. Preserve any current base changes to the CLI wrapper, checks,
  and deployment tooling.

If the existing PR branch will be rewritten, preserve the research snapshot
first, for example at
`archive/any-821-pr191-online-concurrency-e804c298`. Publishing the archive,
rewriting the remote branch, or updating the PR or Linear requires separate
authorization. Later commits supply targeted regressions and implementation
evidence for the accepted scope.

## 3. Target invariants

The rebuilt code must make these invariants obvious and centralized.

### I1. No blind financial replay

An uncertain original financial CREATE is never repeated. Empty discovery and elapsed time do not authorize another CREATE.

### I2. One complete identity fact

Every retained point fact contains the complete tuple:

```text
operation_kind
external_object_id
fact = open | live
point_read_finished_at
```

A timestamp without an exact ID is invalid history. Freshness is compared using the object point-read completion time, never a later tariff/inventory completion time. Legacy observations may use their enclosing observation time only when the exact point time is absent.

### I3. Quiesced terminal writer

`resolve-purchase` and late-case closure perform no source I/O. They run only after operational stop/drain and refuse active/incompatible local work.

### I4. One atomic decision

Audit, state transition, hold release, fences, invalidation, and paid-access reduction commit together or not at all.

### I5. Historical identity is never adopted by a replacement

An exact provider ID retained in the terminal audit or exact late-object case cannot be first-bound to another purchase.

### I6. Late-object protection is durable and simple

A proven live late object creates or updates one exact `ManualReviewCase`. The case survives later list omission and blocks affected CREATE/first binding/primary selection until exact terminal closure.

### I7. Fail closed outside the model

Ambiguity, active work, stale digest, identity disagreement, unsupported outcome, or incomplete provider proof changes nothing.

## 4. Implementation stages

Use stage checkpoints as local implementation checks. Submit the combined rebuild
for review once it meets the final verification criteria.

## Stage 0 — Prepare the local rebuild base

1. Verify the working tree, research snapshot, reduction source, and target
   `main`. Carry the reduction commits onto the verified target base.
2. Align the repository implementation plan with this plan and the Linear issue
   as part of the rebuild.
3. Run the relevant baseline checks on that base and record known failures
   for use during implementation.

**Checkpoint**

- The rebuild starts from the current target base with the reduction commits.
- The research snapshot remains available.
- The rebuild base has no second migration or case read-token fields.

## Stage 1 — Remove unsupported behavior before adding new code

Make this a subtractive stage.

1. Remove `canonical_binding` as a late-case closure outcome.
2. Remove canonical-observation closure queries and tests used only by that outcome.
3. Keep late-case closure only for definitive `external_terminal` evidence for the exact case ID.
4. Remove code/comments/tests that promise closure while inventory, recovery, reconciliation, or point reads are active.
5. Remove unrelated accessibility/focus refinements from this PR unless required to display the terminal result or avoid opening a Widget for a resolved purchase.
6. Keep the minimum saved-link flow:
   - show `manual_review`;
   - explicit status refresh;
   - show terminal result;
   - link to a fresh purchase with current terms and fresh consent.
7. Do not add replacement persistence while deleting behavior.

**Checkpoint**

- No automatic canonical adoption or closure remains.
- No read reservation/token/deadline exists.
- Existing normal purchase, recovery, reconciliation, and paid-access tests remain green.

## Stage 2 — Unify exact point evidence

Introduce one small typed contract, for example:

```python
class OriginalPointFact(BaseModel):
    operation_id: UUID
    operation_kind: ExternalCreateOperationKind
    external_object_id: ProviderId
    fact: Literal["open", "live"]
    point_read_finished_at: AwareDatetime


class RetainedOriginalPointFacts(BaseModel):
    schema_version: Literal["original-operation-point-facts:v1"]
    primary: OriginalPointFact
    conflict: OriginalPointFact | None = None
```

The final names may follow repository conventions, but the semantics are fixed.

### Storage

Reuse the existing operation recovery work payload. Do not add a table or column. Store one typed nested document per original operation. Keep at most the primary exact ID and one distinct conflict witness; a conflict permanently fails closed until resolved through the existing review workflow.

### Writers

- Agreement recovery records `(agreement, exact ID, open, point GET completion time)` immediately after exact original owner/seller/key/create-date proof.
- Subscription recovery records `(subscription, exact ID, live, point GET completion time)` immediately after exact relationship/effective-term/lifecycle proof and before tariff/policy I/O.
- A newer read of the same ID replaces its time/fact.
- A different ID records conflict and refuses terminal resolution.
- Keep a proven point for the same original send across UNKNOWN, receipt arrival, deadline review, and a concurrent first binding. Verify its retained request, active send window, customer, hold, and work claim. A new send after definitive no-send or an audited choice invalidates the old reader.
- Before first binding, recheck retained identities and receipts under the same locks as the write. A conflicting point blocks ordinary binding even when the proposed object is terminal. Record such a disagreement in the financial review so terminal resolution also sees it. An audited original binding needs fresh point proof covering the conflict it settles.

### Bound subscription observations

Retain exact `agreement_read_finished_at` and `subscription_read_finished_at` in the existing reconciliation/preparation evidence document. Do not add callbacks that write late-purchase state from every integration path. The authoritative apply remains the sole observation writer.

### Reader

`state_digest` and terminal proof validation read the typed evidence by
operation. Retain and validate the exact ID and point-read time together for
both agreement and subscription, including when a later binding attempt fails.

Validate the outcomes of the two original operations independently:

- `not_sent` requires durable proof that the operation was never sent or that
  transport definitively proved no send.
- `external_terminal` requires definitive proof of irreversible termination
  of the exact original provider object. The supplied ID must agree with
  retained bindings, receipts, audit evidence, and authoritative point facts.
- `no_external_effect` after a possible send requires an approved LBX
  operation-level contract proving that the exact request had no effect and
  cannot materialize later. Refuse the outcome while that contract is
  unavailable, even with fresh timestamps. Empty discovery, timeout, recovery
  expiry, and an unqualified 404 leave the outcome unresolved.

Two proven `not_sent` operations can conclude as
`resolved_no_external_effect`. A supported decision containing
`external_terminal` concludes as `resolved_external_terminal`.

**Checkpoint**

- Agreement and subscription evidence use the same typed concept.
- A different evidence ID is rejected for either operation.
- A fresh but unsupported `no_external_effect` claim leaves the hold in place.
- A newer point fact rejects older operator confirmation.
- A late tariff response cannot make an older object GET appear newer.
- No new migration is introduced.

## Stage 3 — Add the quiesced maintenance guard

Create one shared guard used by terminal purchase resolution and late-case closure.

### Locking, replay, and checks

Use the repository lock order and existing advisory-lock utility. Under one
transaction:

1. Lock and verify user, customer, purchase, and billing-account ownership.
2. Check the saved audit for an exact retry by the same principal. Return the
   saved result before checking state required for a new write, including when
   the original hold is gone or a replacement purchase exists.
3. For a new write, acquire the maintenance and relevant exact financial-object
   locks under the business locks. Lock and recheck the applicable hold, original
   operations, subscription, and exact case.
4. Verify the expected digest, identity, bindings, fences, and accepted evidence.
   Use database time to check relevant work claims, live work leases, and live
   reconciliation leases. Return `billing_busy` or the stale-proof error
   without writes if activity or incompatibility is detected.

The operator owns stop/drain and restart. The database guard checks the activity
and freshness visible to the command. For a work row left `running` after
shutdown, use the existing claim and lease rules to establish whether any
writer still has authority. If its state is ambiguous, keep the hold or case and
use the runbook to finish normal recovery, drain again, and obtain fresh proof.

### Commit effects

For purchase resolution, commit the audit, terminal purchase state, release of
the original hold, rotation of its operation and linked-subscription fences,
invalidation of its work and clearing of its work leases, and paid-access
reduction in one transaction.
Preserve the original terms and consent, operation identities, provider
history, allowances, and audit history.

For exact late-case closure, commit that case's closure and audit together.
Preserve the original terminal decision and keep the replacement outside the
write scope.

**Checkpoint**

- Active work or a live lease returns `billing_busy` with zero writes.
- Audit or reducer failure rolls back the full purchase resolution.
- A stale worker cannot commit after successful resolution.
- Exact replay returns the original result after restart and after a replacement
  purchase exists.

## Stage 4 — Reduce late-object handling to one durable case

### Recording

Ordinary customer inventory and GET-only recovery follow the same rules when
they prove that a live object is related to a terminal purchase.

- lock the exact financial object identity;
- create or update one `purchase_late_external_object` case for that exact object on the original purchase;
- store the exact typed point fact plus the minimum relationship needed for product scoping;
- preserve the newest fact for the same ID;
- retain conflict instead of guessing ownership.

If a background worker proves this relationship while recovering another held
purchase, record the case on the terminal purchase before deciding whether the
held purchase can bind the object.

Write an already-proven exact fact once the point response and retained
original relationship establish identity. A later agreement or tariff GET
may still make inventory incomplete. Its failure must leave the proven fact
and exact case intact. List membership, empty results, and incomplete identity
proof are insufficient to open a case.

### Blocking

The open case blocks:

- financial CREATE for the affected product/scope;
- first binding of the exact ID;
- first-primary selection for the affected product.

The case remains open when later discovery omits the object.

### Closure

The only supported closure in this ticket is:

```text
external_terminal(exact ID, confirmed_at)
```

The maintenance guard must pass. Use the exact object's point GET completion
time to veto a confirmation older than the case's latest point fact or a newer
authoritative live/open fact already committed before quiescence, including
when pricing was incomplete. The retired ID remains ineligible for first binding.
A distinct fresh ID may proceed through ordinary admission.

A later contradictory point read after restart creates or updates an open case.

**Checkpoint**

- Proven late live object → one exact open case.
- Proven point read → follow-up GET fails → later list omits ID → case still
  blocks and zero replacement financial CREATEs occur.
- Exact stale confirmation → closure refused.
- Fresh exact terminal proof under quiescence → case closes.
- Distinct fresh ID can proceed; retired exact ID cannot bind.
- Other customer and independent product remain isolated.

## Stage 5 — Complete the customer and operator path

1. Keep `resolved_external_terminal` and Alembic revision `20261123_0821`.
2. Keep `inspect` output required to build evidence safely:
   - operation IDs/kinds/states/fences;
   - request correlation keys;
   - bound/receipt IDs;
   - retained exact point facts/conflict;
   - current expected resolution digest;
   - blocking exact late-case IDs and digests.
3. Keep `resolve-purchase` local-only with bounded evidence file, reason and reference.
4. Update `docs/engineering/billing-background-operations.md` and
   `docs/architecture/deployment.md` with the supported sequence. Stop every
   Portal API/worker replica that can affect the operation, disable automatic
   restart, finish related one-off commands, and keep PostgreSQL available. Use
   a compatible one-off CLI and compatible API, worker, and web images with the
   migrated schema. Keep the downgrade guard for retained terminal history.

```text
inspect
→ attempt GET-only recover
→ inspect again
→ stop and drain affected Portal processes and commands; prevent automatic restart
→ verify no active work or live lease
→ use local proof for each not_sent operation and final LBX confirmation for each external_terminal outcome or exact case closure
→ resolve-purchase / close exact case
→ exact replay if CLI outcome is uncertain
→ restart compatible processes
→ verify saved link and ordinary replacement admission
```

5. Keep the saved-link terminal outcome and fresh consent. Do not add unrelated cabinet redesign.
6. Regenerate contracts and schema documentation through canonical repository commands.

**Checkpoint**

- Operator can execute the documented local procedure without source I/O inside the terminal command.
- Old purchase cannot reopen its Widget.
- New purchase uses current offer/fingerprint/documents and a new idempotency key.
- Web/API generated contracts contain the terminal state and no unrelated wire changes.

## Stage 6 — Verification and final review boundary

Run the verification matrix from the Linear issue on the final revision. Use
existing focused tests and port the targeted regressions from Stage 2 and
Stage 4 into the applicable groups.

### Required focused groups

- terminal evidence validation;
- atomic writer and rollback;
- maintenance guard/active leases;
- exact replay/restart;
- original recovery and no repeated CREATE;
- exact-ID retirement/first-binding restriction;
- late-object case and list omission;
- user/customer/product isolation;
- paid-access reduction/history retention;
- saved-link and fresh-consent customer journey;
- Alembic upgrade/downgrade compatibility for the single terminal-state migration.

### End-to-end evidence

Repeat the [operator-to-replacement scenario from ANY-821(#191)](https://github.com/gushinets/payments-portal/pull/191#pullrequestreview-6025497581)
on the final revision using disposable PostgreSQL, simulated LBX, the actual CLI, and Portal's
HTTP routes and saved purchase link. Prove one existing matrix scenario in
sequence:

1. Simulate a lost agreement CREATE reply. Verify the saved link shows
   `manual_review` for the original purchase.
2. Stop and drain the processes. Supply definitive simulated terminal proof
   for the exact original agreement and durable local `not_sent` evidence
   for the original subscription. Run `resolve-purchase`.
3. Restart compatible processes. Refresh the original link, verify the terminal
   result, and start a distinct purchase using the current offer and fresh
   consent. Verify the old purchase cannot reopen its Widget.

Use the existing matrix to verify refusal when only an empty/failed discovery
or an elapsed deadline is available, rollback, exact replay, and late-case
block and closure. Record the run and the repository's canonical checks on
the final revision in the PR or its verification report. Use `npm run check`
and the repository's documented browser procedure for browser coverage.

### Final review rule

A finding blocks merge when it gives a reachable trace, the violated Linear
criterion or existing guarantee on an affected path, and the concrete
consequence. Supported traces include ordinary recovery before stop/drain,
refusal when the command detects activity, and ordinary inventory/admission
after restart. Propose the smallest in-scope fix when one is known. If a real
blocker calls for a scope change, settle that decision explicitly before
expanding the patch.

Successful closure during an active GET, online coordination, and UI polish
outside the saved-link journey are follow-up work. After a blocker fix, review
the affected behavior and repeat the relevant checks on the final revision.

## 5. File disposition from current PR

### Port/keep

- `apps/api/app/domains/billing/terminal_resolution.py` — rewrite around shared guard and typed exact evidence.
- `apps/api/app/cli/billing_purchases.py` and `scripts/repo.py` — keep narrow CLI.
- terminal purchase enum/model/check migration.
- financial-object advisory lock and exact audited-ID first-binding restriction.
- atomic paid-access reduction/work fencing/replay logic.
- minimal saved-link/terminal-state UI and generated contract.
- focused atomicity, replay, retired-ID, late-case omission and customer-path tests.

### Rewrite smaller

- `purchase_late_objects.py`.
- `late_purchase_reviews.py` and its queries.
- `purchase_inventory.py` integration points.
- original recovery point-evidence retention.
- operator diagnostics and runbooks.
- reconciliation proof timestamps, without late-case callbacks.

### Drop from rebuilt PR

- `20261124_0821_late_case_subscription_read.py`.
- `late_purchase_case_reads.py`.
- `subscription_read_token` / `subscription_read_until` model/schema/docs/tests.
- automatic `canonical_binding` closure.
- `test_billing_terminal_resolution_races_postgres.py` as a wholesale module.
  Retain regressions reachable on the supported paths in focused tests.
- callback chains whose only purpose is to preserve evidence across concurrent terminal closure.
- automatic scans or batch recovery of completed purchases.
- unrelated focus/UI polish.

## 6. Targeted regressions from ANY-821(#191)

- Cover agreement and subscription with the same ID-and-point-time rule. Use
  the [agreement-ID P1](https://github.com/gushinets/payments-portal/pull/191#discussion_r4678000497)
  and its [subscription counterpart](https://github.com/gushinets/payments-portal/pull/191#discussion_r4674822757).
- Retain the [late-object omission regression](https://github.com/gushinets/payments-portal/pull/191#discussion_r4675978760)
  from `c8c5d0cc`. Ordinary inventory first proved a live subscription related
  to the completed purchase, then lost that fact when a follow-up request
  failed. Keep the case and refuse CREATE when discovery later omits the ID.
- Apply the [point-read freshness rule](https://github.com/gushinets/payments-portal/pull/191#discussion_r4678000509)
  to supported `external_terminal` evidence. Keep the `canonical_binding`
  closure path and its overlap regression with the research snapshot.
- Retain a refusal check for active work under the maintenance guard. Keep
  overlap-dependent token, deadline, and cleanup regressions with the research
  snapshot.

## 7. Definition of done

Close ANY-821 when all of the following are true:

1. The final revision of ANY-821(#191) implements the quiesced operator and
   exact late-case closure paths, the minimal saved-link journey, and the
   compatible migration and runbooks. The PR description records this scope.
2. The existing Linear matrix, the single CLI-to-customer run in Stage 6, and
   the applicable canonical repository and CI checks pass on that revision.
3. A human has approved the PR, every reproducible violation on the supported
   paths has been resolved under the final review rule, and the PR is merged.

The local run supplies evidence for the related ANY-767 journey. Remote
deployment and live LBX or production acceptance are tracked through ANY-767.
