# Provisional Kernel Capability Manifest v1

Status: specification-derived development contract; SIMULATED fixtures.
Implementation: ANY-664 implementation Step 1 (part of ANY-504 program Step 6).
Verification: not run by the implementation agent; human verification pending.

This directory describes the documented manifest boundary and explicit local
conventions. It is not a Kernel-owned OpenAPI export, a delivered producer, a
paid metric registry or evidence of production approval. Portal runtime must
not import this directory or the mock. The eventual Portal HTTP client owns
its Integration-boundary validation independently; there is no shared runtime
schema package.

## Authority and provenance

The [accepted access-contract design](../../../superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md#capability-manifest)
defines the request, response fields, enabled semantics and service-auth/HTTP
requirements. Its researched source blob is
`c42e8b48a34506f9a68f174556dc01bd94eb9554`. The
[live-source amendment](../../../superpowers/specs/2026-10-15-live-source-commercial-admission-design-amendment.md)
changes source admission strategy, not manifest field names. It remains a
proposed production-policy amendment; the separately approved Portal-only
execution scope permits this provisional mock now.

Kernel identity evidence is pinned to commit
`079eb03e28d7a50b980795c63c3e4533b785d11f`, inspected read-only on
2026-10-15:

- [Platform composition](https://github.com/gushinets/anytoolai-platform/blob/079eb03e28d7a50b980795c63c3e4533b785d11f/apps/platform-api/src/anytoolai_platform_api/bootstrap.py)
  composes the Freelancer Suite and identifies `kernel_demo`.
- [Freelancer Suite bundle](https://github.com/gushinets/anytoolai-platform/blob/079eb03e28d7a50b980795c63c3e4533b785d11f/packages/backend/product-platforms/freelancer-suite/src/anytoolai_freelancer_suite/bundle.py)
  lists `proposal_ai`, `client_update_writer`, `brief_decoder`,
  `acceptance_builder` and `task_finder` product roots.
- [Selected ProposalAI product source](https://github.com/gushinets/anytoolai-platform/blob/079eb03e28d7a50b980795c63c3e4533b785d11f/packages/backend/product-platforms/freelancer-suite/src/anytoolai_freelancer_suite/products/proposal_ai/product.yaml)
  declares `product_id: proposal_ai`; blob
  `98449f0ec63fec742e443aeeb0556b1b8ce46368`. Its guest quota reference is
  not used to derive a paid metric or allowance.

These sources establish identity/composition only. They do not establish a
paid release, actual `ru` manifest deployment, approved production bearer
authentication or paid quantity. No Kernel checkout or runtime package is
needed by this mock.

## Request and complete response

```http
GET /internal/v1/capability-manifest?tenant_id=anytoolai&region=ru
Authorization: Bearer <configured development token>
```

[manifest.schema.json](manifest.schema.json) is a hand-authored JSON Schema
2020-12 description of a complete v1 response. In addition to structural
validation, require unique product IDs, unique metric keys, every metric's
product reference to exist, exact requested tenant/region and a correct
semantic digest. Validate timestamps as timezone-aware date-times. The schema
is not sufficient to prove those relationships or that a producer returned
its entire configured deployment.

The [complete positive fixture](fixtures/valid-manifest.json) declares a
six-product **test deployment**, not a partial copy of a live registry. Only
`proposal_ai` is enabled; all five other products, including `kernel_demo`,
are disabled. `proposal_ai.test_generations`, unit `generation`, is explicitly
**TEST-ONLY** and enabled for the positive example. It is not a real paid
metric. No price, allowance or commercial/legal approval is established by
this fixture.

`enabled` controls new bindings. Both the selected product and selected metric
must be enabled, with matching product identity. A later disablement does not
revoke historical paid access. A legitimate complete deployment may omit the
selected product/metric; that prevents a new binding without making the
manifest structurally invalid.

HTTP semantics remain: `200` for a complete valid manifest, `401` for absent or
invalid service authentication, `403` for unauthorized tenant/region/scope,
and `5xx` when a complete valid response cannot be produced. The mock's
`detail.code` error strings are local conventions, not a promised Kernel
error-body contract. Production requires TLS, service authentication and no
browser access. A user's login credentials are insufficient.

## Explicitly provisional conventions

- Local service auth is `Authorization: Bearer <KERNEL_MOCK_TOKEN>`, supplied
  at process startup. No default credential is supplied. This is not evidence
  of the eventual producer's credential format.
- The local schema rejects unknown fields and requires nonempty identities
  and units. Confirm compatibility, including extension handling, with the
  eventual Kernel-owned contract before real enablement.
- `manifest_version` is `sha256:` plus the lowercase SHA-256 hex digest of
  canonical UTF-8 JSON containing only `schema_version`, `tenant_id`,
  `region`, `products` and `usage_metrics`. Sort object keys recursively;
  sort products by `product_id` and metrics by `metric_key`; use compact
  separators with no whitespace and unescaped Unicode (`ensure_ascii=False`).
  Reject duplicate IDs/keys and invalid references before hashing. Exclude
  `generated_at` and `manifest_version` itself. This serialization must be
  reconciled with the eventual producer.

[valid-manifest.digest](fixtures/valid-manifest.digest) is the literal expected
digest, authored independently of mock/client execution. Focused test source
recomputes it independently, compares both the fixture and actual HTTP
response with it, and exercises semantic changes and timestamp/order
stability. The mock generates a current timestamp for each response while
retaining the same version for the same semantics.

Keep simulation metadata outside the Kernel response schema. These artifacts
are SIMULATED by provenance; a future mapping that uses any simulated source,
metric or approval must mark its entire versioned evidence SIMULATED. Real
publication/admission and production catalog reads must reject/exclude such
revisions, including after changing source URLs. A configuration change does
not upgrade a simulated revision into real approval. No mapping/runtime
implementation is added in Step 1.

## Standalone mock and startup scenarios

The [server](../../../../tools/kernel_manifest_mock/server.py) uses only the
Python standard library. It serves the manifest route, with exact
`anytoolai/ru` request scope, explicit development auth, no CORS, no control
API and no access logging, plus local documentation at `/docs` and
`/openapi.json`. The standard-library `ThreadingHTTPServer` handles requests
concurrently, so an in-flight delayed manifest request does not block either
documentation route. Connection timeouts and scenario delay bounds remain in
place; this is a small local fixture server, not a load emulator.

Start from the Portal repository root:

```bash
APP_ENV=development KERNEL_MOCK_TOKEN=local-kernel-test-only \
  ./.venv/bin/python -m tools.kernel_manifest_mock --port 8091 --scenario valid
```

`APP_ENV` must explicitly be `development` or `test`; production, missing or
other environments fail before binding. The default bind address is
`127.0.0.1`. The process prints a SIMULATED startup label without credentials.
The mock is not automatically started and has no Portal startup dependency.
Stop with Ctrl-C; restart with a different `--scenario` to select a case:

- `valid`: complete six-product positive fixture.
- `disabled-product`, `missing-product`, `disabled-metric`, `missing-metric`:
  complete alternate test deployments with fresh matching semantic versions.
  Missing product also removes its metrics to preserve reference validity.
- `unauthorized`, `forbidden`, `unavailable`: inject `401`, `403`, `503` after
  the normal route/auth checks, with no successful manifest body.
- `timeout`: delay a valid response by `--delay-seconds` (default 2 seconds;
  positive and at most 60). Set a shorter caller deadline to exercise timeout.
- `wrong-schema`, `malformed-json`, `partial`, `wrong-type`,
  `duplicate-product`, `duplicate-metric`, `invalid-reference`,
  `digest-mismatch`: deliberately invalid `200` responses. These are fault
  injection only, never conforming producer behavior.
- `wrong-tenant`, `wrong-region`: deliberately return the wrong response
  scope with an internally matching digest; the caller must reject scope.

Request parameters cannot change scenarios. Origin-bearing requests are
rejected, and unsupported routes/methods do not expose any management API.
Root Docker build inputs exclude the mock via `.dockerignore`; contract
fixtures are already excluded with non-legal `docs`. No Compose, Portal browser,
Portal client, production configuration or runtime integration is added here.

## Local Swagger UI and OpenAPI

The same HTTP server provides credential-free development metadata:

- `GET /docs` returns Swagger UI HTML.
- `GET /openapi.json` returns OpenAPI 3.1 for the actual
  `GET /internal/v1/capability-manifest`, including required `tenant_id` and
  `region`, exact local scope, service bearer security and
  `200`/`401`/`403`/`503` success/error bodies.

OpenAPI embeds [manifest.schema.json](manifest.schema.json) directly as its
manifest component and rebases its local JSON references into that component.
The projection omits the standalone `$schema` declaration and leaves
`jsonSchemaDialect` unset, using the [default OpenAPI 3.1 dialect](https://spec.openapis.org/oas/v3.1.1.html#specifying-schema-dialects)
supported by Swagger UI. The source schema and all its field constraints
remain unchanged.
It does not redeclare manifest fields or create a second contract. The
positive independent fixture supplies the example. Fault scenarios do not
change the documented valid schema or make metadata unavailable.

Swagger is read-only: no browser manifest execution, embedded service token,
persisted authorization or external schema validation. Manifest service auth,
exact scope and browser restrictions remain unchanged. No CORS is enabled
for documentation; ordinary same-origin browser navigation can view it.

The HTML loads pinned `swagger-ui-dist@5.32.15` CSS/JavaScript from jsDelivr;
the browser needs network access to that CDN to render Swagger UI. The Python
server makes no external asset requests, and `/openapi.json` works without
the CDN. See the upstream [pinned release](https://github.com/swagger-api/swagger-ui/releases/tag/v5.32.15)
and [Swagger UI configuration](https://swagger.io/docs/open-source-tools/swagger-ui/usage/configuration/).
Both documentation routes retain the mock's explicit development/test-only
startup and production build exclusions. Compose remains separate later work.

## Human verification and remaining ownership

From the Portal repository root, run:

```bash
./.venv/bin/python -m pytest -q apps/api/tests/test_kernel_manifest_mock.py
npm run architecture:check
npm run docs:check
```

With the mock running, check documentation in a second terminal:

```bash
curl --fail-with-body -i http://127.0.0.1:8091/docs
curl --fail-with-body -i http://127.0.0.1:8091/openapi.json
```

Both should return `200`, with HTML and JSON content types respectively and
no configured token in either response. Open
[local Swagger UI](http://127.0.0.1:8091/docs) in a browser. Confirm the
manifest operation, required `anytoolai/ru` parameters, bearer authentication,
complete success/error schemas and read-only controls. The focused test source
also compares the served OpenAPI component with the versioned JSON Schema
after restoring local references, resolves product/metric references and
checks metadata during injected manifest failures. Run it manually to verify
contract correspondence; no agent-run result is claimed.

To check documentation while a manifest request is actually delayed, restart
the mock in the first terminal with a longer timeout scenario:

```bash
APP_ENV=development KERNEL_MOCK_TOKEN=local-kernel-test-only \
  ./.venv/bin/python -m tools.kernel_manifest_mock --port 8091 \
  --scenario timeout --delay-seconds 10
```

Start the slow authenticated request in a second terminal:

```bash
curl --fail-with-body --max-time 15 \
  -H 'Authorization: Bearer local-kernel-test-only' \
  'http://127.0.0.1:8091/internal/v1/capability-manifest?tenant_id=anytoolai&region=ru'
```

While that request is still pending, use a third terminal:

```bash
curl --fail-with-body --max-time 2 -i http://127.0.0.1:8091/docs
curl --fail-with-body --max-time 2 -i http://127.0.0.1:8091/openapi.json
```

Both metadata routes should return `200` before the slow request completes.
The focused concurrency test uses a real authenticated HTTP manifest request
and events at its delay boundary: it confirms the handler is waiting, reads
both metadata routes through a separate client, and only then releases the
manifest request. It also checks that the released manifest completes with
a valid response, without relying on an arbitrary sleep to establish overlap.

With the standalone mock running, exercise `200`, `401` and `403`:

```bash
curl --fail-with-body -H 'Authorization: Bearer local-kernel-test-only' \
  'http://127.0.0.1:8091/internal/v1/capability-manifest?tenant_id=anytoolai&region=ru'
curl -i \
  'http://127.0.0.1:8091/internal/v1/capability-manifest?tenant_id=anytoolai&region=ru'
curl -i -H 'Authorization: Bearer local-kernel-test-only' \
  'http://127.0.0.1:8091/internal/v1/capability-manifest?tenant_id=other&region=ru'
```

Restart with `--scenario unavailable` and repeat the authenticated request
using `curl -i` to observe `503`. Restart with `--scenario timeout` and add
`--max-time 0.1` to the authenticated curl command to observe a read timeout.
The focused tests cover schema, references, literal digest, disabled/missing
capabilities and the other injected failures over HTTP. No PASS is claimed
until the human runs them.

ANY-664 completion concerns Portal outputs against this provisional contract.
Real Kernel producer delivery, production paid registry/release/quantity,
service-auth/scope deployment and actual producer conformance remain future
enablement gates. A compatible endpoint can later replace the mock through
URL/credentials; incompatible wire/hash/auth requires explicit Integration
boundary alignment first. No production sale or paid execution is authorized
by a local mock demonstration.

Separate owner synchronization is still needed for ANY-504 and ANY-664 Linear
wording that requires a real Kernel producer or actual-producer PASS before
Portal ticket completion. PR #138's remote description may need the same
ownership/DoD correction. This implementation changes only repository content;
it does not write to Linear/GitHub, add the implementation plan to PR #138,
or claim an upstream contract/drift check has passed.
