# ANY-664 Step 4 handoff

Implementation and test source only. No tests, checks, formatters, generators,
migrations or live Server API requests were run. Earlier steps, persistence,
composition settings, Portal HTTP contracts and the implementation plan are
unchanged. Public documentation was read; that is not provider-test evidence.

## Callable boundary and resource ownership

`selected_offer.read_selected_offer(client, *, selection, inputs, budget)` is
the asynchronous outer Integration boundary. It consumes the existing real
`LbxServerClient` and the **same admitted `PreflightBudget`** used by the
calling operation, including any preceding Kernel read. It neither creates
admission/deadlines nor owns client shutdown. The composition owner drains
admission before closing the client, retaining resources if cleanup is pending
as documented in the Step 3 README. No DB session/transaction belongs here.

`SelectedOfferRequest` and `SelectedOfferInputs` in `offer_inputs.py` are strict
versioned input contracts, not public API DTOs or production defaults. Supply
the exact account/tariff/service/period, explicit billing-calendar applicability
date and commercial quantity. Currency configuration proves the selected
account's numeric currency reference, ISO currency, source monetary units
(`major` or `minor`) and decimal places. A currency ID has no global mapping.
The policy evidence is bound to tenant, region, account and the exact selection
and has an inclusive/exclusive calendar validity interval.

The GETs do not attest credential/account binding, list completeness, tax,
account-wide discounts, all activation policies, connection-quantity rules or
historical policy applicability. These require explicit evidence references
and revisions. A documentation reference alone cannot establish account
currency, credential binding, selected-list completeness or historical policy.
Every optional material input left absent is unknown. Configuration is evidence
input, **not commercial/legal approval**; Step 5 must supply its separate
independently approved terms/quantity/policy/legal inputs. No loader, operator
CLI, approval gate or publication operation is introduced in Step 4.

The returned frozen `SelectedCommercialOffer` in
`app/domains/catalog/commercial_offer.py` contains only neutral terms, opaque
source references, provenance, observations and a reproducible evidence
document/digest. `normalize_selected_offer()` is synchronous and owns no I/O.
Its `SelectedReadSet` is Integration-only: Application consumes the neutral
result, never that read set, LBX DTOs or raw vendor flags.

`offer_provenance.selected_offer_provenance()` builds the ordered field-source
references and propagates the evidence mode. It owns no I/O or validation;
canonical serialization, hashing and the public call remain in `selected_offer.py`.

## Read set, applicability and refusal

Each successful operation performs two sequential sets of exactly these
documented GETs, with bounded existing auth/retry semantics:

1. `/tariffs/{tar_id}` for the selected tariff and its policy flags/currency.
2. `/tariffs/{tar_id}/periods` for unique selected membership and period meaning.
3. `/tariffs/{tar_id}/services` for selected service membership, quantity bounds,
   customer-management flags, inline price and selected-period discounts.
4. `/tariffs/{tar_id}/services/{service_id}/prices` for effective-dated recurring
   and connection prices and their period definitions.

