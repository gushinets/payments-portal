# Complete SIMULATED selected-offer inputs

These invented HTTP responses and scoped evidence inputs exercise the real
`LbxServerClient` and Step 4 normalizer. They are not live recordings, commercial
approvals or evidence for a production account. Earlier Step 3 fixtures remain
unchanged; their discount-bearing profile is deliberately not the positive
fixed-offer fixture.

`selection.json` explicitly chooses account, tariff 701, service 1001, period
901, calendar applicability date and **commercial** count 2. `inputs.json`
records every non-API currency/policy/completeness/history fact with visibly
SIMULATED versioned provenance. The tariff references account-scoped currency
77, configured here as RUB/major units/scale 2. No ISO mapping or scale is
assumed from 77.

`tariff.json`, `periods.json`, `services.json` and `prices.json` are raw numeric
JSON fixtures. The selected recurring price is 100.01, connection charge 7.03
per service unit; extended amounts are 200.02 and 14.06. Service/quantity
management is off, discounts are explicitly empty, and historical/current/
future price rows and a separate connection charge are present. The policy's
calendar validity and historical readback contract are invented test inputs,
not proof of a provider timezone, actual invoice or rollback guarantee.

Use `SelectedOfferRecording` in `tests/support/lbx_selected_offer.py` at the
existing HTTP transport seam. Its response bodies can be changed without
passing through binary-float JSON decoding. Positive, changed-source,
incomplete and unsupported cases use the same client/normalizer; runtime never
imports this helper. Tests also compose synthetic EU/EUR evidence for another
account using currency ID 77 and a different unit/scale. This is not a contour
deployment or live EUR claim.

See `app/integrations/lbx/SELECTED_OFFER.md` for callable contracts, exact digest
inputs, failure meanings, resource ownership and unexecuted human commands.

The optional source-input `calendar` is now mandatory in publication composition.
This fixture explicitly names Europe/Moscow for the simulated account, with a
SIMULATED evidence reference. It is not provider-confirmed timezone evidence.
Regression tests use controlled 2026-10-16 clocks. Manual preparation selects
the current configured account date before independent test review; publication
never backdates or rewrites it. Calendar configuration is included in the exact
selected digest, while the operation date and clock remain outside equality.
