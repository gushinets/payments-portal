# Correctness Review

Apply the authoritative
[internal-contract conventions](../CODING_CONVENTIONS.md#internal-contracts)
to new/materially changed contracts and their affected producers/consumers.

- Acceptance criteria describe the intended intermediate or final result.
  Trace the real entrypoint through decisions, writes/side effects,
  serialization and the next consumer; a successful response alone is not
  proof of that result.
- Existing coverage was assessed before implementation. Bug regressions failed
  before the fix; behavior-preserving work has characterization evidence.
  Assertions and mocks exercise the claimed guarantee rather than replace it.
- Failure, partial-success, duplicate, retry, stale-event and recovery paths
  preserve auth/ownership, history and idempotency. Decisions applied after I/O
  or transaction gaps retain a valid basis through a proven atomic mechanism.
- Known shared inputs/results/snapshots declare required/optional fields and
  meaningful consumed nested shapes. Bare dictionaries, broad aliases, erased
  dataclass fields or casts do not establish a concrete contract.
- Finite states/outcomes/kinds/scopes have one symbolic owner. Textual Python
  vocabularies use `StrEnum`; persisted vocabularies reuse `app.models` and
  `PersistedEnumType` over TEXT/VARCHAR. All Portal-owned ORM, dataclass and response-model
  status/state fields are covered, including singleton states without
  transitions. Review queue, observation, review, operator, catalog, health,
  diagnostics/metrics and local UI concepts where they own finite meanings.
- Trace the whole symbolic use path: annotations, construction, client/server
  defaults, positive factories/fixtures, assignments/transitions, comparisons,
  membership/`match`, query filters, DML/upserts, serialized results and UI.
  Active CHECK/partial-index SQL derives values from its owner or has focused
  parity checks; frozen migrations and independent wire/history assertions
  preserve compatibility literals.
- Enum-member narrowing, boolean literals and actual schema/protocol tags are
  distinguished from business states. A singleton status/outcome is not a tag
  exception. A single tag/diagnostic identifier can use an owner constant.
- External and consumed retained data is validated once at its real boundary;
  useful nested/helper/callable types survive inward. Annotations and
  `frozen=True` are not runtime validation. Trusted internal calls are not
  repeatedly decoded, and unread retained data is not decoded speculatively.
- Repeated construction identity/init invariants have one concrete owner where
  justified. Intentional use-case differences and Application transition,
  transaction, lease and fencing ownership remain intact; no factory or second
  entity graph is required merely to wrap direct ORM construction.
- Genuine maps, opaque requests, physical JSON and necessary SDK/decoding/
  redaction seams have an identifiable owner, consumer and reason. Known-key
  objects are not genuine maps. Empty payloads stay empty absent a consumer
  requirement.
- Public routes and wire/storage representations remain compatible unless
  explicitly decided otherwise. Check keys, omitted/null distinctions,
  spelling/versions, equality/coalescing, digests/fingerprints, original
  identities, receipts, immutable history, enqueue generations, counters and
  deadlines. Do not silently merge `done`/`completed`.
- Database changes are atomic and deterministic; vocabulary changes preserve
  physical storage and constraints unless their migration is explicitly in
  scope. Check real readers/writers and transaction/dependency/trust ownership.
- Portal contracts stay provider-neutral across contours. Integration owns
  vendor DTOs, numeric symbols (`IntEnum` where appropriate), unknown handling
  and normalization; raw source values remain raw until their decoder.
  Opaque IDs, arbitrary codes/currencies, user text and quantities are not
  automatically enums, while recognized decision subsets need an owner.
- Backend → OpenAPI → generated frontend contracts and shared transport retain
  one wire authority. UI concepts use local symbols; backend wire enums are
  not hand-copied. Legal/locale/capability sources remain authoritative.
  Type-only frontend generation and existing runtime representation debt are
  reported honestly rather than claimed fixed by documentation.
- Changes have a current consumer/invariant benefit and use KISS/YAGNI and DRY
  for repeated knowledge. No speculative mechanism, broad cleanup, per-field
  waiver registry or blanket cast/suppression enters the diff. Bounded
  exceptions and unresolved owner decisions follow the conventions; routine
  reversible choices and already-approved decisions need no new approval.
- No unrelated behavior, generated output, legal content or unapproved program
  step changed. Checks record passed/failed/blocked/skipped/unreached accurately.
  Distinguish an enforcement gap, a reproduced defect and existing debt;
  neither additional classes nor a green suite proves an untested guarantee.
