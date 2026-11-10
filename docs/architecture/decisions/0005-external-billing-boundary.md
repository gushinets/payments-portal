# 0005. External billing boundary

Status: accepted
Date: 2026-09-18

Supersedes for new billing development:
[ADR 0002](0002-plan-based-checkout-identity.md),
[ADR 0004](0004-billing-authority-and-consistency.md), and conflicting target
semantics in related legacy documentation.

## Context

The target external-billing architecture needs one explicit ownership and
documentation-precedence decision. Retained Portal-managed billing code and its
documentation remain useful current-state context, but they must not define the
target or turn External Billing into a direct payment-provider integration.

## Decision

- External Billing owns commercial billing truth and lifecycle.
- Payment Portal owns AnyToolAI identity and legal acceptance; the external-
  billing anti-corruption, projection, reconciliation, and recovery boundary;
  and provider-neutral paid-access projection and delivery.
- Platform Kernel owns technical product and metric vocabulary, durable actual
  usage, and quota enforcement.
- External Billing is not a `PaymentProviderAdapter` and is never registered in
  `PaymentProviderRegistry`. Payment Portal is not the target payment
  orchestrator.
- The accepted
  [external-billing boundary design](../../superpowers/specs/2026-09-15-external-billing-boundary-design.md)
  and
  [Portal-Kernel access-contract design](../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md)
  are the normative implementation baselines, with the accepted
  [live-source commercial admission amendment](../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
  taking precedence only for source-catalog reads and new-operation admission
  (owner confirmation, 2026-10-20). Publication and each new purchase require
  live Kernel/LBX evidence; approved immutable terms are stored and browsed in
  PostgreSQL. There is no periodic source-catalog mirror or catalog-age sale
  permission. Subscription reconciliation/trust, paid-access derivation and
  AccessSnapshot are unchanged. New target development follows this ADR and
  those specifications with that narrow supersession.
- Conflicting target semantics in ADR 0002, ADR 0004, and related legacy
  documentation are superseded. Retained legacy implementation and its
  current-state documentation remain available until later controlled,
  separately gated cleanup.
- `ANY-504` controls implementation sequence. Provider-independent
  pre-production cleanup may precede Phase 0 PASS. Phase 0 remains the hard gate
  for provider-dependent production semantics, Widget/LBX production behavior,
  and launch.

**Dated ANY-709 decisions:** C1-C4 in **"Accepted ANY-709 contract decisions
— 2026-10-31"** in [ANY-504](https://linear.app/paveldik/issue/ANY-504) override the
baseline clauses they explicitly identify. That section owns exact scope,
rationale, retained guarantees and evidence limits; the accepted specification
bodies are preserved. Ownership above and every other clause remain in force.
[ANY-709](https://linear.app/paveldik/issue/ANY-709), section **"ANY-709 result and
contract deviations — 2026-10-31"**, owns results and verification. Ordinary issue
text, reports, passing tests and checkboxes do not create further exceptions.
The additional owner decisions below have only their explicitly stated scopes.

### Accepted point-resource identity decision - 2026-11-01

The owner explicitly accepts authenticated LBX point endpoints as the resource
selection boundary for `GET /users/{id}`, `/tariffs/{id}`, `/agreements/{id}`
and `/subscriptions/{id}`. Portal validates the wire schema once in the
Integration and relies on the point URL to select the requested canonical
resource. A second comparison of the response's self-ID with the URL ID is not
required and must not be restored solely to defend against a hypothetical
violation of that endpoint's resource-selection contract.

This resolves the P1 discussion in [PR #150](https://github.com/gushinets/payments-portal/pull/150#discussion_r4434768469).
No observed LBX response, documented provider limitation or independently
reachable Portal scenario has established such a selection violation. A mock
returning an unrelated resource demonstrates that injected assumption, not a
required production guard. This is an accepted integration assumption, not a
new claim that provider conformance was tested.

Precise precedence: the September design's Phase 0 E canonical
`users.user_id == provider_customer_id` proof and canonical subscription
readback requirements are satisfied by the authenticated canonical point lookup
together with the retained identity/relationship proof. They do not require a
separate returned-self-ID-versus-requested-ID assertion. The same selection
rule applies to tariff and agreement point reads. The accepted specification
bodies remain unchanged.

Original customer-key proof, retained canonical bindings, ambiguity handling,
customer/agreement ownership, seller, subscription agreement/tariff/composition,
effective terms, session/email/contour checks, Client readiness and final
session/fence admission remain required. Discovery and CREATE receipts remain
candidates until point proof; an existing binding cannot be replaced by a
different canonical ID. This decision does not remove relationship checks or
permit financial replay, paid access or production launch. Concrete evidence
that a supported point endpoint selects another resource requires a targeted
reassessment of this assumption.

### Accepted payment-Widget admission decision - 2026-11-09

The owner separates an explicit payment-Widget opening from independent
background verification failures. Each opening still requires its own fresh
customer/owner, agreement/seller, accepted effective-term and dedicated-agreement
inventory proof. A later independent `INCOMPLETE` read, timeout or reconciliation
fence change does not invalidate that successful opening proof by itself.
Background polling continues to record observations and maintain finite source
trust through the shared reconciliation writer.

This resolves the policy question in [PR #161](https://github.com/gushinets/payments-portal/pull/161#discussion_r4506868176).
The injected concurrent-read failure demonstrated current behavior; it was not
an observed LBX outage or an established cause of intermittent Widget failures.
Requiring every unrelated failed poll to cancel an already verified opening
would introduce an additional availability dependency without proving a change
to the purchase.

Precise precedence: in the September design's "LBX Widget as RU billing cabinet"
section, `latest required material verification == COMPLETE_MATCH` and the
`INCOMPLETE` mint prohibition apply to the opening's own required verification.
They do not require a globally unchanged reconciliation fence or a successful
result from every later independent poll. The accepted specification body stays
unchanged. An opening's own incomplete proof still refuses credentials; retained
last-known-good trust cannot substitute for that proof.

The final local check still enforces the current session, original customer and
purchase bindings, consent, unresolved reviews, proven identity/commercial
conflicts and terminal lifecycle changes. A worker can persist those proven
facts through the same writer, and they remain binding on the opening.
Existing lease/claim coordination is retained. This decision does not change
UNKNOWN recovery, paid-access derivation, source-trust renewal or expiry,
Kernel contracts or production enablement.

### Accepted UNKNOWN recovery and lifecycle-metadata decisions - 2026-11-09

The owner keeps the fixed two-hour recovery window and makes its expiry a
durable pause of automatic original-operation discovery, with an actionable
Sentry notification. The pause survives repair/restart and revokes an in-flight
automatic queue claim. The original operation, evidence and held scope remain;
an empty/failed GET or elapsed time never permits another financial CREATE.
For an escalated paused customer, an explicit opening is also GET-only; C3
cannot rearm that paused operation from an empty listing. Its pre-pause policy
and provider uniqueness assumption are otherwise retained.
Completed bindings and typed PROVEN_NOT_SENT results are not escalated.
C4 still gives a genuinely new explicit proven-unsent attempt its own fixed
active window without rewriting original timestamps or request history.

Explicit user or operator recovery remains GET-only and may bind the uniquely
proven original after that window. Ambiguity, foreign identity, changed effective
terms and unrelated reviews require the existing proof-based operator path.
Expiry does not impose an operator-only first-binding rule on an otherwise
proven original. Precise precedence: these rules narrow the September common
UNKNOWN section's continued automatic discovery after escalation and clarify
ANY-715's late-object acceptance condition. No arbitrary rebind, unknown-hold
release, repeat financial POST or paid-access grant is authorized.

The owner also treats LBX `block_to_close_days` as informational lifecycle
metadata. LBX owns how long a financially blocked subscription remains before
closure; Portal consumes the concrete subscription's authoritative blocking and
terminal facts. Missing or changed block-to-close metadata alone does not refuse
a current offer, invalidate accepted purchase conditions, or make reconciliation
or payment-Widget proof incomplete. Owner/seller, money/currency, composition,
period, prepaid/blocking eligibility and the actual effective terms remain
required. Portal promises no independently fixed block-to-close period.

Precise precedence: this excludes that one field from the baseline's mandatory
material-policy reconstruction and live-admission equality rules. New current
offer fingerprints use `current-terms:v3`. Old accepted snapshots and their
stored digests remain unchanged and readable; live continuation recomputes both
old and current offers under the new comparison. Historical approval/mapping
formats are not rewritten. The accepted specification bodies stay intact.

## Implementation status

The former direct-provider runtime has been physically removed. ANY-709 adds
direct product links, live offers, account Widget and accepted-purchase
preparation/recovery. ANY-715 adds polling-only reconciliation/recovery; ANY-765
adds local paid projection, allowances, revisions/outbox, expiry and authenticated
cabinet reads. ANY-766 adds delegated identity, snapshot V2, coherent Kernel paid
admission and durable invalidation delivery. Browser/usage integration and paired
local acceptance remain pending; ANY-767 owns remote/live acceptance and rollout.
Current boundaries are in [ARCHITECTURE](../../../ARCHITECTURE.md) and
[billing operations](../../engineering/billing-background-operations.md).
The original context above records transition history.

## Consequences

- Target billing work has one authority chain: this ADR and the two accepted
  implementation baselines, narrowly superseded by the accepted live-source
  amendment for source reads/admission only.
- Historical direct-provider behavior remains characterizable without becoming a
  target architecture option.
- Unverified provider-dependent assumptions remain explicit Phase 0 gates and
  cannot grant production authority.
- ADR 0001's contour isolation and Region Resolver decisions remain accepted.
