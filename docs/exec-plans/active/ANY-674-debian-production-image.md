# ANY-674 — Debian production-image execution plan

Ticket: https://linear.app/paveldik/issue/ANY-674

The full historical plan is preserved in the [local evidence archive](../../engineering/evidence/ANY-674/README.md).
See the [technical summary](../../engineering/ANY-674-high-remediation-followup.md).

- [x] Characterize baseline, supported updates, minimization and all101 IDs.
- [x] Apply supported updates; verify runtime, native dependencies and migrations.
- [x] Reconcile ANY-831 security workflow and verify f81cb6d4 hosted CI/security.
- [x] Preserve155 exact source files on local archive branch and checksum archive.
- [x] Remove bulky reports from current PR tree; retain comparison and hash catalog.
- [x] Verify archive roundtrip155 files,101 comparison rows, documentation links and PR metadata.
- [ ] Observe exact new-head CI after the documentation-only commit.
- [ ] Reviewer acceptance and any separately authorized scoped decisions remain pending.

Coverage assessment: artifact relocation changes documentation/evidence storage only;
existing runtime/deployment tests remain valid. Verify archive roundtrip and every
file hash, documentation links, resulting diff, and PR metadata. Do not rerun image
builds to manufacture historical evidence. No merge/deployment or policy exception.
