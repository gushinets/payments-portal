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

## Dependency and container scanning

Dependabot checks npm, Poetry, Dockerfile, Docker Compose, and GitHub Actions
dependencies weekly. Repository administrators must keep Dependabot alerts and
security updates enabled in GitHub; those settings are not controlled by
`.github/dependabot.yml`.

The `Security scans` workflow scans the repository filesystem and both
production images on pull requests, pushes to `main`, a weekly schedule, and
manual dispatch. JSON reports are retained as workflow artifacts for 14 days.
Scans must write findings to reports instead of workflow logs. Secret match and
source-code fields are removed before upload so detected values are neither
printed nor retained in workflow artifacts.

Trivy's built-in Dockerfile checks are supplemented by repository-owned Compose
checks under `security/trivy`. They reject privileged services, host namespace
sharing, Docker socket mounts, and adding all Linux capabilities.

The initial rollout is report-only while the baseline is remediated. After human
approval, set the repository Actions variable `TRIVY_ENFORCE=true`. The checked-in
gate then rejects all Critical vulnerabilities, fixable High vulnerabilities,
and High or Critical secret and misconfiguration findings. Exceptions belong in
`.trivyignore.yaml` and must include an ID, affected paths, an actionable reason,
and an expiration date.
