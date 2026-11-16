# Local Windows canonical verification fixes

Issue: https://linear.app/paveldik/issue/ANY-743

## Scope

The owner extended the OpenTelemetry work to remove the local verification
limitations and make the three canonical commands pass on this Windows machine.
Starting implementation: `d36065c5da39c505e13e3fc4f605b39f78bea373`.
No production application, dependency, billing contract or schema change is
intended. Existing local services are preserved; PostgreSQL verification uses the
worktree-specific disposable Compose project.

## Reproduced causes and changes

- [x] Uvicorn startup: the first half-second connection probe raises
  `httpx2.ConnectTimeout` on this Windows host before the listener is ready. The
  readiness loop previously retried only `ConnectError`. The unchanged test
  failed; a diagnostic retry reached HTTP 200. A deterministic injected-timeout
  regression failed before the fix. Retry both connection outcomes within the
  existing 10-second deadline, retaining process cleanup and response assertions.
  Original smoke and injected-timeout regression: two passed.
- [x] Private-path checks: POSIX st_mode does not express Windows ACLs. Retain the
  POSIX check and inspect protected Windows ACLs through native security APIs,
  rejecting ordinary-user grants while allowing owner, SYSTEM and administrators.
  Positive/negative file and directory regressions pass. Explicit exposed POSIX
  fixture modes make the negative checks independent of umask.
- [x] Joint-runtime private env files: chmod alone leaves Windows inheritance
  intact. A real ACL assertion reproduced the gap. Reuse the existing protected
  runtime-env writer, which protects the empty temporary file before writing
  secrets. Preserve the documented direct-script invocation. Five affected
  privacy cases and the direct CLI help check passed.
- [x] Retained contract bytes: core.autocrlf converted canonical LF bytes to CRLF,
  causing SHA256SUMS mismatch. Add focused LF checkout attributes for contract
  artifacts and generated API contracts. Existing files were verified clean,
  backed up, and restored from exact Git blobs only after asserting CRLF-only
  differences. No retained fixture/schema content change. Hash and generation
  freshness checks pass.
- [x] Source encoding: the Windows legacy locale raised UnicodeDecodeError in an
  architecture source scan. Canonical subprocesses now use PYTHONUTF8=1. A real
  subprocess regression under a deliberately legacy locale failed before the
  fix and passed afterward. Existing canonical environment assertions pass.
- [x] Shared-budget timing test: a 10ms cleanup reserve races the Windows
  scheduler. Advance only the preflight budget clock deterministically; keep the
  asyncio clock real and use a scheduler-safe synthetic cleanup reserve. The
  test still asserts cumulative nonrenewable budget exhaustion. Production
  deadlines and timeout handling are unchanged. Focused case passes.
- [x] Independent reviews: corrected the negative-fixture umask assumption;
  subsequent review found no actionable issues or weakened assertions.

## Final verification

- [ ] `npm run test:api:fast`
- [ ] `npm run check:fast`
- [ ] `npm run check`, including production web build and PostgreSQL tests
- [ ] Final diff/privacy review and PR evidence update

The full fast suite is running without fail-fast so remaining independent local
failures can be collected together. Initial stopped runs are diagnostic failures,
not completed verification. Final counts and results will be recorded below.

## Additional full-suite findings

- Deployment shell tests selected the WSL bash launcher on Windows. Canonical
  Windows checks now prefer the installed native Git Bash, and the tests resolve
  its executable explicitly (Windows CreateProcess otherwise searches System32
  before PATH). Shell fixtures use LF. The fake command directory is prepended
  inside Bash after MSYS initialization so the curl/docker/python stubs retain
  priority. All 41 deployment cases pass; no production shell logic changed.
- The real trickling peer exposed CPython 3.12.10 Windows Proactor reset handling:
  ConnectionResetError escaped its connection-lost callback and server shutdown
  never completed. The test peer now uses bounded stdlib threaded HTTP serving;
  the real asynchronous client, repeated read progress, absolute-deadline error,
  elapsed upper bound, resource counts and peer-close assertions remain enabled.
  Fixture shutdown is explicit and bounded, including failure paths.
- Additional retry/lock-wait tests had 10ms cleanup reserves. Only their
  synthetic timings were expanded while keeping retry delay beyond the work
  deadline, safe timeout assertions and zero released resource counts.
- Combined Kernel/LBX network and deployment selection: **257 passed**.
