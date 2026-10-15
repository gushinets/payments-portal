# ANY-504 / ANY-664 — Live-source commercial admission and minimal durable state

**Status:** Proposed design amendment for architecture/product-owner review. This PR is documentation only; it does not implement the design or prove a runtime PASS.
**Date:** 2026-10-15
**Scope:** RU MVP, one configured LBX billing account per regional Portal deployment, ANY-504 Steps 6–11; immediate implementation planning in ANY-664 (Step 6).
**Decision owner:** ANY-504 architecture/product owner; decision becomes authoritative only after explicit approval and merge.

## 1. Decision in one paragraph

**Do not continuously mirror the current LBX tariff catalog or the Platform Kernel capability registry into Payments Portal PostgreSQL.** Fetch the relevant, complete, authoritative data **live via private server-to-server APIs** whenever an operator publishes a commercial offer and whenever a customer starts a new purchase. A failed, incomplete, stale-assumed or unverifiable read blocks that new operation. Persist only the approved, immutable offer-to-capability terms and evidence, customer/provider identity and purchase/recovery state, and the authoritative subscription-derived facts needed to keep *already paid* access working safely during temporary LBX failure. Kernel continues to own products, technical metrics and actual usage; Portal continues to own grants/allowances, revisioned paid-access decisions and delivery to Kernel. No offline/new sale, automatic repricing or automatic renewal is invented.

This is a **narrow change to source-read strategy**, not a redesign of payment, customer identity, commercial verification, recovery or paid-access architecture.

## 2. Authority, precise supersession, and unchanged invariants

Previous accepted baseline:
- `docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md`, especially **Platform capability manifest and catalog freshness**, **External catalog and mapping model**, and the Step 6 implementation-order text.
- `docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md`, especially **Capability Manifest — Portal import and freshness**.
- ANY-504 and child ANY-664; the independently reviewed ANY-634/PR #137 provider evidence remains applicable.

**Once approved**, this amendment takes precedence **only** over the following previously prescribed behavior:

| Previous requirement | Replacement |
| --- | --- |
| Periodically import and persist a complete current LBX account catalog as `external_billing_catalog_projections` LKG | Perform complete **selected-offer-scoped** authoritative LBX reads on publication and purchase preflight. Persist approved terms/evidence in immutable mapping and accepted purchase records; no active full-account catalog mirror |
| Persist and periodically refresh the complete Kernel manifest as `capability_manifest_projections` LKG | Fetch a complete authenticated Kernel manifest **live** for each publication and purchase preflight. Validate relevant product/metric bindings. Do not maintain a separate current registry projection in Portal |
| Background refresh at startup and ~5-minute cadence for both source catalogs | No periodic source-catalog/manifest synchronization jobs. Existing **subscription reconciliation**, due-deadline processing and **Kernel AccessSnapshot caching** retain their *different* schedules |
| Allow new publication / purchase based solely on source projection age <=24h | **No age-based permission to start a new commercial operation.** A complete, valid live read for **this operation** is mandatory; failure is `NOT_SELLABLE(reason)` |
| A stored current catalog/manifest digest stands in for source validity | Compare fresh, relevant selected-offer material with the approved immutable revision. Retain provider manifest version and scoped observation digests for audit, **not** as authorization to skip live checks |

The 24-hour `new_sales_projection_max_age` gate is **retired** for both catalogs. It is **not** changed to a different TTL.

Everything else remains binding unless separately amended:
- LBX owns tariff, prices, cycle, subscriptions, balances, payment/Widget, invoices, renewals, cancellation and history.
- Kernel owns the technical product/metric vocabulary, product/metric `enabled` for **new** bindings, actual usage, remaining quota and runtime enforcement.
- Portal owns AnyToolAI identity/legal acceptance, verified external-customer bindings, immutable mapping/purchase snapshots, create/recovery/reconciliation, normalized grants/allowances, access revisions and invalidation.
- The complete versioned authenticated `GET /internal/v1/capability-manifest` contract, field semantics, producer-owned fixtures and drift checks **remain required**; only Portal's durable import is retired.
- The Portal-to-Kernel `AccessSnapshot` and `AccessInvalidation` contracts, Kernel's bounded cache/revision floor, and paid usage accounting **do not change**.
- Subscription projection trust remains `last_authoritative_read_at + 6h`, bounded by paid/allowance/cycle deadlines and ordinary fail-closed rules. Stable reconciliation remains ~15m; urgent attempts <=5m. This **is not** catalog caching.
- Previously pinned mappings, purchases, grants and allowances are not silently rewritten/revoked just because today's catalog or Kernel `enabled` changes.
- Phase 0 B4/B5 JWT/provider permission acceptance, B8 money/history limitations, B9 quantity distinction, B10 date-only/cycle deferral, B11/B14 limitations and the existing Step 7–11 boundaries remain intact.
- No Portal payment REST APIs, fallback payment orchestration, new billing-account routing, shared Portal/Kernel runtime SDK or generalized provider framework.

