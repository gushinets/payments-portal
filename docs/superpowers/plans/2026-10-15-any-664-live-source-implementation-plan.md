# ANY-664 — Live Kernel/LBX admission, approved offer mapping and Portal catalog

**Status:** REVISED IMPLEMENTATION PLAN — proposed, not implemented or tested (2026-10-15).  
**Program:** [ANY-504](https://linear.app/paveldik/issue/ANY-504); **ticket:** [ANY-664](https://linear.app/paveldik/issue/ANY-664).  
**Architecture change:** [2026-10-15 live-source commercial admission design](https://github.com/gushinets/payments-portal/blob/any-664-kernel-mock-dev-contract-docs/docs/superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md), proposed in [PR #138](https://github.com/gushinets/payments-portal/pull/138). The amendment must be reviewed/approved and reconciled with the canonical design **before implementing the conflicting parts** of this plan.  
**Predecessor:** ANY-634 reviewed architecture gate PASS; PR #137 merged 2026-10-15 (`05d3fcb6a965fcd053d713f49669d1dd25c22978`). PR #138 is open, not merged, and its branch has an older base. Kernel research SHA `079eb03e28d7a50b980795c63c3e4533b785d11f` must be re-pinned.  
**Execution:** Eight sequential code steps. Each is `todo`. Implement **one** step, review/test it, then move to the next. Do not infer implementation PASS from this plan.

## 1. Goal, ownership and deliberately changed architecture

**Expected result before any purchase:** an approved real Kernel technical product is linked to a specific supported LBX tariff/service/period, with exact monetary and legal terms and explicit fixed technical allowance. The privileged publisher validates both **current live sources** for every publication, records an immutable approved offer revision, and the actual Portal backend/frontend display its approved values with an honest **not yet live-verified for purchase** state. Step 7 must distinguish a genuinely new purchase from a retry/recovery of an existing PurchaseIntent: only genuinely new admission repeats full live checks. An unsent initial provider CREATE on an existing intent is revalidated before that outbound action without changing pinned accepted terms.

**Remove:** periodic startup/~five-minute import of Kernel product registry and complete LBX account commercial catalog into `capability_manifest_projections`/`external_billing_catalog_projections`, 24-hour projection-age permission for new publication/purchase, and any alternative Redis mirror. Existing PostgreSQL projection models/tables are *unused foundation slots*: verify consumers/writers, retire or leave inert with explicit migration decision. Do not delete customer, subscription, paid-access or commercial history.

**Keep:** immutable `commercial_mapping_revisions`, verified external customer/purchase/UNKNOWN recovery records (later Step 7), normalized confirmed LBX subscription and period state with finite **6-hour source trust** (Steps 8–9), Portal paid grant/allowance revisions and invalidations (Step 9), Kernel `AccessSnapshot` bounded cache and actual quota/usage enforcement (Step 10). **The product-registry cache and user-access cache are different things.** The latter is not being removed. LBX remains authoritative for money, tariffs, prices, subscriptions, payments and Widget. Kernel owns technical IDs, metrics, enablement and usage. Portal owns identity/legal, approved mappings, paid access derivation and delivery.

**Accepted trade-off:** new publication and new purchase are unavailable if either LBX or Kernel cannot supply complete current evidence. The customer may still *view last approved terms*, clearly marked as subject to check when buying; existing previously proven paid access follows its independent finite trust policy. No offline checkout, no guessed source data or reprice.

**Source scope:** a complete **selected-offer** LBX material read (tariff and the actual relevant service/component membership, billing period, effective-dated service price, separate connection charge, currency unit/scale, discounts/taxes/prepaid/policies, historic applicability). Do not claim to obtain an atomic full-account LBX snapshot, require unrelated tariff mirroring, invent pagination/point endpoints or call tariff price `base_price`. The Kernel producer provides a complete all-or-nothing, versioned S2S manifest; only the selected enabled product and metric(s) authorize a new mapping.

**Commercial semantics:** tariff-service `min_multiplicator` / `max_multiplicator` are commercial configured bounds; actual subscription `multiplicator` belongs to later provider readback. Kernel technical allowance quantity is a separately **approved positive integer**, never derived from provider commercial count, money or guest quota. Provider `currency_id` is account scoped; stand043 `1 -> RUB` is not globally valid and does not itself prove amount scale. Every unsupported/unverified condition fails closed.

**Bounded work and isolation:** one end-to-end configurable new-publication/new-purchase preflight deadline covers admission wait, all LBX/Kernel GETs, limited retries and normalization. Cap simultaneous new-sale/source-read preflights and pending queue; on overload/timeouts reject only *new* operations. Existing PurchaseIntent status and UNKNOWN recovery, locally served AccessSnapshot, paid-access deadline processing, and separately reserved LBX subscription reconciliation/recovery capacity must not wait on saturated new-sale slots. Reuse existing runtime infrastructure, no new microservice and no invented LBX SLA.

**Already-paid outage rule:** With LBX alone down but Portal+Kernel alive, an authoritatively verified paid active/unblocked and commercially consistent user retains access only until the **earliest** of last complete subscription verification + 6h and finite paid/grant/cycle/allowance deadlines. The 6h starts at the *last successful read*, **not** the outage start. Kernel <=5m cached snapshots may be refreshed through Portal while trust remains; when Portal also fails, only an already issued unexpired <=5m snapshot remains. Source failures never extend trust or themselves revoke proven grants; real block/conflict/expiry fails closed. All full paid-grant enforcement belongs to Steps 8–10, not Step 6.

**Freshness and race:** a fresh source read is required **in each publish/purchase operation**. An earlier hash, stored mapping or a GET from a previous operation never substitutes for it. S2S HTTP happens outside short database business transactions; use revision preconditions/concurrency guard locally. Fresh GET does **not** magically make provider state atomic through CREATE: subsequent accepted subscription-specific readback, idempotency/UNKNOWN handling and recovery remain mandatory in later steps.

**Approval status:** The new design document is currently proposed in PR #138, not automatically canonical merely because ticket descriptions were edited. Do not implement contradictory old/new versions until architectural review resolves this precedence. Old design files remain untouched historical documents, superseded narrowly on approval.

## 2. Functional Definition of Done (Step 6)

| ID | Functionally observable outcome | Evidence required |
| --- | --- | --- |
| F1 | Real Kernel complete authenticated versioned manifest; Portal has one typed **on-demand** client, no current-registry mirror | Producer/client contract tests, actual composed product IDs, metric ownership/enabled/auth/scope/error negatives |
| F2 | Real LBX typed client validates complete **selected-offer** tariff/service/period/effective-price/policy and exact account money | Actual supported read set or explicit evidence gate, missing/changed/partial/currency-scale failures, no full-account replica |
| F3 | Privileged operator publishes and queries one immutable approved mapping **after both live checks** | Operator CLI dry-run/publish, audit, historical immutability at DB boundary, concurrency, two-source outage/changed terms fail |
| F4 | Real Portal backend+localized browser show approved exact product/offer/currency/period/fixed allowance and truthful state | Generated API/TS, actual list/detail, real Kernel product-ID direct URL + hard reload, no premature buy CTA |
| F5 | No background full source mirror, no 24h sale admission and no history rewrite | No source sync jobs/writers, old tables inert/retired, prior approved display survives upstream outage; **new publish fails** |
| F6 | Optional isolated Kernel HTTP development mock and real producer-based contract drift detection | Mock on/off/invalid/down/recover, simulated label, config-only real switch, no production inclusion; PR and independently scheduled upstream checks |
| F7 | Bounded total live-check deadline and parallel admission cap with source-outage-safe result | Human forces slow LBX + concurrent new publish; bounded rejection, no unbounded queue or provider CREATE; independent read/resource capacity remains for existing access and later reconciliation |

Step 6 **does not** implement: PurchaseIntent, customer/agreement/subscription CREATE, Widget JWT, payment execution, webhook/reconciliation jobs, grants/access revisions, actual quota enforcement or paid E2E. Those are ANY-504 Steps 7–11. Their DoD is preserved, not silently marked done.

## 3. Preconditions, baseline and decisions

- **G0 — New architectural authority:** obtain review/approval of amendment in PR #138 and align the plan/tickets. Existing ANY-634 architecture-gate PASS stands; no new B4/B5 JWT/ACL experiment or approval is needed.
- **G1 — Kernel paid product identity:** actual composed `ConfigRegistry.products` includes e.g. `proposal_ai`, but mere presence/`ANYTOOLAI_ENABLED_PRODUCT_IDS` does not mean RU monetization approval. Product owner approves actual `product_id`, paid `metric_key`, unit, enabled policy and release; unknown => no real approved publication.
- **G2 — LBX selected offer source:** account-bound complete selected tariff/services/period/effective price/policies and exact money units/scale proven from applicable Swagger/real configuration. B8 service-level price, B9 commercial-vs-technical unit, historic price/policy applicability retained. Unknown => unavailable, not synthetic money.
- **G3 — Commercial/legal approval:** explicit supported fixed periodic/prepaid/non-bulk service, approved technical quantity and renewal/cancel/legal/tax/discount policies, historical change control. Unknown => refuse publication.
- **G4 — Deployment/trusted identity:** private Kernel+LBX service auth, tenant/region/account, TLS/secret handling and trusted privileged operator identity. Mock/test-only source may demonstrate UI but never real `SELLABLE`.
- **G5 — Steps 7–11 launch:** actual purchase/readback/Widget, B14 webhook or documented safe polling-only, B10 calendar-cycle wire, natural unpaid renewal and Kernel usage; not Step 6 code.

Use existing Portal models `apps/api/app/models/billing_projections.py`: `commercial_mapping_revisions` is the durable approved mapping; `capability_manifest_projections` and `external_billing_catalog_projections` must no longer become source-admission read models. The current Portal frontend editorial slugs `document-summary` and `prompt-optimizer` are not actual Kernel IDs. Inspect `apps/web/src/app/[locale]/products/[product]/page.tsx`: existing `dynamicParams = false` / limited static params must not block real product IDs on direct navigation.

## 4. Implementation sequence — one step at a time

### Step 1 — Real Kernel Capability Manifest producer

**Status:** `todo` — repo `gushinets/anytoolai-platform`. Implement accepted `GET /internal/v1/capability-manifest?tenant_id=anytoolai&region=ru`, complete versioned schema v1, actual immutable composed `ConfigRegistry.products`, explicit minimal paid metric registry, one real product per metric, correct deployment/release `enabled`, deterministic semantic `manifest_version` independent of volatile generation timestamp, authorized S2S 401/403, no partial `200`. Preserve guest quota/runtime and existing per-product endpoint. Producer-owned canonical fixture and negative contract tests. No LBX or Kernel paid usage/AccessSnapshot changes.

**AI execution instruction:** Implement **only** Kernel manifest endpoint/schema/auth/contract fixtures and tests as source edits; inspect existing registry/auth patterns, do not invent paid metrics or sellable release flags. If source ownership/auth conflicts, report a blocker. **Do not run** tests/builds/generators, **do not stage/commit/push**. Report paths, exact future human tests and limitations.

**Human checks:** `uv run python -m pytest -q apps/platform-api/tests/test_capability_manifest.py`; existing registry/bootstrap tests; `make validate-architecture`. Exercise 200 valid/complete/stable hash, 401/403, disabled/misbound/duplicate metric and digest change. **DoD:** actual code endpoint, not fixture-only.

### Step 2 — Typed live Portal Kernel client, no DB import

**Status:** `todo` — repo `gushinets/payments-portal`. Single `PlatformKernelClient` with correct service auth, tenant/region, bounded GET timeout/retry, typed error and full v1/schema/metric-owner/semantic digest validation against real Step 1 producer contract. Used **on demand** by publisher (and future Step 7). Mock selected via configuration URL/credentials only. **No `CapabilityManifestProjection` writers/reader for sale, no startup task, no 5m sync, no 24h grace**. Apply one **configurable overall preflight deadline** including queue wait/GETs/retries, bounded concurrent admission and finite pending queue; preserve separately reserved access/reconciliation capacity. Never hold SQL transaction across HTTP; no browser S2S secret exposure.

**AI execution instruction:** Implement **only** live typed Kernel S2S caller and validation/tests. Prove future fresh call for each admission, offline/401/malformed/disabled fail closed. Do not persist manifest or build background job, UI, mapping or purchase. **Do not run** automation/tests/builds/formatters/codegen or commit/push. Report actual commands and evidence.

**Human checks:** proposed `./.venv/bin/python -m pytest -q apps/api/tests/test_kernel_manifest_client.py`, `npm run architecture:check`; assert old table untouched and no source refresh. **DoD:** callable complete fresh Kernel manifest, error categories and negative tests.

### Step 3 — Typed LBX Server API transport and read foundation

**Status:** `todo` — Portal. Configure one RU billing account and scoped server secrets; use real documented LBX tariff, periods, services, effective-dated service-price and relevant policy GETs. Typed DTOs inside Integration, redacted logs, connect/read timeouts **subordinate to total operation budget**, bounded concurrent new-sale requests and queue, bounded safe GET retries/one controlled reauth, permanent 401/403, no invented pagination/snapshot/POST idempotency. Provide narrowly typed future customer/agreement/subscription operation methods **as inert callable foundations**, not Step 7 runtime CREATE. Provider-specific DTOs do not enter Kernel/Application wire, no payment REST.

**AI execution instruction:** Implement **only** verified private LBX transport and selected-offer read operations/future narrow DTO foundation. Do not invoke any CREATE, launch subscription flow, build full-account sync or generic billing SDK. **Do not run** checks/builds or git writes. Report exact Swagger-backed operations and human tests.

**Human checks:** proposed `./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_client.py apps/api/tests/test_lbx_client_errors.py`, `npm run lock:check:api`. Verify auth/one GET reauth/429/5xx finite retry, lost response classified UNKNOWN for future CREATE, redaction. **DoD:** safe reusable typed reads, zero external mutations.

### Step 4 — Normalize complete material dependencies of one LBX offer

**Status:** `todo` — Portal. Input is explicitly selected account/tariff/service/period; fetch the **entire relevant offer read set**, not every unrelated tariff. Normalize tariff→service/component→period→effective-dated price and separate connection charge, exact decimal/ISO currency/provider units/scale, tax/discount/demo/proration/prepaid/blocking, documented quantity bounds, source IDs/effective dates and historical applicability. Source completeness may require actual documented list/filter semantics plus bounded relevant reread; do **not** claim LBX atomic snapshot. Distinguish unsupported complete tariff (`NOT_SELLABLE`) from missing referenced data (`INCOMPLETE`). Deterministic **selected-offer** material digest/version/provenance returned as typed in-memory data. Never write `external_billing_catalog_projections` or implement refresh. Do not infer Kernel allowance from multiplicator.

**AI execution instruction:** Implement **only** selected-offer LBX normalizer/read-set validator + unit/error tests; reject money scale unknown, missing price/policy, selected source mutation/drift, account mismatch and partial read; no cache fallback, old catalog sync or Step 5 publish. **No tests/build/codegen/git writes**; report actual read set and validation gates.

**Human checks:** proposed `./.venv/bin/python -m pytest -q apps/api/tests/test_lbx_selected_offer_normalization.py apps/api/tests/test_lbx_selected_offer_failures.py`; verify unrelated tariff changes don't invalidate selected offer, changing selected price does, float/inferred RUB scale fails. **DoD:** complete request-local validated selected commercial meaning, no persisted source mirror.

### Step 5 — Privileged live publication, immutable revision

**Status:** `todo` — Portal. Restricted audited operator CLI/command (not speculative public RBAC API), `dry-run`, publish/query; **always fetch live Kernel (Step 2) and LBX selected offer (Step 4) for that publication** and check approved fixed integer technical quantity, real enabled product/metric ownership, exact source price/period/currency/policy, legal/renewal/cancellation terms. Generate normalized material fingerprint. Store immutable approved mapping in `commercial_mapping_revisions` with account/tenant/region, source IDs/version, Kernel manifest version, **selected-offer** digest (`digest_scope=selected_offer`, never claim full-account snapshot), evidence timestamps/mode, terms and audit actor/reason. Protect UPDATE/DELETE at DB boundary if no guard exists; short DB transaction after source HTTP, expected revision/CAS/lock; exact same *material evidence* idempotent, changed evidence requires reapproval/new revision. A stored mapping is `PUBLISHED_APPROVED_UNVERIFIED_NOW`, **not evergreen `SELLABLE`**.

**AI execution instruction:** Implement **only** real two-source-on-every-publication evaluator, audited privileged append-only publication/query/DB tests. A failed/changed source blocks publish; no historical reprice or provider POST. No extra admin portal, background cache sync, purchased grant or checkout. Respect total admission time budget, fail promptly under source congestion, preserve isolated paid-access resources. **Do not run** tests/DB migrations/builds/git writes; report CLI actual help/manual tests.

**Human checks:** proposed `./.venv/bin/python -m pytest -q apps/api/tests/test_commercial_sellability.py`, `npm run test:api:postgres`; test API down after previous publication, changed selected source price/metric disabled, authorized publisher, concurrent different rev, DB rollback, UPDATE/DELETE rejection, no HTTP under DB transaction, zero provider CREATE. **DoD:** immutable approved mapping only from successful live checks.

### Step 6 — Real Portal API and frontend approved-offer preview

**Status:** `todo` — Portal. Add frontend-safe GET product list/detail using **stored approved mapping/offer terms** and editorial presentation keyed explicitly to real Kernel `product_id`. Show exact approved price/currency/period/fixed metric allowance and `PUBLISHED_APPROVED_UNVERIFIED_NOW` / safe unavailable state; availability will be checked on Step 7 purchase, not from outdated local cache or every browse request. No direct browser LBX/Kernel, no provider secrets/raw DTO or hardcoded price/sellability. Generated FastAPI OpenAPI→TypeScript contract, current localized pages and responsive/accessibility. Fix `dynamicParams = false` limited editorial route so real `/ru/products/<kernel-id>` works by **direct URL and hard reload**. No purchase CTA until Step 7.

**AI execution instruction:** Implement **only** safe catalog/detail API + generated-schema source contracts and real localized browser integration; use approved immutable mapping, not mirror/full live GET on every page. No checkout, grants, mock production fallback, catalog UI redesign. **Do not run** codegen/tests/builds/git writes; human will generate artifacts. Report direct-route and negative-state proof.

**Human checks:** `npm run generate && npm run generate:check`, proposed `./.venv/bin/python -m pytest -q apps/api/tests/test_catalog_api.py`, `npm run typecheck:web`, web component tests, actual browser via `npm run repo:up`. Approved preview remains readable if external sources offline; new publication is separately blocked. **DoD:** actual backend/DB/browser truthfully displays approval without false current sale claim.

### Step 7 — Optional removable local Kernel HTTP mock

**Status:** `todo` — Portal. Standalone dev-only HTTP Kernel manifest mock with actual v1 auth/schema/version/metric contract, opt-in `docker-compose.kernel-mock.dev.yml` overlay/profile on **same worktree harness Compose project and backend network**; disabled by default, production build/Compose excluded. Real Portal client switches solely via URL/credentials; ensure environment reaches API **container**, not merely exported local shell. Simulated selected-offer LBX test source via an isolated read fixture or real authorized test account; explicitly `SIMULATED/TEST`, never genuine production offer. Mock down/disabled/malformed/401/timeout makes *new publication fail immediately*, while previous approved preview is still displayable without a false `SELLABLE`. Reconcile `docs/engineering/DEVELOPMENT.md` in PR #138; no Kernel production dependency on mock.

**AI execution instruction:** Implement **only** optional local mock/Compose/docs/real-backend-browser smoke+negative tests. No fake client branches, persistent LKG, full LBX emulator, payment or production mock. **Do not run** automated verification/build/git writes; provide exact actual working opt-in, stop, remove and config-switch commands.

**Human checks:** `npm run repo:setup`, check `.harness/runtime.json` and effective Compose, run opt-in mock and real `npm run repo:up`, proposed mock contract test and `npm run test:e2e`, stop/remove mock, inspect clean production config/build. **DoD:** removable dev mock only, real HTTP contract and browser preview behavior.

### Step 8 — Producer/consumer cross-repo conformance and upstream drift

**Status:** `todo` — Kernel producer and Portal consumer. Pin Kernel source SHA/versioned producer-owned OpenAPI/fixture hash; exercise **actual Kernel endpoint code** (not just Portal-copied JSON) against Portal Step 2 typed client and Step 7 dev HTTP mock, including auth/scope/schema/metric ownership/version. CI runs on every relevant Portal PR **and independently** of Portal PRs on upstream Kernel change, via tested event trigger or bounded GitHub Actions scheduled default-branch latest Kernel `main` check. GitHub scheduled workflows do not operate independently from feature branches; post-merge default-branch schedule must be observed before claiming active automatic drift monitoring. Deliberately break a required field/metric owner and prove failing check; unrelated added products/commits must not fail. Unavailable current upstream => `UNKNOWN/FAIL`, never old fixture green. Update `docs/engineering/DEVELOPMENT.md` with source pin/refresh, exact command, trigger and failure handling.

**AI execution instruction:** Implement **only** real Kernel producer/Portal client/mock contract conformance, PR CI plus independent upstream drift check, negative regression and docs. Keep no shared runtime SDK, provider mutating probe, Step 10 access wire changes or broader CI framework. **Do not run** CI/tests/linters/builds/git writes; report commands and post-merge proof requirements.

**Human checks:** Kernel capability-manifest producer tests; Portal proposed `./.venv/bin/python scripts/check_kernel_manifest_contract.py --kernel-repo ../anytoolai-platform`, `npm run generate:check`, `npm run architecture:check`, scheduled/default-branch workflow run when merged. **DoD:** real verified producer↔consumer/mock compatibility, reproducible upstream incompatibility failure and independent signal.

## 5. Cross-step invariants and failure matrix

| Case | Step 6 new publish | Existing offer/user |
| --- | --- | --- |
| Kernel or LBX timeout/401/403/5xx, invalid/partial source | Deny `NOT_SELLABLE(source_unavailable_or_invalid)`; no mapping write or CREATE | Previously published approved terms may be shown *unverified*; no historical grant revoke solely due new-sale preflight |
| Kernel product/metric disabled/misbound | Deny, no new mapping | Existing pinned meanings unchanged; separate Kernel runtime policy still applies |
| Selected LBX service/period/price changes or policy/money unknown | Deny until reviewed new approved revision | Old immutable commercial fingerprint/price untouched |
| Unrelated new Kernel product/LBX tariff changes | No automatic denial if selected dependency set valid | No historical reprice; full Kernel manifest validation still required |
| Publisher concurrency or local transaction failure | One commit or deterministic conflict/rollback | Existing mapping remains, no partial audit |
| Provider CREATE ambiguous **in Step 7** | Preserve `UNKNOWN`, no blind retry; not executed by Step 6 | Recovery scope held and actual subscription terms re-read before access |
| LBX unavailable for existing confirmed customer | No new sale | With Portal+Kernel healthy, verified active/unblocked paid grants remain only to the earliest last complete source read + **6h** or paid/grant/cycle deadlines; Portal may issue fresh <=5m Kernel snapshots within that trust. Fail closed at deadline, never extend lease on failed reads. |
| Slow LBX and overfull new-sale checks | Bound total queue+HTTP+retry deadline, concurrent tasks and waiting queue; reject further new admissions | Step 6 demonstrates capacity separation structurally and with available requests; Steps 8–10 must later prove actual Portal AccessSnapshot, deterministic expiration and reserved subscription reconciliation/recovery under load |
| Repeated / recovering Step 7 purchase | Not a Step 6 purchase command | Same request/key/scope returns existing pinned PurchaseIntent/state, not new preflight or CREATE. UNKNOWN holds scope and original meaning; use read-only discovery. Different key same occupied (user_id, product_id) blocked. |
| Kernel cannot fetch Portal `AccessSnapshot` **Step 10** | Not a Step 6 publication bypass | Kernel may use only valid unexpired existing <=5m cached snapshot and revision floor; actual usage never stored by Portal |

**Source-era code cleanup:** old tables may remain as explicitly inert schema until a justified narrow migration can remove them without disrupting completed persistence or later subscription state. No duplicate full-source sync jobs, no new Redis mirror. All provider REST payloads remain Integration-private. Provider money exact (no float), account-scoped currency, release approval explicit, no implicit 1,000 technical operations.

## 6. Human acceptance and release sequencing

1. Review/approve **new** design amendment PR #138, reconcile its old branch base against merged PR #137 and target `main` when authorized; do **not** merge or change PR as part of editing this plan.
2. For each step, inspect actual current repos/contract, implement its narrow result, run human tests and review actual behavior before marking done. Agent does **not** run verification or commit.
3. Run actual Kernel manifest endpoint/auth/fixture tests, Portal typed LBX/Kernel read and negative tests, PostgreSQL immutability/concurrency tests, API generation/check, browser direct reload and mock on/off/prod exclusion tests.
4. Verify static fixtures never pass production `SELLABLE`, and **new** publication cannot use a stored previous source version after remote failure. A previously approved readable offer is not proof of current purchase availability.
5. Run scoped repo verification: `npm run generate`, `npm run generate:check`, `npm run test:api:fast`, disposable-DB `npm run test:api:postgres`, `npm run test:boundaries:web`, `npm run typecheck:web`, `npm run architecture:check`, `npm run check` (human only); adapt to current repo commands. Kernel architecture and relevant tests separately.
6. Have an independent intent/architecture/DoD review covering F1–F7 and full negative cases. Document actual SHAs and test results, reasons for unresolved G1–G4, and Step 7 handoff. No claim Step 7–11 production success here.

## 7. Exact Step 7 handoff and completion record

**Step 7 — new operation order:** authenticate and **first look up existing idempotency key / occupied (user_id, product_id) / linked subscription**. If one exists, return the existing status or recover it; no second PurchaseIntent, no new-purchase live preflight, no duplicated provider CREATE. For a genuinely new operation only: exact approved mapping → **bounded live complete Kernel manifest + LBX selected-offer verification** before local `PurchaseIntent` pin or provider CREATE → short transactional immutable pin/idempotent scope reservation → LBX customer/agreement/subscription non-payment preparation with safe UNKNOWN recovery → authoritative verification of **actual** accepted subscription-specific effective price/services/periods → only then Widget-mint predicates and subsequent paid eligibility steps. HTTP outside database business transactions. A race across LBX calls cannot be assumed atomic: mismatch/recovery holds the operation; no silent repricing or recreated subscription. **Exact retry:** same idempotency key+same canonical meaning gives existing state; conflicting payload fails; different key while scope occupied cannot start a parallel purchase. **Recovery:** ambiguous create leaves durable UNKNOWN and one held scope, performs read-only discovery; manual-review deadline never permits blind retry/release. **Unsent initial CREATE:** recheck approved terms when finally proceeding, without repinning or mutating acceptance. **Load:** one overall deadline/parallelism limit on new-sale preflight; paid AccessSnapshot and existing-subscription reconciliation remain isolated. **LBX-only outage:** proven active paid access continues within original finite provider trust/deadline only, not six hours guaranteed from outage start.

**Record template (complete after execution only):**

```text
Design PR #138 architecture approved/merged: <YES/NO, evidence, SHA>
ANY-634 architecture PASS: recorded; PR #137 merged SHA 05d3fcb6...
ANY-664 Step 1..8: todo / PASS / FAIL / NOT_RUN (each with evidence)
Kernel actual producer SHA/fixture: <...>
Portal actual implementing SHA: <...>
Current-source mirrors/writers: NONE <verification>
LBX selected account tariff/price/currency/scale evidence: <.../UNKNOWN>
Approved product/metric/quantity/terms: <.../UNKNOWN>
Publisher live kernel+LBX negative tests + DB immutable history: <...>
Real API/Next.js direct Kernel-ID route and browse-unverified states: <...>
Mock simulation and no-production proof: <...>
PR-time and independent upstream Kernel drift runs: <.../NOT_YET_OPERATIONAL>
Open G1-G5 gates and owners: <...>
Step 7 handoff approved by: <...>
```

**Plan status remains:** `REVISED / NOT IMPLEMENTED / NOT VERIFIED`; all DoD checkboxes are goals, not passed evidence.