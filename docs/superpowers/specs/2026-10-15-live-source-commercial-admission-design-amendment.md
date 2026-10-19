# ANY-504 / ANY-664 — Live-source commercial admission and minimal durable state

**Status:** Architecture direction **accepted in principle by the reviewer for the RU MVP**, with two mandatory clarifications incorporated below: idempotent new/retry/recovery semantics and resource isolation/total live-read deadline. This is still a **proposed, unmerged** design amendment in PR #138; approval of its merged canonical precedence and implementation remain separate. No runtime PASS is claimed.
**Date:** 2026-10-15
**Scope:** RU MVP, one configured LBX billing account per regional Portal deployment, ANY-504 Steps 6–11; immediate implementation planning in ANY-664 (Step 6).
**Decision owner:** ANY-504 architecture/product owner; decision becomes authoritative only after explicit approval and merge.

**Portal execution scope correction, 2026-10-15:** the separately approved ANY-664 owner decision makes all ticket implementation Portal-only: one typed HTTP client, specification-derived provisional contract/independent fixtures and a separate optional development mock now. Real Kernel producer delivery, paid registry/release approvals, deployment auth/scope and actual-producer conformance are future real-enablement gates, not prerequisites for completing this Portal ticket. This corrects Step 6 ownership/DoD below without approving production sales, canonicalizing this still-proposed live-source policy, or changing any subscription/access safeguard. Remote Linear/PR wording needs separate owner synchronization; this repository edit does not claim those updates.

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
- The complete versioned authenticated `GET /internal/v1/capability-manifest` contract and field semantics **remain required**; only Portal's durable import is retired. ANY-664 implements the client/mock against documented provisional fixtures and focused reference checks. Actual producer-owned fixtures and conformance remain required before real enablement, outside this Portal ticket's completion prerequisite.
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

**Reviewer-accepted MVP trade-off:** publishing and **starting a genuinely new** purchase require healthy, verifiable **both** Kernel and LBX reads. **A retry or recovery of an already-persisted PurchaseIntent must not be converted into a new-purchase preflight**, especially when LBX is temporarily down. This may reduce new-sale availability during a Kernel outage even when LBX is available. It does **not** reduce the explicit bounded survival policy for already confirmed paid access. Do not claim live GETs make provider updates and later CREATE atomic: LBX supplies no proven cross-call snapshot/transaction guarantee; post-preparation authoritative verification and UNKNOWN recovery remain essential.

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

### 5.3 New purchase, retry and recovery are three **different** operations (ANY-504 Steps 7–8)

**Scope and persistent identity.** The browser's `Idempotency-Key` identifies retransmission of one public command; the independent **business scope is `(user_id, product_id)`** (within the configured tenant/region and account). Only **one scope-holding PurchaseIntent or already linked non-terminal subscription** can own that business scope. Store the verified exact accepted amount, account currency/scale, service/period/connection-price breakdown, policy/legal versions, Kernel product/metric/approved allowance, immutable mapping revision/fingerprint and durable outbound-create operation state. Preserve accepted meaning across all retries, restarts, pricing changes and LBX outages. Client/browser close is not an expiry; prepared/unpaid linked subscription **has no browser checkout TTL**.

**A. Genuinely new purchase (no existing occupied scope):**