If this amendment is not approved, the prior accepted specs remain authoritative. An AI executor must not silently mix the two designs.

## 3. Why change: real benefit versus cost

**Current design's benefit:** Portal can serve a recently checked product/offer catalog without querying upstream on every request, and new commercial admission can continue during a bounded upstream outage.

**Why this is a poor default for this MVP:**
1. **Offline purchase is not a usable product guarantee.** Creating the LBX customer/agreement/subscription, checking accepted terms and opening the LBX Widget still require LBX. A locally “sellable” catalog does not make checkout possible when billing is down.
2. **A 24-hour registry/price acceptance window can be misleading.** The Kernel product may be disabled or the LBX offer may change after a sync. Rechecking selected sources at the actual business operation protects the decision more directly than an age threshold.
3. **The full-account mirror solves a larger problem than we have.** MVP publishes a small, controlled set of fixed offers. Importing, validating, transactionally replacing and continuously reconciling every unrelated tariff/product adds complexity without helping an already subscribed user execute.
4. **The correct outage safeguard is elsewhere.** Paid access depends on confirmed customer/subscription facts with a bounded trust lease; Kernel already has its own short, revision-fenced access cache. Neither needs an up-to-24-hour current catalogue.
5. **Less duplicated state means less drift and maintenance.** There are fewer clocks, background workers, race/partial-snapshot problems and extra databases to keep consistent.

**Accepted trade-off:** publication and starting a new purchase now require healthy, verifiable **both** Kernel and LBX reads. This may reduce new-sale availability during a Kernel outage even when LBX is available. It does **not** reduce the explicit bounded survival policy for already confirmed paid access. Do not claim live GETs make provider updates and later CREATE atomic: LBX supplies no proven cross-call snapshot/transaction guarantee; post-preparation authoritative verification and UNKNOWN recovery remain essential.

## 4. Exactly what is and is not persisted

| Authority / data | Portal durable state | Purpose and owner |
| --- | --- | --- |
| LBX current **whole tariff catalog** (all tariffs/services/prices) | **No active copy**, no periodic `external_billing_catalog_projections` writer/reader | Fetch relevant selected-offer dependencies live for new commercial actions |
| LBX **approved offer terms** | **Yes**, in append-only `commercial_mapping_revisions.mapping_document` plus source identifiers, relevant read-set digest/version, exact amount/currency/period/policy, material legal/commercial fingerprint and audit | Show last *approved* offer; compare new live facts with what customer will accept; preserve history |
| LBX verified **customer identity binding** | **Yes**, `external_billing_customers` and existing durable binding invariants (Step 7) | Unambiguous user ↔ provider identity, safe recovery |
| LBX **purchase preparation/create outcome** | **Yes**, `PurchaseIntent`, operation/recovery records and pinned accepted terms (Step 7–8) | Prevent duplicate/unknown external creates; recover and audit |
| LBX **subscription and relevant agreement/cycle/paid status** | **Yes**, authoritative normalized subscription facts, verification timestamps/trust deadline, allowance/cycle linkage (Steps 8–9) | Preserve bounded, read-only *existing paid access* through transient provider failure |
| LBX balances, invoices, payment methods, payment history, autopay state | **No general local replica** | Provider-owned Widget and direct authoritative UI, not paid-access authority |
| Kernel **current full product/metric registry** | **No active copy**, no periodic `capability_manifest_projections` writer/reader | Authenticated live manifest read at publication/purchase |
| Kernel **selected product/metric identity** | **Yes**, in the approved immutable mapping and accepted purchase/grant/allowance references | Historical commercial-to-technical meaning |
| Kernel actual used/remaining quota | **No Portal copy** | Kernel alone owns durable usage and runtime enforcement |
| Portal effective **paid grants/allowances and revisions** | **Yes**, as specified by Steps 9–10 | Answer `AccessSnapshot`; deliver bounded, revisioned paid access to Kernel |

