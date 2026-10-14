# ANY-634 — LBX Phase 0 evidence and implementation handoff

Status: **research consolidated; final Step 5 architecture-gate PASS NOT YET RECORDED**  
Decision date: 2026-10-14  
Sources: [ANY-634](https://linear.app/paveldik/issue/ANY-634/5-run-lbx-phase-0-validate-widget-and-provider-contract), [ANY-504](https://linear.app/paveldik/issue/ANY-504/realizovat-ru-external-billing-i-paid-access-arhitekturu-lbx-payments), [GitHub #112](https://github.com/gushinets/payments-portal/issues/112).

## Reading this matrix

`CONFIRMED_ON_TEST` means the specific provider behavior was observed on stand 043; `DOCUMENTED` means official LBX documentation; `VENDOR_CONFIRMED` is the vendor's stated contract, not a stand reenactment; `LOCAL_POLICY_CHECK` verifies only our local policy. `DONE` means the independent Phase 0 research was completed, **not** that every originally hypothesized property passed. Never silently upgrade `UNKNOWN`, `NOT_TESTED`, or provider `FAIL`.

| Probe | Research disposition | Supported facts, limits and owner |
| --- | --- | --- |
| B1 Server auth/read/create | **PASS / CONFIRMED_ON_TEST** | Server auth expiry and reauth, non-payment create and point reread. POST subscription may return 200 despite Swagger 201. LBX client: Step 6. |
| B2 Widget identity | **PASS / CONFIRMED_ON_TEST** | Historical type-6 lookup and real Widget type-7 authenticated GET. Production **only** `ident_type=7` with bound LBX `users.user_id`; Step 7. |
| B3 `outer_id` reuse | **Research DONE; original type-6 provider FAIL** | Reassignment allowed an old type-6 JWT to resolve another customer; type-7 selected. Immutable Portal key still checked against `users.outer_id`; conflict fails closed. Steps 7-8. |
| B4 Widget JWT | **Research DONE; original 900s criterion FAIL** | `exp` ignored; remint does not revoke. LBX vendor confirmed 72h from `iat`, including backdating; real Widget type-7 checks support age rule. MVP uses fresh `iat=now`, not backdating. **Explicit residual-token-risk/security approval before Widget enablement.** |
| B5 Client API ACL | **Research DONE / Provider FAIL / other mutations UNKNOWN** | Client JWT could mutate own `outer_id`; cross-customer subscription GET denied. Service/quantity/payment/top-up/autopay server-side mutation authorization **not proven**; UI flags not ACLs. **Security/provider decision before unsafe Widget flow enablement**; Step 6 fixed-offer config, Steps 7-9 fail-closed. |
| B6 Dedicated agreement | **PASS / CONFIRMED_ON_TEST for integration scope** | Agreement separation, funding isolation and intended activation. Do not infer complete provider-owned autopay/cancellation coverage. Steps 7-9. |
| B7 Subscription/version | **Research DONE / partial provider PASS** | Canonical subscription binding and tested version/read facts; ended-to-active revival and all historical transitions not established. Unexpected revival/agreement change → fail-closed/manual review, Step 8. |
| B8 Pricing and accepted terms | **Research DONE; B8.3 PASS; B8.2 DOCUMENTED replacement** | Prices on tariff services and effective subscription services, not an independent tariff base price; operator-specific effective 10→15→10 observed without instance change. Catalog source-price mutation **NOT_TESTED**, intentionally no longer Phase 0 requirement. Complete material accepted snapshot, historical provenance and currency/profile sellability tests Steps 6-8. Included in the same consolidated PR, in the canonical Phase 0 B service-price section. |
| B9 Fixed quota | **Research DONE / partially CONFIRMED_ON_TEST + DOCUMENTED** | LBX `multiplicator=1.0` = one commercial service unit, not 1000 operations. Fixed periodic non-bulk service needs no usage upload. Commercial `component → metric → immutable fixed quantity` is Step 6 admission work, Kernel owns usage. |
| B10 Cycle identity | **Research DONE / documented calendar model accepted; natural-renewal mechanism NOT TEST-CONFIRMED** | Repeated same-period read and adjacent charges observed; no native cycle ID or verified LBX timezone/UTC instants. Preserve LBX calendar dates inside Portal; no made-up UTC start/end; edits/recalculation not new cycles. Steps 8-9 implement fail-closed cycle proof. Coupled persistence/Kernel wire redesign **assigned Step 10**, not this PR. |
| B11 Prepaid eligibility | **Research DONE / DOCUMENTED_ACCEPTED + partial CONFIRMED_ON_TEST** | S22 waiting unpaid then funded 15 RUB/charged 10/balance 5 and ACTIVE; historical financial block observed elsewhere. S22 **manually blocked 2026-10-13**, so natural unpaid renewal **NOT TEST-CONFIRMED**. Required untouched real renewal and provider→Portal→Kernel E2E before paid access enablement; Steps 8-9, launch Step 11. |
| B12 Subscription discovery | **PASS / CONFIRMED_ON_TEST for tested inventory** | Customer-scoped inventory + point GET finds competing candidates; no pagination assumption; missing/concurrent visibility SLA not proven. Held scopes, inventory completeness and race tests Step 8. |
| B13 Ambiguous CREATE recovery | **PASS / CONFIRMED_ON_TEST for simulated lost response** | Customer/agreement/subscription recovered read-only without duplicate POST. Zero/multiple match handling is LOCAL_POLICY_CHECK. Steps 7-8 durable recovery/manual review. |
| B14 Webhooks | **Research DONE / PASS DOCUMENTED architecture; real delivery UNKNOWN** | Official event/configuration contract; **zero real provider events**, no real auth header, timing or 500→retry evidence. Webhook is hint only, scheduled reconciliation is correctness backstop. Step 8 pre-enable verifies real auth/receipt/event→REST visibility or accepts reviewed polling-only operation. |
| B15 Retry policy | **PASS / POLICY_REVIEWED** | B1/B12/B13 test evidence and B14 docs support bounded GET retry, one GET reauth, never blind retry ambiguous CREATE, discover-first/manual review/backoff. Native LBX POST idempotency, forced 429/500 and webhook retry remain UNKNOWN, not correctness assumptions. Steps 6-9. |

## Confirmed integration choices

- LBX owns prices, subscriptions, payments and billing lifecycle. Portal owns binding, frozen user acceptance, fail-closed commercial reconciliation and published allowances. Kernel owns technical capabilities and durable actual usage. No Portal-owned payment API or provider-ID leakage into Kernel.
- Portal customer correlation key equals LBX `users.outer_id`, but Widget JWT identifies the persisted LBX `users.user_id` with `ident_type=7`, after an authoritative paired binding check.
- The commercial price is on a tariff service and the prepared subscription's **effective** service terms; do not reprice existing accepted terms from the newest catalog row. Complete evidence mismatch or incompleteness blocks access; an offer without a proven historic policy/currency/quantity mapping is `NOT_SELLABLE`.
- Prepaid access needs a proven active lifecycle, supported blocking configuration, complete present-cycle financial and commercial terms. `state=-2/current_blocking=0` is not paid; `state=2/current_blocking=0` alone is not sufficient.
- Stable logical allowance IDs and Kernel usage survive same-cycle reread, block/unblock and catalog changes. Only a proven subsequent cycle authorizes a new bucket; raw LBX calendar dates are **not** exact UTC timestamps.
- Provider JWT stays potentially usable for up to 72h. Do not imply that browser closure, logout, `exp` or fresh remint revoke it. Direct Client API write permissions remain an explicit security risk.
- An authenticated webhook is optional acceleration. Every commercial/financial decision rereads authoritative LBX API. Scheduled reconciliation with finite trust and fail-closed expiry remains mandatory.
- Ambiguous POST CREATE outcome holds the scope, recovers by read/discovery and never blindly repeats the mutation.

## Review gates — do not silently close Step 5

**Before recording Phase 0 architecture-gate PASS / beginning Step 6:**

1. Review this matrix against the sanitized reports and ANY-634; explicitly classify each original FAIL/UNKNOWN as architecture-resolved, accepted risk, or deferred runtime gate. No contradictory provider assumptions necessary for Steps 6-11 may remain unresolved.
2. Obtain documented security decision for B4's 72h old-token exposure and B5's direct Client API mutation scope; where actual unsafe authorization cannot be bounded, keep affected production flow disabled and declare the specific risk blocking rather than claiming provider ACL.
3. Review the single consolidated Phase 0 B8 service-price contract and the B1-B15 closeout together. Confirm customer identity, discovery and JWT content is aligned with [GitHub #112](https://github.com/gushinets/payments-portal/issues/112) and update its checklist/decision with remaining security gaps; do not close the whole issue as a fictional PASS.
4. Record the final explicit reviewed **Step 5 architecture gate verdict** in ANY-634, including owners and mandatory pre-enable tests. A research-DONE label or an In Review status is not that verdict.

**After Step 5, before corresponding feature enablement / launch:**

- **Step 6:** full fresh catalog+Kernel manifest, account-specific RUB/scale/provenance; controlled immutable commercial mapping and approved legal/renewal policy; unresolved missing source => `NOT_SELLABLE`.
- **Step 7:** type-7 identity pairing; actual Widget configured safe offer, full independent accepted snapshot; explicit B4/B5 security gate.
- **Step 8:** authentic real webhook and durable receipt/event-to-REST check *or* explicit safe polling-only mode; recovery/concurrency/fault-injection, reconciliation under 6h provider-source trust and <=5m/15m cadence.
- **Step 9:** verified active prepaid paid status and current cycle, no false quota refresh, same-cycle durable usage retention; adapt date-only period persistence.
- **Step 10:** **review both canonical specs together** and implement matching producer+Kernel wire schema, fixtures and clients. Existing contract's immutable UTC `allowances[].period_start/end` is incompatible with assuming LBX date-only values are UTC instants. Retain finite UTC trust/snapshot/grant deadlines, provider-neutrality, 6h trust, <=5m AccessSnapshot expiry, monotonic revisions and usage durability. Do **not** reopen PR #136 as-is or delete UTC fields without the design.
- **Step 11 / launch:** unchanged, uncontaminated natural unpaid renewal fixture; demonstrate authoritative denial and no new allowance on insufficient funds, plus actual end-to-end provider→Portal→Kernel results. Revalidate critical claims on deployed RU configuration.

## Canonical document sequencing

This consolidated Phase 0 PR updates `2026-09-15-external-billing-boundary-design.md` including the entire B8 pricing contract, and stores the B1-B15 evidence/deferral handoff. The provider-neutral `2026-09-15-portal-kernel-access-contract-design.md` **must not** receive LBX-specific IDs/statuses/JWT; its allowance time representation and the related billing-boundary sections are a reviewed **Step 9/10 design + implementation dependency**, as explicitly chosen after closing unmerged PR #136. Step 5 completion wording in ANY-504 that says “both design specs updated” must be interpreted/reconciled to mean that provider facts and deferred cross-service redesign are explicitly documented, not that a speculative wire-contract change is merged now. If program owners require literal prior updates to both specs, the Step 5 gate cannot be declared complete without a separately approved change to that acceptance criterion.

## Evidence pointers

Sanitized reports and manifests are cataloged in the B1–B15 sections of ANY-634 and under `tools/lbx_client/logs/` in their originating environments. Individual file names referenced by Linear are evidence pointers, **not claims that those artifacts are present on `main`**. Before final Step 5 sign-off, validate actual retained repository evidence completeness and provenance; do not invent missing logs or treat a probe summary as a substitute for the original provider facts.
