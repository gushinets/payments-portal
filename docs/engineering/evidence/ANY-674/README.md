# ANY-674 evidence archive

The complete evidence is retained locally, **not uploaded**, by explicit user
instruction. Remote reviewers cannot download this local archive from the PR.
Request a copy from the technical owner when raw verification is needed.

- Source commit: `f81cb6d4340f88c56d8f5bb62f782edde7e2a537`.
- Local preservation branch: `codex/any-674-evidence-archive-20261123` (not pushed).
- Archive: `.harness/any-674-artifacts/ANY-674-evidence-f81cb6d4.tar.gz`.
- Size: 3,513,486 bytes; 155 original files, byte-verified against Git blobs.
- SHA-256: `d44ab5451da33bda874c228d0370713396bb55e2b5946423aab7653009628b37`.
- [Original per-file SHA-256 catalog](FILES-SHA256SUMS).
- [Before inventory](before-packages.tsv), [after inventory](after-packages.tsv).
- [101-ID comparison, applicability and next steps](advisory-comparison.csv).

The archive contains six evidence groups, seven reports and the original plan.
Their original SHA256SUMS and sanitized scan JSON are preserved unchanged.
Private diary, Agent.md, credentials, raw environment dumps and personal audit
files are excluded. Image tar archives and frozen scanner database remain in
their original local .harness directories; they are not inside this report bundle.

Verify after obtaining the archive:

```sh
sha256sum ANY-674-evidence-f81cb6d4.tar.gz
tar -xzf ANY-674-evidence-f81cb6d4.tar.gz -C /path/to/empty-directory
cd /path/to/empty-directory
sha256sum -c /path/to/FILES-SHA256SUMS
```

This is a normal deletion commit: heavy files leave the current PR tree/diff,
but remain in earlier Git commits. No history purge or force push is performed.
Historical reports are capture-time evidence, not current approval decisions.
