# 043 selected-offer capture, 2026-10-26

The four JSON files are the actual HTTP 200 / LBX code 200 bodies read from the
authorized test origin `https://043.lbxbilling.ru` during the ANY-709 Steps 1–2
QA correction. Only these selected GETs were captured:

- `/api/rest/v1/tariffs/32`
- `/api/rest/v1/tariffs/32/periods`
- `/api/rest/v1/tariffs/32/services`
- `/api/rest/v1/tariffs/32/services/1/prices`

Bodies retain the original structure, JSON numeric spellings (including six
fractional digits), dates, field positions and product descriptions. They contain
no customer records, credentials, HTTP headers or tokens. No payload was adjusted
to satisfy a test. Mutated negative cases live in test code, not these captures.

`record_id` is an integer service-row metadata field (observed value 101), not
`tariff_service_id` (1). The selected inline price for period 1 contains an
explicit `discounts: []`; service-level `discounts` is absent. Its money and
start date agree with the dedicated current price row 288. Normalization uses
that matched price only; another period cannot supply missing discount evidence.

Separate sources: the stand's [Swagger 1.0.11](https://043.lbxbilling.ru/swagger/swagger.json)
documents service-level `PeriodDiscountInfo`, `ShortUserInfo` without `outer_id`,
`UserId`, `PostUserInfo` and nested `Error.response.error`. It does not describe
`record_id` or inline discounts. The official [discount guide](https://docs.lbxbilling.ru/tariffs/add_discount/)
explains service quantity discounts and their commercial effect. It is not a
wire-schema guarantee for the inline field. Inline support is deliberately
bounded to the observed selected-price structure; nonempty discounts are parsed
and refused, not calculated. A future unsupported format must be investigated
rather than ignored.

DTO compatibility policy: explicitly model observed additive metadata and
commercial fields; retain strict envelopes, identifiers, numeric types and
unknown-field rejection for unclassified commercial extensions. Private customer
GETs instead project only the two identity fields and discard all unused
credential/contact fields. No global `extra="ignore"` change was made.

Tests use an explicitly synthetic `Etc/UTC` calendar to isolate parsing. These
captures do not establish the provider's billing timezone or authorize purchases.
