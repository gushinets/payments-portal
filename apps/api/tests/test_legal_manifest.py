from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LEGAL_ROOT = ROOT / "docs" / "legal" / "ru" / "2026-07-02"


def normalize_legal_markdown(raw: str) -> str:
    source = raw.replace("\r\n", "\n")
    if source.startswith("---"):
        closing = source.find("\n---", 3)
        if closing >= 0:
            source = source[closing + 4 :]
    return source.strip()


def test_legal_manifest_hashes_match_source() -> None:
    manifest = json.loads((LEGAL_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert len(manifest["documents"]) == 6
    for document in manifest["documents"]:
        source = (LEGAL_ROOT / document["file"]).read_text(encoding="utf-8")
        digest = hashlib.sha256(
            normalize_legal_markdown(source).encode("utf-8")
        ).hexdigest()
        assert document["contentHash"] == f"sha256:{digest}"