1. Authenticate and resolve the intended exact approved offer, request identity, required commercial/legal acceptance and scope. **Before live source calls, perform a read-only lookup for an existing idempotency key, scope-holding intent, or linked subscription.** If found, follow B or C below, not the new-purchase path.
2. Only for a genuine new operation: perform a **fresh, bounded** authenticated complete Kernel manifest read and complete relevant LBX selected-offer read set; validate enabled identities, exact amount/currency/scale, material tariff/period/policy, approved mapping revision and accepted terms. A failure, material change or unavailable source means **no new PurchaseIntent and no external CREATE**. A previous successful preflight on a different purchase is not reusable.
3. Commit **one** PurchaseIntent, its *unchanging* accepted snapshot, idempotency identity and the unique `(user_id, product_id)` reservation in a short transaction with a concurrency/expected-revision guard. If another request reserved the scope first, use B or return a stable scope-occupied result; never create a second intent.
4. Before each actual non-money external customer/agreement/subscription CREATE, persist its outbound-create operation identity/correlation and safe attempt state. No provider HTTP happens inside a DB transaction. Unknown CREATE semantics are preserved; provider-side `POST` idempotency is **not assumed**.
5. After a proven create/link, **point-read and validate the actual subscription-specific** owner/agreement, services, `multiplicator`, effective prices, total, currency, period and material policies against the *pinned accepted snapshot* before Widget mint or any paid grant. Provider catalog price changes alone do not reprice an existing accepted subscription.

**B. Repeated public request (same idempotency key or occupied business scope):**

1. The **same idempotency key plus same canonical request/acceptance meaning** returns the *existing* PurchaseIntent or its current provider-neutral status (`preparing`, `awaiting_external_result`, `linked`, `manual_review`, etc.); it never makes a second PurchaseIntent, performs a second CREATE or replaces the snapshot with today's price. The same key with a materially different payload is rejected as an idempotency conflict.
2. A different key for the same **occupied `(user_id, product_id)`** cannot open a second parallel purchase. Return the authorized existing state where safe or a stable `purchase_scope_occupied` response. Already linked prepared/unpaid subscriptions continue holding that scope until authoritative terminal resolution or an audited safe release.
3. **Status reads and exact retries do not require repeating the new-purchase Kernel/LBX catalog preflight.** This is essential: if LBX goes down after an intent was recorded, the customer can still see/resume the *existing operation state*. If **no external CREATE has yet been sent**, the first eventual CREATE must only proceed if the original accepted terms remain authoritatively valid for that actual outbound action; source recheck failure pauses the *same* intent without repricing or creating another.
4. A retry may reshow a prepared, verified, still-eligible Widget entry only after its **separate current Widget-mint predicates**, not on the strength of an old JWT, browser callback or the earlier publication. An existing paid subscription is not recreated via the purchase command.

**C. Recovery after a provider request may have succeeded (including timeout, dropped response or restart):**

1. Durable outbound-create evidence drives recovery for customer/agreement/subscription. If the request may have been sent, persist `UNKNOWN`/`awaiting_external_result`, **keep the PurchaseIntent, accepted terms and business scope held**. Never interpret a timeout as proof no external object was created; never blindly re-send the provider CREATE.
2. Use the documented **read-only point-read/discovery/correlation + authoritative owner/account/agreement/material-terms verification** to link the one proven external object. `outer_id` is only a nonunique discovery hint; canonical subscription identity is the proven provider subscription ID. Multiple candidates/missing proof remain `UNKNOWN`, with no Widget or grant.
3. If LBX is down, return `preparing/not_ready/recovery_pending` (use existing normalized statuses) and keep the operation durable; continue bounded background recovery when possible without using **new-sale admission capacity**. The existing ~2h unresolved-create **manual-review escalation** is not a license to release the scope or try another CREATE. Only authoritative evidence of *no external effect* or audited safe resolution can release/finish the scope; after terminal/safe release, a **separate** newly accepted purchase may use current prices.
4. Recovery never re-pins the fingerprint, mutates the accepted snapshot, starts a second PurchaseIntent, grants paid access from an outbound-success flag or treats today's unrelated catalog repricing as the old subscription's accepted price. Preserve exact accepted terms across outage and restart.

**API/DB invariants (Step 7 owner):** unique active scope plus idempotency identity, durable accepted snapshot and per-create operation record; bounded response states; provider-neutral/public-safe errors; no extra Portal payment/Order model. These are elaborations of ANY-504's existing PurchaseIntent/UNKNOWN mechanism, **not a new orchestration subsystem**.

