# ANY-831 production image scan coverage

- Baseline: `49ed895d3925e097ef7e46908c87a6cb75f0fb26` has filesystem,
  Compose, API and web reports. The gate checks completeness only when
  enforcement is enabled. Existing tests cover the finding thresholds, secret
  redaction and both negative configuration fixtures.
- Add regression coverage for both production Compose image pins, malformed or
  missing inputs and reports, report-only completeness, finding thresholds and
  the sanitized upload boundary.
- Resolve the platform manifests from the Compose pins and scan both with the
  installed Trivy. Record the source revision, resolved image identities and
  report hashes alongside the sanitized reports.
- Verify focused and canonical checks, then validate the exact-revision
  security run and downloaded artifact. Group new findings by advisory and
  source package for remediation follow-up.