There is no `/tariffs` whole-account scan, invented pagination, extra point
endpoint, cache or DB writer. The selected tariff's documented list operations
can include unrelated services/periods; only selected material is normalized.
The complete service list is nevertheless a composition dependency: every row
must have correct tariff membership, a unique service identity and an explicit
`enabled_by_default` of `0` or `1`. The selected service must have `1`.
Another service with `1` refuses Portal publication with
`selected_offer_additional_default_components_unsupported`; unknown flags or
ambiguous membership are `INCOMPLETE`. Services with `0` are optional and do
not enter automatic composition. Both bounded reads apply this rule. Portal
does not change LBX tariffs or restrict customer actions in the LBX cabinet.
The documented shapes and numeric flags were read from
[Swagger 1.0.11](https://demo.lbxbilling.ru/swagger/swagger.json) and the
[API quick start](https://docs.lbxbilling.ru/api/api_start/). B8/B9/B10 evidence
retains the limitations recorded in
[the Phase 0 handoff](../../../../../docs/superpowers/phase0/2026-10-14-any-634-lbx-evidence-handoff.md).

The explicit proven price rule is latest inclusive start / exclusive next
start, using **calendar dates**. Duplicate starts, conflicting period meanings,
gaps/overlaps advertised by `next_change_date`, missing successors, absent
applicable rows, missing/ambiguous membership and inline/effective price
disagreement refuse the read. No account timezone or UTC cycle is guessed.
The inline price must agree with the selected effective row; this function is
for new-offer evaluation, not historical subscription invoicing.

The narrow supported profile is fixed, periodic, non-bulk, prepaid with
insufficient-funds blocking, full funding, no demo/proration/credit/promised
payment/manual activation, no service/account discounts, included or
inapplicable tax, independent service selection, and client service/quantity
management disabled. Connection charges are independently proven as once per
selection or per commercial service unit. Unsupported billing calculations
are refused. UI management flags are not assertions about provider API ACLs.

`SelectedOfferRefused.kind` distinguishes `INCOMPLETE` (unknown, missing,
contradictory, partial or changed facts) from `NOT_SELLABLE` (complete evidence
of an unsupported profile). Its stable `code` is `selected_offer_` plus the
safe `reason`. Examples include `money_scale_unknown`,
`price_applicability_ambiguous`, `historical_policy_unproven`,
`selected_source_changed`, `discounts_unsupported` and
`prepaid_blocking_required`. Transport failures become `INCOMPLETE` with the
existing safe LBX error code as reason. Shared preflight deadline/closure and
cancellation retain Step 2 exception semantics. There is no fallback to the
first read set when the reread fails.

Money is exact from the existing JSON-number decoder through normalization,
comparison, products, evidence and decimal-string serialization. Coefficient
arithmetic avoids Decimal's default 28-digit multiplication rounding. Fractional
minor units or products that exceed proven precision are refused without
rounding. Finite representation limits are 256 coefficient/exponent digits
and 0–36 money decimal places; these are local representation bounds, not
claims about provider precision. No technical allowance is inferred from
commercial quantity, prices or guest quotas.

## Two distinct equality contracts

`terms.canonical_json()` serializes only material commercial meaning: currency
and scale, exact unit/extended recurring and separate connection amounts,
period length/unit/anchor and selected price applicability, commercial count
and bounds, supported policy, renewal/cancellation and historical applicability.
Decimal strings have no redundant trailing zeroes, exponent spelling or
negative zero. Dates remain ISO calendar dates.

`selected_evidence_json` additionally includes schema version 1,
`digest_scope=selected_offer`, tenant/region/account, opaque selected
offer/component/period/membership/price references, selected catalog/fiscal
context, proven account currency units/scale, policy validity/dependencies,
the sorted `dependencies.default_components` identities and their source provenance,
evidence mode and field-to-source references/revisions/bases. It contains no
raw DTOs, volatile observations, evaluation date, editorial text, unrelated
list records or inactive historical/future price amounts. The effective
successor date is relevant; unrelated future amounts are not current terms.

Reproduce `selected_evidence_digest` as `sha256:` plus the SHA-256 hex digest of
the canonical document's UTF-8 bytes. JSON keys are sorted, separators compact,
and non-ASCII is preserved. Source observation timestamps are returned in
`observations` separately (eight entries for the two read sets). Semantic
Decimal spellings and unrelated records do not manufacture drift.

The two digests must agree across the bounded reread. Agreement detects only
observed drift; it does not prove atomic snapshots, exclude an ABA change or
make a later provider CREATE atomic. A consistently omitted record cannot be
discovered by inventing pagination; completeness evidence and cross-reference
checks remain mandatory. Changed selected material requires separate approval
and a replacement revision in Step 5. An older immutable result is never
rewritten, and current catalog prices cannot replace a concrete subscription's
authoritative effective/historical terms in later readback.

## Immediate dependency handoff

Step 5 consumes `read_selected_offer()` and `SelectedCommercialOffer`, combining
material terms, selected dependencies and evidence mode with independently
approved technical bindings/quantity and legal/policy revisions. It owns fresh
publication evaluation and immutable mapping persistence; none is implemented
here. A fresh call cannot reuse a previous result as current-source evidence.

Steps 5/7 may use the isolated transport recording in
`apps/api/tests/support/lbx_selected_offer.py` and
`apps/api/tests/fixtures/lbx/selected_offer/`. `SelectedOfferRecording.respond`
is injected through `httpx.MockTransport` into the existing real client; source
DTO parsing, auth, reads and normalization remain unchanged. The helpers
`simulated_selection()` and `simulated_inputs()` provide explicit test-only
configuration/evidence. `reread_bodies`, `replace()` and `append_row()` provide
repeatable changed/partial/unsupported cases without a billing emulator.
Normal Portal runtime must never import these fixtures/helpers or silently
select them on network failure.

Any simulated source or required proof taints the entire result `SIMULATED`,
even after changing source mode. `CONFIGURED_SOURCE` is a provenance label,
never production conformance/approval. Step 5 must retain that label in stored
history and apply its own production exclusions.

The complete simulated RU input selects currency reference 77 as RUB with two
decimal places, quantity 2, recurring unit amount 100.01, and connection unit
amount 7.03: expected extended amounts are 200.02 and 14.06. A synthetic
application-level EU/EUR test uses the same numeric reference in another
account with minor-unit input and scale 3. It does not enable EU or certify EUR
on live LBX. Large fractional fixtures exercise more than 28 decimal digits.

## Human verification, in order

Run from `/home/wstanley/www/work_unirec/payments-portal`:

```bash
export PATH="/home/wstanley/www/work_unirec/payments-portal/.venv/bin:$PATH"
./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_selected_offer_normalization.py apps/api/tests/test_lbx_selected_offer_failures.py
./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_client.py apps/api/tests/test_lbx_client_errors.py apps/api/tests/test_preflight.py
npm run architecture:check
npm run check:fast
```

Run `npm run check` when the existing full local verification environment is
available. These are unexecuted human commands, not PASS evidence. Step 4 adds
no schema/HTTP-contract changes requiring migration or generation. No live
provider request is required for these isolated tests.

Only read-only `pwd`, `git status`, `rg`, `cat` and `sed` inspection, public-doc
reads and source/test/document edits were performed. Runtime outcomes, checks,
actual account credential/currency/scale and historical-policy evidence remain
unverified. G1–G5 and the separate real enablement/approval gates remain open;
no Kernel, publication, checkout, paid grant or paid-cycle claim is made.


### PR #139 publication corrections (2026-10-21)

Commercial quantity must be a positive integer within the selected service's
inclusive LBX min/max, independently of monetary scale. Thus 1.5 × 100.00 is
refused even though 150.00 is exact. Decimal money and the separately approved
Kernel allowance remain unchanged. Publication composition additionally requires
account-scoped calendar evidence and checks today's account date; the standalone
normalizer can still evaluate explicitly historical terms for independent review.
See [operator input contracts](../../cli/COMMERCIAL_MAPPINGS.md#explicit-input-contracts).