### 5.4 Existing user and provider outage (Steps 8–10 unchanged)

- **LBX unavailable:** no new purchase or provider mutation, payment, automatic renewal, speculative unblock/new period, or new Widget mint relying only on cached facts. Continue read-only display of last known user status clearly marked with its observation time where appropriate.
- **Already verified access:** subscription/grant state can survive only inside the existing finite `last_authoritative_read_at + 6h` trust lease **and** only until earlier approved payment/cycle/grant/allowance deadlines; known blocked or expired status stays blocked. Failed/partial LBX reads never extend the lease. At expiry, omit the affected paid facts and fail closed; unrelated users/products remain independent.
- **LBX recovery:** authoritative reread and normalization/reconciliation resume; valid changes produce a new revisioned Portal access state and invalidation. Provider auto-renewal is observed/verified, **not** initiated by a local fallback.
- **Kernel unavailable:** Portal may display approved offer information but must reject new purchase/publication preflights. Actual product execution is not available while Kernel is down; storing Kernel products would not fix this.
- **Portal unavailable to Kernel:** Kernel may use **only its still-valid previously accepted** `AccessSnapshot`, bounded by its <=5m hard TTL, revision floor, actual allowance interval and trust-derived deadlines. On expiry it refuses paid execution; it never extends the cache. This is a separate, required runtime cache, **not** the removed current Kernel catalog projection.
- Kernel does **not** call LBX, Portal does **not** store Kernel runtime usage, and catalog absence never itself revokes immutable historical commercial identities.

### 5.5 End-to-end deadline, admission throttling and paid-access isolation

The reviewer accepted the extra LBX reads for MVP **provided they cannot starve already-paid users**. The design requires **bounded work, not a new scheduler/service**:

1. **End-to-end budget:** bound elapsed time for the **whole new-sale/publish live preflight**, including waiting for an admission slot, all relevant Kernel/LBX GETs, read-only bounded retries/one permitted GET re-auth and local normalization. Individual connect/read timeouts are *sub-limits*, not a way to exceed the total budget. Cancel/stop outstanding read-only work after deadline; do not start a provider CREATE if its required admission has timed out or is indeterminate. Use explicit configurable, observable limits; choose actual numbers in the Step 6/7 plans after checking existing runtime resources, not invented LBX SLA guarantees.
2. **Bounded parallelism and backpressure:** limit in-flight new-sale/publish preflights and their waiting queue, with non-blocking or bounded wait and a stable provider-neutral "temporarily unavailable/busy" response when full. No unbounded futures/tasks, connection pools, sessions or retries. Distinguish `429/503` transport semantics according to the existing API convention rather than inventing a new DTO.
3. **Protect existing paid access:** public `AccessSnapshot` reads, already-confirmed grant/allowance read and revision/invalidation/deadline processing **must not wait for an LBX catalog/manifest preflight slot**, nor share a saturated outbound-HTTP capacity budget/threadpool/worker queue with new-sale validation. Keep reserved/independent serving resources for paid-access reads and local deterministic expiry; retain sufficient separately bounded LBX read/reconciliation/recovery capacity to refresh already-confirmed subscriptions even if buyers flood the source API. Reuse existing service pools/background infrastructure; **no extra microservice or universal job framework**.
4. **No accidental trust changes:** sale preflight failure/queue overload **never invalidates** already verified grants or advances/shortens their previously proven trust merely by failing; it also never extends source trust. An access-relevant LBX point read/reconciliation that is complete may extend subscription trust as originally specified; failed/partial reads, browser retries, local DB reads and catalog checks **cannot**.
5. **Metrics and rollout:** record redacted preflight overall latency, per-source latency, queue wait, concurrent in-flight/limit, capacity rejection and timeout category; separately measure `AccessSnapshot` latency and reconciliation lag, including during slow LBX. Explicit operator-configured bounded defaults and a local saturation demonstration are part of DoD; do **not** claim provider SLA or assume a numerical throughput.

