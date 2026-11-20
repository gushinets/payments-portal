from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "inspect_api_components", ROOT / "security/trivy/inspect-api-components.py"
)
assert SPEC is not None and SPEC.loader is not None
COMPONENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPONENTS)


def test_component_command_failure_is_not_reported_as_absence() -> None:
    result = COMPONENTS.command_result(
        [sys.executable, "-c", "import sys; sys.stderr.write('inspection failed'); sys.exit(2)"]
    )

    assert result["exit"] == 2
    assert result["stdout"] == ""
    assert result["stderr"] == "inspection failed"


def test_component_missing_inspector_records_execution_error(tmp_path: Path) -> None:
    result = COMPONENTS.command_result([str(tmp_path / "missing-inspector")])

    assert result["execution_error"] == "FileNotFoundError"
    assert "exit" not in result


def test_component_traversal_reports_unreadable_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied_walk(root: Path, *, followlinks: bool, onerror: object) -> list:
        assert followlinks is False
        assert callable(onerror)
        onerror(PermissionError(13, "Permission denied", str(root / "unreadable")))
        return []

    monkeypatch.setattr(COMPONENTS.os, "walk", denied_walk)
    paths, errors = COMPONENTS.collect_files([Path("/fixture")])

    assert paths == []
    assert errors == [f"PermissionError: {Path('/fixture') / 'unreadable'}"]


def test_component_traversal_includes_nested_files(tmp_path: Path) -> None:
    child = tmp_path / "library" / "component.so"
    child.parent.mkdir()
    child.write_bytes(b"fixture")

    paths, errors = COMPONENTS.collect_files([tmp_path])

    assert paths == [str(child)]
    assert errors == []


def test_component_elf_decoder_reads_actual_dynamic_needed_record() -> None:
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", header, 18, 62)
    struct.pack_into("<Q", header, 40, 64)
    struct.pack_into("<HHH", header, 58, 64, 3, 0)
    strings = b"\0libc.so.6\0"
    dynamic = struct.pack("<qQqQ", 1, 1, 0, 0)

    def section(kind: int, offset: int, size: int, link: int, entry: int) -> bytes:
        return struct.pack("<IIQQQQIIQQ", 0, kind, 0, 0, offset, size, link, 0, 0, entry)

    data = (
        bytes(header)
        + bytes(64)
        + section(3, 256, len(strings), 0, 0)
        + section(6, 256 + len(strings), len(dynamic), 1, 16)
        + strings
        + dynamic
    )

    assert COMPONENTS.elf_dynamic_info(data)["needed"] == ["libc.so.6"]
    assert COMPONENTS.elf_dynamic_info(b"not an ELF") is None
    with pytest.raises(ValueError, match="x86-64"):
        invalid = bytearray(data)
        struct.pack_into("<H", invalid, 18, 183)
        COMPONENTS.elf_dynamic_info(bytes(invalid))
    with pytest.raises(ValueError, match="truncated"):
        COMPONENTS.elf_dynamic_info(data[:80])