The two existing projection SQLAlchemy models/tables are **pre-implementation schema slots, not evidence that any live sync already works**. On implementing this amendment, remove the unused source-projection paths; retire the two unused tables/models with a narrow, verified schema migration if no real references require them. Do not silently keep background writers or new-sale consumers for those tables “for compatibility.” Do not drop customer, subscription, mapping, grant or recovery data. Because these are pre-production slots, no speculative production-data migration/backfill is required.

The existing `CommercialMappingRevision` shape may be reused. Its currently named `catalog_digest` must have an **explicit documented scope**: the complete, normalized, relevant selected-offer read set (with account/source provenance), **not** a claim of an atomically complete LBX account snapshot. Store a separate `offer_material_digest` and `digest_scope=selected_offer` in versioned mapping evidence, or rename/restructure fields through a narrow migration if that makes the distinction clearer. Never silently reinterpret an account-wide digest as a selected-offer digest. `manifest_version` is producer version evidence, not approval to skip checking current `enabled`. Unrelated products/tariffs changing must not alone reprice or invalidate the selected offer.

## 5. Operational flows

### 5.1 Catalog browsing (read-only, no live availability promise)

1. Browser calls **Portal-owned safe read endpoints**, never LBX Server API or Kernel internal endpoints.
2. Portal reads operator-approved immutable offer terms and the explicitly mapped real Kernel `product_id` from its DB. The UI may show the **last approved** price, currency, period, fixed allowance and product presentation.
3. Distinguish **`PUBLISHED`** (approved historical/current offer description) from **`SELLABLE`** (the current operation passed live admission). A stored mapping alone **never** proves `SELLABLE`. When live availability has not been checked for this operation, display an honest “subject to confirmation”/unverified availability state, not a promise that checkout will work or that the shown price is unchanged at LBX.
4. An unsupported, unpublished, disputed or historically invalidated offer is shown as unavailable, without an active purchase CTA. A public “Continue / check availability” action may start Step 7's live admission; it is **not** a completed sale.
5. If Portal itself is down, frontend shows a safe unavailable/error state. Do not fall back to hard-coded prices, fictional Kernel IDs or mock authority.

**No LBX or Kernel request is required for each anonymous page view.** That would add unnecessary traffic; only new commercial decisions have mandatory live reads.

### 5.2 Operator publishes or revises an offer (ANY-664 Step 6)

1. Authorized operator selects the real configured RU LBX account, provider tariff, supported service/component and period, and a real Kernel product/metric plus approved fixed integer technical allowance and commercial/legal terms.
2. Portal issues a live, authenticated, authorized complete Kernel manifest GET for the correct tenant/region. Validate schema, semantic digest/version, uniqueness and reference integrity. Selected product and metric must exist, be enabled and belong together. Never infer a paid metric from guest quota settings.
3. Portal issues live, scoped LBX Server API GETs for the **selected tariff and all material dependencies**: current tariff membership, relevant periods/components/services and effective-dated service/connection prices and all needed discount/tax/prepaid/blocking/policy and historical applicability evidence. A complete relevant selection is required; enumerating every unrelated account tariff is **not** a requirement. If the verified API cannot establish complete relevant membership or authoritative commercial meaning, refuse publication as `INCOMPLETE`/`NOT_SELLABLE` — do not fabricate a field, currency scale, an atomic LBX snapshot or a default value.
4. Losslessly normalize source money (exact Decimal / integer minor units; account-confirmed currency/unit/scale). Verify approved one-component fixed-periodic prepaid MVP profile; LBX service `multiplicator` is a commercial unit, **not** the Kernel allowance quantity. Compute deterministic relevant read-set digest and approved customer-visible commercial fingerprint.
5. Before committing, reject changed/unsupported/currently disabled sources, missing approval or conflicting revisions. Persist the new **append-only** `CommercialMappingRevision` with full selected-offer accepted semantics, provider/source provenance and read timestamp, scoped fingerprints/digests, authenticated publisher and reason. Network calls occur **outside** the short PostgreSQL business transaction; recheck local expected revision/concurrent publication inside it.
6. Repeating a publication with exactly the same verified source evidence and approved terms is idempotent. A changed material offer, price/policy, metric, allowance or terms requires a separately approved **new revision**. Old revisions remain queryable and unchanged.

A standalone “periodic catalog refresh” is **not** an alternative to these live publish checks.

