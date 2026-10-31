# 0006. Preserve billing baselines and recognize the ANY-709 ticket decisions

Status: accepted
Date: 2026-10-31

## Context

ANY-709 changed linking, account viewing and recovery behavior. Editing accepted
specification bodies alongside implementation obscured the difference between
an approved contract change and a defect in its implementation. The owner
instructed restoration of the baselines in a separate commit and recording the
actual choices, reasons and limits in ANY-504/ANY-709.

## Decision

- Preserve the [September billing design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md)
  and [October live-source amendment](../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
  byte-for-byte from PR #150 base `ace7c277bbfda46e295fc9651d83e6a3a8fd1787`.
  The [Portal-Kernel baseline](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  is unchanged. Their original accepted content remains reviewable.
- Recognize only **C1-C4 in "Accepted ANY-709 contract decisions — 2026-10-31"**
  in [ANY-504](https://linear.app/paveldik/issue/ANY-504) as the dated, narrowly
  scoped exceptions. That section owns before/after, rationale, exact
  supersession, preserved invariants and evidence limits. Apply it before the
  affected baseline clauses; all other clauses and [ADR 0005](0005-external-billing-boundary.md)
  ownership remain authoritative.
- [ANY-709](https://linear.app/paveldik/issue/ANY-709), section
  **"ANY-709 result and contract deviations — 2026-10-31"**, owns the delivered
  behavior, review-fix outcomes and verification. It references the ANY-504
  decisions instead of creating another version of the contract.
- Ordinary issue text, comments, execution plans, passing tests and completion
  checkboxes do not introduce further exceptions. A new contract change needs
  an explicit dated decision with its scope and retained guarantees.

## Scope of the recognized decisions

- **C1:** direct audited product links, source-backed discovery/current offers
  and immutable accepted purchases replace mandatory approval files,
  approved-price browsing and price-republication requirements.
- **C2:** independently proven customer account viewing does not require a
  purchase/subscription. Purchase/payment presentation retains its own exact
  acceptance, ownership and effective-term verification.
- **C3:** the existing bounded customer retry policy is a conditional departure
  from customer UNKNOWN read-only recovery. Remote duplicate prevention depends
  on LBX email-uniqueness enforcement; a local fence or empty listing is not
  proof of no earlier side effect. There is no agreement/subscription UNKNOWN
  retry exception or new exactly-once/provider PASS claim.
- **C4:** a genuinely new explicit attempt after completed PROVEN_NOT_SENT proof
  receives a fixed active recovery window without rewriting the original
  operation history. GETs do not renew it; UNKNOWN does not authorize a send.

The exact replaced clauses and qualifications are in the ANY-504 entries, not
inferred from these navigation summaries. The original canonical user_id/key
restoration path is retained; the removed blanket conflict refusal is not a
new decision. Provider ownership, paid-access authority, LKG trust, AccessSnapshot,
Kernel wire/quota, legal text, contours and completed Step 6 history are unchanged.

## Consequences

Baseline diffs no longer hide contract choices. The accepted differences are
explicit and reviewable in the program ticket; implementation evidence cannot
silently weaken them. Current behavior remains described by
[ARCHITECTURE](../../../ARCHITECTURE.md) and the
[ANY-709 runbook](../../engineering/ANY-709-billing-runbook.md).
This documentation change supplies no provider guarantee or runtime repair.
