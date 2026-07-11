# Security Requirements

Status: authoritative
Last verified: 2026-07-11

## Sensitive data

Never collect, persist, or log full card data. Redact card-related provider
fields, raw session tokens, authorization headers, webhook secrets, passwords,
and private payment configuration before logging or tracing.

Email and IP data are personal data. Record them only where the documented legal
or security purpose requires them, and never add them to metric labels.

## Trust boundaries

- Validate HTTP, environment, webhook, and database-boundary data.
- Verify CloudPayments signatures before trusting provider state.
- Treat request IDs and provider metadata as untrusted input with length and
  character limits.
- Store session tokens only as hashes.
- Keep provider secrets in environment or a secret manager, never migrations,
  seed files, telemetry, or source control.

## High-risk review paths

Authentication, payments, legal sources and seeds, migrations, telemetry
redaction, production Compose, deployment configuration, and secret handling
require human review. Agents may prepare changes and evidence but may not merge
them autonomously.