### 5.3 Customer starts a new purchase (ANY-504 Step 7; specified now to prevent contract drift)

1. Authenticate user, identify one concrete published/approved offer revision, verify Portal customer/scope/idempotency prerequisites.
2. **For this purchase attempt, before a new PurchaseIntent is pinned or any external CREATE is sent**, issue live authenticated Kernel manifest and complete relevant LBX read-set calls. Validate all required identities, `enabled`, selected tariff/service/period/policy, exact amount+currency+scale, approved technical quantity, commercial/legal fingerprint and the latest permissible selected mapping revision. A remote 401/403, timeout, 5xx, missing/incomplete record, unknown money semantics, disabled product or changed material terms => reject/hold this new attempt with a safe deterministic reason; **do not use DB offer snapshots or an old previous-attempt GET as substitute**.
3. Within a short local transaction, pin the already validated immutable revision, accepted material terms, verified product/metric and approved quantity, and idempotently reserve the purchase scope. Network requests are never made while holding that business transaction. Reject stale/conflicting local publication or scope state; no last-write-wins.
4. Only then use the existing narrowly allowed LBX non-payment customer/agreement/subscription preparation workflow and discovery/recovery rules. Ambiguous CREATE remains `UNKNOWN`; **no blind retry**, scope remains held, recovery and eventual manual-review escalation are unchanged.
5. After preparing/linking the external object, **authoritatively reread the actual accepted subscription-specific terms** before enabling Widget mint or deriving paid access. Mismatch, `INCOMPLETE`, source changes or lost response block advancement; retain/recover any already-created provider object rather than assuming no effect or silently repricing.
6. A separate normal customer acceptance / new published revision is required if price or material terms changed. Do not mutate an existing accepted fingerprint in place.

These calls cannot create a perfectly atomic snapshot across Kernel, Portal and LBX. The supported invariant is **no business admission on known-stale or unverified facts, then post-create verification and safe UNKNOWN handling**, not a fictional provider-side compare-and-swap.

### 5.4 Existing user and provider outage (Steps 8–10 unchanged)

- **LBX unavailable:** no new purchase or provider mutation, payment, automatic renewal, speculative unblock/new period, or new Widget mint relying only on cached facts. Continue read-only display of last known user status clearly marked with its observation time where appropriate.
- **Already verified access:** subscription/grant state can survive only inside the existing finite `last_authoritative_read_at + 6h` trust lease **and** only until earlier approved payment/cycle/grant/allowance deadlines; known blocked or expired status stays blocked. Failed/partial LBX reads never extend the lease. At expiry, omit the affected paid facts and fail closed; unrelated users/products remain independent.
- **LBX recovery:** authoritative reread and normalization/reconciliation resume; valid changes produce a new revisioned Portal access state and invalidation. Provider auto-renewal is observed/verified, **not** initiated by a local fallback.
- **Kernel unavailable:** Portal may display approved offer information but must reject new purchase/publication preflights. Actual product execution is not available while Kernel is down; storing Kernel products would not fix this.
- **Portal unavailable to Kernel:** Kernel may use **only its still-valid previously accepted** `AccessSnapshot`, bounded by its <=5m hard TTL, revision floor, actual allowance interval and trust-derived deadlines. On expiry it refuses paid execution; it never extends the cache. This is a separate, required runtime cache, **not** the removed current Kernel catalog projection.
- Kernel does **not** call LBX, Portal does **not** store Kernel runtime usage, and catalog absence never itself revokes immutable historical commercial identities.

## 6. Failure and state rules (must be deterministic)

| Scenario | New publication / purchase | Catalog display / existing access |
| --- | --- | --- |
| Kernel timeout / 401 / 403 / 5xx / malformed or wrong-scope manifest | `NOT_SELLABLE(kernel_source_unavailable_or_invalid)`; no new provider CREATE | Previously approved display can remain; existing grants not revoked solely by manifest failure |
| Kernel product or selected metric now disabled/missing/misbound | `NOT_SELLABLE(capability_disabled_or_invalid)`; no new binding/purchase | Do not rewrite existing accepted grants/pins; runtime policy may independently disable execution |
| LBX tariff service/period/price missing, read partial or invalid price/currency policy | `NOT_SELLABLE(catalog_incomplete_or_unverified)`; no new provider CREATE | Last approved terms may be displayed with non-current/unverified availability; no guessed price |
| Current LBX selected-offer price/renewal/commercial fingerprint changed | `NOT_SELLABLE(source_terms_changed)` until reviewed new revision/acceptance | Historic approved price stays immutable; never silently show new price as approved |
| Unrelated Kernel product or LBX unrelated tariff changed | **Does not by itself block** selected valid offer | No automatic repricing; verify selected scope semantics |
| LBX unavailable after customer CREATE request might have succeeded | Operation stays `UNKNOWN` or equivalent safe held state, not “definitely failed” | Do not mint Widget or issue new paid grant without later authoritative verification |
| LBX unavailable; paid subscription last verified <6h ago | New sale blocked | Previously proven eligible access may continue only within its tighter trust/period limits |
| LBX unavailable; trust or paid period expired | New sale blocked | Affected paid access denied; no local renewal |
| Public Portal catalog request while LBX/Kernel down | Does not attempt CREATE or claim live admission | Published offer details can render with clear verification-on-purchase semantics |

