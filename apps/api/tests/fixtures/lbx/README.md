# Simulated selected LBX reads

These are invented account/tariff/service/period/price values for isolated
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