**Concrete availability promise and limit:** when **only LBX** is down, a user whose subscription was **already authoritatively confirmed paid, active, unblocked, commercial/identity-consistent** continues to receive Portal paid facts without a live catalog lookup **until the earliest** of the existing `last_authoritative_read_at + 6h` trust lease, proven paid-cycle/grant/allowance deadline or another access-reducing boundary. Portal's `AccessSnapshot` can be reissued from locally trusted facts while Portal runs; Kernel's existing snapshot cache remains at most **5 minutes per issued snapshot**, with revision/deadline fencing, so it refreshes from Portal for longer LBX outages. **Six hours is an upper bound from the last successful full subscription verification, not six guaranteed hours from outage start.** If Portal itself is unavailable too, Kernel can use only its **already issued unexpired** <=5m snapshot, not six hours of autonomous access. After source trust/period expiry, or known block/conflict, affected access must fail closed. No invented renewal, payment, unblock or grace extension. This protects already-paid users **without letting new-sale failure consume their operational capacity**.

## 6. Failure and state rules (must be deterministic)

| Scenario | New publication / purchase | Catalog display / existing access |
| --- | --- | --- |
| Kernel timeout / 401 / 403 / 5xx / malformed or wrong-scope manifest | `NOT_SELLABLE(kernel_source_unavailable_or_invalid)`; no new provider CREATE | Previously approved display can remain; existing grants not revoked solely by manifest failure |
| Kernel product or selected metric now disabled/missing/misbound | `NOT_SELLABLE(capability_disabled_or_invalid)`; no new binding/purchase | Do not rewrite existing accepted grants/pins; runtime policy may independently disable execution |
| LBX tariff service/period/price missing, read partial or invalid price/currency policy | `NOT_SELLABLE(catalog_incomplete_or_unverified)`; no new provider CREATE | Last approved terms may be displayed with non-current/unverified availability; no guessed price |
| Current LBX selected-offer price/renewal/commercial fingerprint changed | `NOT_SELLABLE(source_terms_changed)` until reviewed new revision/acceptance | Historic approved price stays immutable; never silently show new price as approved |
| Unrelated Kernel product or LBX unrelated tariff changed | **Does not by itself block** selected valid offer | No automatic repricing; verify selected scope semantics |
| LBX unavailable after customer CREATE request might have succeeded | Existing `PurchaseIntent` and accepted meaning remain pinned; durable `UNKNOWN`, scope held, read-only discovery and manual review; **no duplicate CREATE** | Customer can view `recovery_pending`; no Widget/grant without authoritative subscription verification |
| LBX unavailable; paid subscription last verified <6h ago | New sale blocked | Previously proven eligible access may continue only within its tighter trust/period limits |
| LBX unavailable; trust or paid period expired | New sale blocked | Affected paid access denied; no local renewal or extended 6h grace; unaffected grants continue |
| Public Portal catalog request while LBX/Kernel down | Does not attempt CREATE or claim live admission | Published offer details can render with clear verification-on-purchase semantics |

Reason names are conceptual and may map to existing safe API conventions. Never leak S2S URLs, provider secrets, raw DTOs or other users' data to browser responses.

| Exact request replay while provider unavailable | Return existing intent/status with the same accepted snapshot, **no new admission/CREATE**; conflicting same-key payload or occupied scope rejected | Existing paid-access read path remains independent |
| LBX slow / preflight budget or capacity exhausted | Fail bounded **new** sale/publish admission; no new external CREATE, no unbounded wait; already initiated operations retain safe status | `AccessSnapshot`, local expiry, grant reads and reserved subscription reconciliation/recovery resources continue |

## 7. Concrete implementation impact and boundaries

