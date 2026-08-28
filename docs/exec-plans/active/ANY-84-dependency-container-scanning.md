# ANY-84 Dependency and Container Scanning

Status: active
Started: 2026-08-12
Linear: ANY-84

## Objective

Detect vulnerable dependencies, committed secrets, Docker/Compose
misconfigurations, and vulnerabilities in the production API and web images on
every relevant repository change and on a weekly schedule.

## Decisions

- Dependabot tracks npm, uv through the `uv` ecosystem, Dockerfiles,
  Docker Compose, and GitHub Actions weekly.
- Dependabot PR titles use the `ANY-84 -` prefix so automated updates satisfy
  the repository title gate.
- The workflow uses the SHA-pinned Trivy action and an explicit Trivy version.
- A separate, schema-bound custom Trivy policy scan covers Docker Compose
  because Trivy's built-in misconfiguration scanner supports Dockerfiles but
  not Compose files. Separating raw YAML scanning preserves the built-in IaC
  adapters used by the filesystem scan.
- Filesystem vulnerability scanning includes development dependencies.
- Filesystem and image findings are written to JSON files and uploaded with
  14-day retention. Secret match and source-code fields are stripped before
  upload, and finding details are not printed by the workflow or enforcement
  helper.
- Initial runs are report-only. Setting the repository Actions variable
  `TRIVY_ENFORCE=true` activates the checked-in policy without another code
  change.
- Enforcement blocks every Critical vulnerability, every fixable High
  vulnerability, and every High or Critical secret or misconfiguration finding.
- Trivy exceptions remain empty. Future entries require an ID, path, reason, and
  expiration date in `.trivyignore.yaml`.

## Baseline

The local baseline used Trivy 0.70.0 with a vulnerability database refreshed on
2026-08-12. The workflow pins Trivy 0.72.0, so the first workflow artifact is the
authoritative baseline for approval.

| Target | Total vulnerabilities | Critical | Fixable High | Misconfigurations | Secrets |
|---|---:|---:|---:|---:|---:|
| Repository filesystem | 28 | 1 | 15 | 2 Low | 0 |
| Production API image | 190 | 4 | 0 | Not scanned | 0 |
| Production web image | 106 | 4 | 37 | Not scanned | 0 |

The web image includes vulnerable application and build-tool dependencies.
Dependency remediation is intentionally left to ANY-98 and ANY-99 rather than
mixing upgrades into the scanner rollout.

## Progress

- [x] Record a local filesystem and production-image baseline.
- [x] Add weekly Dependabot configuration for every used ecosystem.
- [x] Add pull request, `main`, weekly, and manual Trivy triggers.
- [x] Scan the filesystem and both production images.
- [x] Add Trivy checks for high-risk Docker Compose configuration.
- [x] Upload JSON reports without printing secret findings.
- [x] Redact secret values before retaining report artifacts.
- [x] Add and test the post-baseline enforcement policy.
- [ ] Enable Dependabot alerts in repository settings (administrator required).
- [ ] Review the first Trivy 0.72.0 workflow artifact and remediate the baseline.
- [ ] Set `TRIVY_ENFORCE=true` after human approval.

## Validation

- Trivy 0.70.0 accepted `.trivyignore.yaml` and the repository config.
- Custom Compose checks reported all four expected findings on an unsafe fixture
  and zero custom findings in the checked-in Compose files. The Docker socket
  fixture covers `/var/run/docker.sock` and `/run/docker.sock` in both short and
  long Compose syntax.
- Dedicated non-Compose Kubernetes YAML and JSON fixtures remain visible to
  Trivy's built-in misconfiguration scanner alongside the separate Compose
  policy scan.
- The enforcement helper rejected the measured baseline without printing
  finding details; focused gate, redaction, and ignore-policy tests passed
  (`8 passed`).
- Dependabot and workflow YAML parsed successfully; configuration options were
  reviewed against current GitHub and Trivy documentation.
- Final full canonical check passed outside the filesystem sandbox: 134 API
  tests, 9 web boundary tests, 25 web component tests, docs, architecture,
  lint, and the production web build. PostgreSQL integration and browser tests
  were skipped because their required database URL and running harness were not
  configured.
