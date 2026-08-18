# Legal Source Workflow

Status: authoritative process
Last verified: 2026-08-18

The files under `docs/legal/<contour>/<version>` are customer-facing legal
artifacts and are intentional exceptions to the engineering-English policy.
They may use the contour's language. The only existing tree is
`docs/legal/ru`. They are draft content until approved by counsel.

Do not add `eu` or `us` legal trees without legal-content authorization and a
contour-enablement ticket.

## Canonical representation

For hashing, read the Markdown as UTF-8, remove YAML frontmatter, normalize CRLF
to LF, trim surrounding whitespace, and calculate SHA-256 over the remaining
UTF-8 bytes. The checked `manifest.json` records metadata and the resulting
`sha256:<hex>` value.

Run:

```bash
python scripts/repo.py legal generate
python scripts/repo.py legal check
```

The generator updates the manifest plus backend/frontend generated registries.
Migration seed rows are fixed historical snapshots and are verified separately.

## Versioning

- Do not edit an approved or accepted version in place.
- Create a new dated directory for changed legal content.
- Obtain explicit legal review.
- Generate the manifest and application registries.
- Add a forward migration that deactivates the superseded version and inserts the
  new version.
- Verify that checkout requires acceptance of the new active version.

Current RU legal source version: `2026-07-11`.

The initial migration seeds version `2026-07-11`.
The `2026-07-02` directory is retained as historical draft source and is not
the active baseline.