**ANY-664 / Step 6 must deliver:**
- A specification-derived versioned manifest contract, independent fixtures/provenance and a standalone development-only HTTP mock in Portal, using source-backed composed product IDs, explicit TEST-ONLY metric/enablement values and provisional auth/digest conventions. One Portal client consumes this boundary. Real Kernel producer/paid registry/auth deployment and actual-producer conformance are separate future enablement work; no Kernel implementation belongs to ANY-664.
- One small typed Portal Kernel GET client and one real, account-scoped typed LBX read client with **total preflight deadline, bounded source retries, limited new-sale/publish concurrency and reserved paid-access/reconciliation capacity**. Step 6 provides the reusable bounded read foundation; Step 7 applies it to purchase admission. No automatic source catalog synchronization jobs.
- A focused **selected-offer** LBX normalizer/completeness validator; exact money, period, effective price/policy, supported RU profile, source evidence and deterministic fingerprint.
- Controlled append-only audited publication and read API for selected verified mappings. Source GETs live on each publication; publication is refused if either source is unavailable or unprovable.
- Portal-owned safe product list/detail DTO and real localized frontend showing last **approved** product/offer/price/period/allowance, with explicit **unverified-now** semantics rather than `SELLABLE` merely because a DB row exists. Preserve genuine Kernel IDs; editorial placeholder slugs cannot silently impersonate paid products.
- The **optional, removable, development-only HTTP Kernel mock** already required by PR #138, sharing the same Portal client and wired only by URL/configuration for a compatible endpoint; Portal-local fixture conformance and focused PR-time/independent upstream reference checks apply now. Keep simulation metadata outside the Kernel schema and mark the entire mapping evidence **SIMULATED** when any source/metric/approval is simulated; real publication/admission and production catalog reads reject/exclude those revisions even after configuration changes. Actual Kernel producer compatibility is verified later, including explicit alignment if wire/hash/auth differs. Negative mock tests demonstrate **live admission failure**, not an obsolete 24h Portal manifest LKG.
- Safe retirement of the unused `capability_manifest_projections` and `external_billing_catalog_projections` runtime paths and (where safe) schema slots. Do not add Redis or a new catalog/mirror DB to replace them.

**ANY-504 later steps must deliver (not Step 6 coding):**
- Step 7 separate **new purchase / same-key retry / recovery** paths: live purchase-time checks only for genuine new admission; one scope-held idempotent `PurchaseIntent` with immutable accepted terms; no duplicate provider CREATE; durable UNKNOWN discovery; Widget only after actual accepted subscription-term verification. Preserve bounded preflight and paid-access resource isolation.
- Step 8 proven customer/subscription state, discovery/webhook/normal+urgent reconciliation, UNKNOWN create recovery and finite **6h** subscription trust, with protected reconciliation capacity under new-sale overload.
- Step 9 grants/allowances and immutable access revisions/invalidation; Step 10 Kernel snapshot consumption/paid quota enforcement; Step 11 true E2E and launch gates.
- No Step 6 CLI/UI/mock may pretend that future Steps 7–11 already authorize payments or paid execution.

**Coordination required after approval:** update ANY-504, ANY-664, the reviewed ANY-664 implementation plan and any affected developer/contract checklist, explicitly citing this amendment as the narrow superseding source. Preserve old designs as versioned historical records; do not silently patch unrelated Phase 0 decisions.

## 8. Acceptance tests and unambiguous Definition of Done

A documentation-only PR is **complete as a proposal** when this decision, superseded sections, rationale, runtime semantics, ownership and measurable DoD are reviewed and linked. **It is not a claim that the implementation tests below have passed.**

### Functional DoD for ANY-664 Step 6