Reason names are conceptual and may map to existing safe API conventions. Never leak S2S URLs, provider secrets, raw DTOs or other users' data to browser responses.

## 7. Concrete implementation impact and boundaries

**ANY-664 / Step 6 must deliver:**
- Real Kernel-owned, service-authenticated versioned manifest producer (only the necessary paid product/metric registry), same actual composed product IDs and supported v1 contract, including `enabled` semantics and producer conformance tests.
- One small typed Portal Kernel GET client and one real, account-scoped typed LBX read client with bounded timeouts/retries/errors. No automatic source catalog synchronization jobs.
- A focused **selected-offer** LBX normalizer/completeness validator; exact money, period, effective price/policy, supported RU profile, source evidence and deterministic fingerprint.
- Controlled append-only audited publication and read API for selected verified mappings. Source GETs live on each publication; publication is refused if either source is unavailable or unprovable.
- Portal-owned safe product list/detail DTO and real localized frontend showing last **approved** product/offer/price/period/allowance, with explicit **unverified-now** semantics rather than `SELLABLE` merely because a DB row exists. Preserve genuine Kernel IDs; editorial placeholder slugs cannot silently impersonate paid products.
- The **optional, removable, development-only HTTP Kernel mock** already required by PR #138, sharing the same real Portal client and wired only by URL/configuration; producer-owned contract fixtures and both PR-time and independent upstream Kernel drift detection still apply. Negative mock tests now demonstrate **live admission failure**, not an obsolete 24h Portal manifest LKG.
- Safe retirement of the unused `capability_manifest_projections` and `external_billing_catalog_projections` runtime paths and (where safe) schema slots. Do not add Redis or a new catalog/mirror DB to replace them.

**ANY-504 later steps must deliver (not Step 6 coding):**
- Step 7 live **purchase-time** checks, idempotent PurchaseIntent pin, customer/agreement/subscription preparation and Widget only after actual accepted terms verification.
- Step 8 proven customer/subscription state, discovery/webhook/normal+urgent reconciliation, UNKNOWN create recovery and finite **6h** subscription trust.
- Step 9 grants/allowances and immutable access revisions/invalidation; Step 10 Kernel snapshot consumption/paid quota enforcement; Step 11 true E2E and launch gates.
- No Step 6 CLI/UI/mock may pretend that future Steps 7–11 already authorize payments or paid execution.

**Coordination required after approval:** update ANY-504, ANY-664, the reviewed ANY-664 implementation plan and any affected developer/contract checklist, explicitly citing this amendment as the narrow superseding source. Preserve old designs as versioned historical records; do not silently patch unrelated Phase 0 decisions.

## 8. Acceptance tests and unambiguous Definition of Done

A documentation-only PR is **complete as a proposal** when this decision, superseded sections, rationale, runtime semantics, ownership and measurable DoD are reviewed and linked. **It is not a claim that the implementation tests below have passed.**

### Functional DoD for ANY-664 Step 6

