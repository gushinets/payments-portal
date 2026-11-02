# Selected LBX read fixtures

The root files and `selected_offer/` contain invented account/tariff/service/period/price values for isolated
transport and Step 4 normalization tests. They are not recorded provider traffic
or production approval. Runtime code must never import them.

Envelope/field shapes follow the selected GET inventory in
[the Step 3 handoff](../../../app/integrations/lbx/README.md), sourced from
Swagger 1.0.11 and the API quick start. Files are raw JSON bytes so fractional
and large numeric lexemes reach the Integration decoder unchanged.

- `auth.json`: explicitly simulated token and example returned lifetime.
- `tariffs.json`, `tariff.json`: the same selected tariff, account-scoped
  currency **77**, fixed/prepaid/blocking source flags. Currency 77 has no
  approved ISO mapping or scale. No tax/historical policy is fabricated.
- `periods.json`: tariff membership and its documented period definition.
- `services.json`: one commercial service with integer documented multiplier
  bounds, inline price/connection price and discount evidence.
- `prices.json`: two effective-dated price rows, including a future row with
  a large fractional monetary number; no selection of the applicable row is
  performed by Step 3.

Missing/null optional fields must remain unknown. Tests may remove/change
individual values to exercise refusal; no fixture supplies Kernel technical
allowances or a real sellability decision.

## Retained readiness responses

`readiness/e04-services.json` and `readiness/e05-prices.json` are the HTTP
response bodies extracted without number re-encoding from the sanitized
E04/E05 logs cited by `ANY709-LBX043-readonly-readiness.md` (2026-10-25):

- E04: `20261025T000102Z_004_get_tariffs_32_services_216161487ba941e8bce11c66485f6b13.json`.
- E05: `20261025T000102Z_005_get_tariffs_32_services_1_prices_ac48dd85522e4f54a757164c63c44aa8.json`.

These preserve the observed `1.0` bounds, local-midnight inline start and
year/month history fields in their actual locations. No fresh LBX request was
made. The test helper combines these two bodies with synthetic tariff/period,
Kernel and authentication support, and explicitly does not claim the combined
recording is a captured complete stand snapshot or production approval.