- [ ] **D1 — Portal contract/client:** one production-shaped Portal client parses a complete authenticated v1 manifest over HTTP from the separate specification-based mock using independent provisional fixtures, pinned source-backed product IDs and explicit TEST-ONLY metric/enablement data. Local evidence is SIMULATED. Real producer delivery, paid registry/release/quantity and actual endpoint/schema/hash/auth/scope conformance remain unverified future enablement gates, not a Portal ticket completion prerequisite.
- [ ] **D2 — No current-source mirrors:** Portal has **no background five-minute Kernel manifest / LBX catalog sync** and no path that treats old `capability_manifest_projections` or `external_billing_catalog_projections` rows or their 24h timestamp as current sale authority. Schema remnants, if any, are documented and inert.
- [ ] **D3 — Exact selected LBX read:** a real scoped LBX GET reads all **material selected-offer** tariff/service/period/price/connection/policy inputs, rejecting missing membership, partial data, unsupported money units/scale, historical applicability unknown and unsupported components; it does not need to mirror unrelated tariffs.
- [ ] **D4 — Publish only live:** each operator publication obtains successful **live** Kernel+LBX checks; disabled/wrong product/metric, failed GET or changed/unapproved source refuses publication with deterministic reason; zero provider CREATE requests.
- [ ] **D5 — Immutable approved offer:** approved publication writes versioned exact selected-source terms and identities, fixed approved integer technical allowance, commercial fingerprint, source evidence/digests, actor/time/reason to PostgreSQL atomically, with repeat-safe idempotency/concurrency and DB-level protection against UPDATE/DELETE. Historic price and mapping remain unchanged after upstream changes.
- [ ] **D6 — Honest frontend:** real Portal API and localized product browser show only vetted stored **approved** terms/identities and communicate that purchase availability is confirmed **later live**. They do not render an old DB offer as currently `SELLABLE`, use fake prices or expose LBX/Kernel internal credentials.
- [ ] **D7 — Outage behavior:** with Kernel or LBX unavailable, direct fresh publication is refused; published terms remain read-only and clearly unverified. An unrelated source change does not invalidate the exact selected offer; changing the selected price or disabling its metric does.
- [ ] **D8 — Dev proof:** the removable local HTTP Kernel mock exercises complete/invalid/disabled/down cases through the **same** Portal client and backend/frontend. Independent local contract fixtures and focused negative conformance CI exist. Per owner decision on 2026-10-19, external Kernel source monitoring is removed without replacement while the real manifest API is absent. Distinguish local PASS from `REAL_KERNEL_CONFORMANCE=DEFERRED_NOT_IMPLEMENTED`; actual Kernel API verification is a separate mandatory task before real publication or sales, not a Portal ticket completion prerequisite. Historical provenance pins remain. No mock ships as production authority, and switching URLs cannot upgrade an old SIMULATED mapping into real approval.
- [ ] **D9 — Regression boundary:** no checkout, payment, paid grants/usage, provider self-service, blanket account-catalog mirroring, speculative idempotent provider POST or new generic framework is introduced in Step 6. Relevant tests and PostgreSQL migrations pass under the repo's manual/CI verification convention.
- [ ] **D10 — Review traceability:** ANY-504, ANY-664 and execution plan reference the approved amendment; obsolete five-minute/24h *source-catalog* acceptance tests are replaced, while subscription trust, AccessSnapshot and later-step recovery tests remain.
- [ ] **D11 — Bounded new-admission foundation:** Step 6 Kernel/LBX read foundation supports an explicit **total operation budget** (queue+GET+retries), bounded parallel publication/source-read work and safe saturated-source rejection. No unbounded tasks, no HTTP within SQL transactions, and no LBX SLA guess. Step 7 applies this foundation to new purchase admissions without blocking existing-intent status/recovery.
- [ ] **D12 — Paid-access protection, correctly step-owned:** Step 6 implements and demonstrates bounded source-read work and isolation from existing Portal request/DB capacity, with reserved/independent capacity design for future subscription reconciliation and paid-access serving. Step 6 **cannot claim actual `AccessSnapshot`, grant/deadline processing or reconciliation load-test PASS**, because those flows are implemented in Steps 8–10. Their real under-load, LBX-outage and deadline-failure acceptance is **mandatory** in those steps (P3/P4/P6) before end-to-end/launch PASS. No new-sale timeout may revoke verified paid access or extend provider trust.

