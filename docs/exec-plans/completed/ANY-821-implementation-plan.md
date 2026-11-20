# ANY-821 - Terminal resolution for UNKNOWN purchases

Status: Implemented and verified locally.
Updated: 2026-11-20
Issue: [ANY-821](https://linear.app/paveldik/issue/ANY-821/define-and-implement-terminal-resolution-for-purchases-stuck-in)

## Implemented scope

A customer can save the purchase status link during preparation and return to
it after operator completion. The original purchase keeps its accepted terms,
operation identities and provider history. A new purchase requires current
terms and consent. Foreground latency belongs to ANY-819. Live LBX verification
and production enablement remain with ANY-504.

## Recovery scenarios

1. **Request never sent.** If both operations are proven unsent, the operator
   can record `resolved_no_external_effect` and release the product hold.
2. **Reply lost.** GET-only recovery can bind a proven original object and let
   the customer continue the same purchase. The hold stays with that purchase.
3. **Empty discovery.** The hold stays in place while the request could still
   take effect. The operator can release it once both operations are accounted
   for under the terminal completion procedure.
4. **Object found after release.** A live original or a confirmed relationship
   conflict opens a case on the completed purchase. The operator resolves that
   case for the named object. An independent live subscription on the same
   tariff still blocks duplicate financial creation.
5. **Partial preparation.** A known agreement and an uncertain subscription
   require separate evidence. Terminal completion records `resolved_external_terminal`
   when a created object is confirmed to have ended and the other operation is
   also accounted for.
6. **Two-hour deadline.** Automatic discovery pauses for manual review. The
   customer or operator can still request GET-only recovery. The hold remains.
7. **Cancellation, replay and replacement.** Operator completion releases the
   original hold and invalidates old work. The same operator can replay the exact
   command after restart. A replacement has its own consent and operations.

See the [operator procedure](../../engineering/billing-background-operations.md#terminal-completion-any-821),
[purchase history and downgrade rules](../../architecture/payment-portal-data-model.md#purchase-and-external-create-tables)
and [customer journey](../../product/ru-mvp.md).

## Final local verification

On 2026-11-20, `npm run check:fast` passed 38 web boundary checks, 477 component
tests and 2,414 fast API tests. One Windows-only test skipped on Linux. On
PostgreSQL 14, 1,315 of 1,316 tests passed together. The Portal–Kernel HTTP test
passed separately with the Unix socket directory supplied via `PGHOST`.

The first full check stopped on a Next.js 16.4.2 security advisory. The
standalone build passed on retry. All 22 synthetic purchase browser checks
passed across desktop Chromium and Pixel 7 emulation, including reopening a
saved link after release and reaching the current offer and consent step.