- [ ] **D1 — Real source:** the real Kernel manifest endpoint answers an authenticated complete valid v1 technical registry; Portal parses it with one production client. Selected enabled product/metric identity is real, not a Portal/frontend fixture.
- [ ] **D2 — No current-source mirrors:** Portal has **no background five-minute Kernel manifest / LBX catalog sync** and no path that treats old `capability_manifest_projections` or `external_billing_catalog_projections` rows or their 24h timestamp as current sale authority. Schema remnants, if any, are documented and inert.
- [ ] **D3 — Exact selected LBX read:** a real scoped LBX GET reads all **material selected-offer** tariff/service/period/price/connection/policy inputs, rejecting missing membership, partial data, unsupported money units/scale, historical applicability unknown and unsupported components; it does not need to mirror unrelated tariffs.
- [ ] **D4 — Publish only live:** each operator publication obtains successful **live** Kernel+LBX checks; disabled/wrong product/metric, failed GET or changed/unapproved source refuses publication with deterministic reason; zero provider CREATE requests.
- [ ] **D5 — Immutable approved offer:** approved publication writes versioned exact selected-source terms and identities, fixed approved integer technical allowance, commercial fingerprint, source evidence/digests, actor/time/reason to PostgreSQL atomically, with repeat-safe idempotency/concurrency and DB-level protection against UPDATE/DELETE. Historic price and mapping remain unchanged after upstream changes.
- [ ] **D6 — Honest frontend:** real Portal API and localized product browser show only vetted stored **approved** terms/identities and communicate that purchase availability is confirmed **later live**. They do not render an old DB offer as currently `SELLABLE`, use fake prices or expose LBX/Kernel internal credentials.
- [ ] **D7 — Outage behavior:** with Kernel or LBX unavailable, direct fresh publication is refused; published terms remain read-only and clearly unverified. An unrelated source change does not invalidate the exact selected offer; changing the selected price or disabling its metric does.
- [ ] **D8 — Dev proof:** the removable local HTTP Kernel mock exercises complete/invalid/disabled/down cases through the **same** Portal client and backend/frontend. Real Kernel contract fixtures, negative drift CI and independent upstream drift signal exist; no mock ships as production authority.
- [ ] **D9 — Regression boundary:** no checkout, payment, paid grants/usage, provider self-service, blanket account-catalog mirroring, speculative idempotent provider POST or new generic framework is introduced in Step 6. Relevant tests and PostgreSQL migrations pass under the repo's manual/CI verification convention.
- [ ] **D10 — Review traceability:** ANY-504, ANY-664 and execution plan reference the approved amendment; obsolete five-minute/24h *source-catalog* acceptance tests are replaced, while subscription trust, AccessSnapshot and later-step recovery tests remain.

### Cross-step acceptance scenarios (Step 7–11, not a Step 6 completion claim)

- [ ] **P1 — Fresh preflight:** each new purchase makes authenticated live Kernel+LBX reads **before PurchaseIntent pin and any provider CREATE**; a disabled capability or changed material price denies the operation with no unintended external mutation.
- [ ] **P2 — Race and UNKNOWN:** if data changes after preflight or an LBX create response is ambiguous, the flow preserves immutable accepted terms, rechecks actual provider subscription terms, holds/reconciles ambiguous effects and never blind-retries or silently reprices.
- [ ] **P3 — Billing outage:** a confirmed active, unblocked paid subscription keeps only its proven access within finite 6h provider trust and tighter period/grant deadlines; paid access stops automatically at expiry, with no invented renewal/unblock.
- [ ] **P4 — Kernel cache separation:** paid `AccessSnapshot` and invalidation work with immutable revision floor and <=5m expiration; Kernel rejects paid execution after cache expiry even if Portal or LBX is offline. Actual used/remaining quota remains Kernel-owned.
- [ ] **P5 — Real E2E:** successful payment/activation/renewal/block and recovery are ultimately proven by authoritative provider and real Kernel behavior, never by a local mock or merely “published” catalog row.

**Overall PASS** requires functional DoD appropriate to each step plus the retained ANY-634 evidence/approval gates. Documentation acceptance alone is **DESIGN APPROVED**, not **IMPLEMENTED** or **PRODUCTION SELLABLE**.

## 9. Reviewer decision checklist

The owner should explicitly decide:
1. Is reduced new-sale availability (mandatory live Kernel+LBX checks) acceptable in return for removing source-catalog mirroring and stale admission?
2. Is the selected-offer relevant read set provably complete under the actual LBX Swagger/Phase 0 evidence? If not, leave a **specific** publication/purchase gate unresolved rather than restore an unproven full-account cache.
3. Are exact approval/fingerprint, actual accepted subscription verification, six-hour paid trust, Kernel AccessSnapshot <=5m cache, provider UNKNOWN and mock/drift requirements preserved?
4. Are ALL changed requirements traced into ANY-504, ANY-664 and its implementation plan **before implementation**?

No other LBX Phase 0 probe is reopened solely because the persistence/read pattern is simplified.