### Cross-step acceptance scenarios (Step 7–11, not a Step 6 completion claim)

- [ ] **P1 — Fresh preflight:** each new purchase makes authenticated live Kernel+LBX reads **before PurchaseIntent pin and any provider CREATE**; a disabled capability or changed material price denies the operation with no unintended external mutation.
- [ ] **P2 — New vs repeat vs recovery:** with 20 concurrent same-user/same-product attempts (same key and different keys), only one scope-holding PurchaseIntent exists, and each separately durably identified customer/agreement/subscription CREATE operation is sent at most once while its outcome is uncertain (no duplicate same-object creation). Same key/same meaning returns the original state; same key/different terms conflicts; another key while scope is occupied cannot start another flow. An LBX timeout **after** CREATE yields durable `UNKNOWN`, old accepted snapshot and held scope; recovery by authoritative discovery never blind-retries or silently reprices. After preflight source change, actual subscription readback rejects mismatch.
- [ ] **P3 — Billing outage:** with LBX offline and Portal+Kernel running, a *previously authoritatively confirmed*, active, unblocked, paid and material-term-consistent subscription continues to authorize the relevant product through refreshed Portal `AccessSnapshot` **only up to the earlier of** its pre-existing `last_authoritative_read_at + 6h` deadline and paid/grant/allowance bounds. LBX catalog admission is not consulted and new-sale overload does not delay the snapshot/local expiry path. Recovery after LBX returns refreshes eligibility only after complete authoritative reread; after deadlines or known conflicts affected paid access fails closed.
- [ ] **P4 — Kernel cache separation:** paid `AccessSnapshot` and invalidation work with immutable revision floor and <=5m expiration; during LBX-only outage Kernel obtains **new** snapshots from still-running Portal while its source trust is valid. If Portal also fails, Kernel uses only an already issued <=5m valid snapshot then fails closed. Kernel never extends a snapshot past paid/source trust or grant deadlines. Actual used/remaining quota remains Kernel-owned.
- [ ] **P5 — Real E2E:** successful payment/activation/renewal/block and recovery are ultimately proven by authoritative provider and real Kernel behavior, never by a local mock or merely “published” catalog row.
- [ ] **P6 — Capacity/fault isolation:** artificially slow or time out many simultaneous **new** offer/purchase preflights; the queue/in-flight bounds and total deadlines reject only new admissions in bounded time. Verify independently served Portal `AccessSnapshot`, finite paid-grant deadlines, and reserved normal/urgent subscription reconciliation/recovery capacity. No second PurchaseIntent/provider CREATE and no accidental access revocation.

**Overall PASS** requires functional DoD appropriate to each step plus the retained ANY-634 evidence/approval gates. Documentation acceptance alone is **DESIGN APPROVED**, not **IMPLEMENTED** or **PRODUCTION SELLABLE**.

## 9. Reviewer decision checklist

The owner should explicitly decide:
1. **Accepted in principle for MVP by the architecture reviewer:** reduced availability of **genuinely new** sales due to mandatory live Kernel+LBX checks, in return for simpler source truth. Confirm details at PR merge; **this does not mean old operation retries require a new preflight**.
2. Is the selected-offer relevant read set provably complete under the actual LBX Swagger/Phase 0 evidence? If not, leave a **specific** publication/purchase gate unresolved rather than restore an unproven full-account cache.
3. Are distinct new/retry/recovery branches, immutable single PurchaseIntent, unchanged accepted fingerprint, authoritative subscription readback, bounded **total** preflight deadline, parallelism limits, independent paid serving/reconciliation capacity, finite six-hour paid trust and Kernel `AccessSnapshot` <=5m cache all explicitly implemented and measured?
4. Are ALL changed requirements traced into ANY-504, ANY-664 and its implementation plan **before implementation**?

No other LBX Phase 0 probe is reopened solely because the persistence/read pattern is simplified.
