"""Development metadata projected from the existing manifest contract."""

from __future__ import annotations

from typing import Any


MANIFEST_SCHEMA_REF = "#/components/schemas/CapabilityManifest"
SWAGGER_ASSET_BASE = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.15"
SWAGGER_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SIMULATED Kernel manifest — Swagger UI</title>
  <link rel="stylesheet" href="{SWAGGER_ASSET_BASE}/swagger-ui.css">
</head>
<body>
  <p>SIMULATED development mock. Read-only documentation; manifest calls require
  service authentication and are not available through this browser UI.</p>
  <div id="swagger-ui"></div>
  <script src="{SWAGGER_ASSET_BASE}/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function () {{
      SwaggerUIBundle({{
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        supportedSubmitMethods: [],
        tryItOutEnabled: false,
        persistAuthorization: false,
        queryConfigEnabled: false,
        validatorUrl: null,
        withCredentials: false
      }});
    }};
  </script>
</body>
</html>
"""


def _schema_for_openapi(value: Any) -> Any:
    """Rebase document-local JSON Pointers into the embedded schema component."""
    if isinstance(value, list):
        return [_schema_for_openapi(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                MANIFEST_SCHEMA_REF + item[1:]
                if key == "$ref" and isinstance(item, str) and item.startswith("#")
                else _schema_for_openapi(item)
            )
            for key, item in value.items()
        }
    return value


def openapi_document(
    schema: dict[str, Any],
    fixture: dict[str, Any],
    manifest_path: str,
    scope: dict[str, str],
    test_offers: dict[str, Any],
) -> dict[str, Any]:
    manifest_schema = _schema_for_openapi(schema)
    # Use the implicit OAS 3.1 dialect, which includes the contract's 2020-12
    # keywords. Swagger UI does not support a different declared dialect.
    manifest_schema.pop("$schema", None)
    responses = {
        status: {
            "description": description,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MockError"},
                    "examples": {
                        code: {"value": {"detail": {"code": code}}} for code in codes
                    },
                }
            },
        }
        for status, description, codes in (
            (
                "401",
                "Missing or invalid configured service bearer token.",
                ("invalid_service_auth",),
            ),
            (
                "403",
                "Unauthorized tenant/region/scope or a browser Origin header.",
                ("scope_forbidden", "browser_access_forbidden"),
            ),
            (
                "503",
                "Producer cannot supply a complete valid manifest.",
                ("manifest_unavailable",),
            ),
        )
    }
    responses["401"]["headers"] = {
        "WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}
    }
    responses["200"] = {
        "description": (
            "Complete valid manifest. Invalid 200 bodies in corruption scenarios "
            "are deliberate fault injection, not conforming producer responses."
        ),
        "content": {
            "application/json": {
                "schema": {"$ref": MANIFEST_SCHEMA_REF},
                "example": fixture,
            }
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SIMULATED Kernel Capability Manifest mock",
            "version": "1.0.0",
            "description": (
                "Provisional development contract, not a delivered Kernel API or "
                "paid registry. Swagger is read-only. The manifest keeps its "
                "service-auth, exact-scope and browser-access restrictions. "
                "Manifest schema is projected from the versioned JSON Schema; "
                "enabled semantics, identity/reference uniqueness and semantic "
                "digest rules remain defined in the contract README.\n\n"
                "SIMULATED purchased allowances for Step 9 tests only. These "
                "quantities belong to accepted test-offer terms, not the "
                "Capability Manifest. No paid access or usage is implemented "
                "by this mock.\n\n"
                "| Product | Test metric | Purchased quantity per confirmed cycle |\n"
                "| --- | --- | --- |\n"
                + "\n".join(
                    f"| {offer['product_id']} | {offer['metric_key']} | {offer['quantity']} {offer['unit']} |"
                    for offer in test_offers["offers"]
                )
            ),
        },
        "x-simulated-purchase-examples": test_offers,
        "servers": [{"url": "/", "description": "Current development mock"}],
        "paths": {
            manifest_path: {
                "get": {
                    "operationId": "getCapabilityManifest",
                    "summary": "Read the complete simulated capability manifest",
                    "security": [{"KernelServiceBearer": []}],
                    "parameters": [
                        {
                            "name": name,
                            "in": "query",
                            "required": True,
                            "description": "Exact development deployment scope.",
                            "schema": {"type": "string", "enum": [value]},
                            "example": value,
                        }
                        for name, value in scope.items()
                    ],
                    "responses": responses,
                }
            }
        },
        "components": {
            "securitySchemes": {
                "KernelServiceBearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "Configured development service token. Provisional local "
                        "encoding; no token is embedded in this documentation."
                    ),
                }
            },
            "schemas": {
                "CapabilityManifest": manifest_schema,
                "MockError": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["detail"],
                    "properties": {
                        "detail": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["code"],
                            "properties": {"code": {"type": "string"}},
                        }
                    },
                },
            },
        },
    }
