from __future__ import annotations

import importlib.util
import struct
import subprocess
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


def test_upgrade_probe_distinguishes_planned_changes_from_summary() -> None:
    spec = importlib.util.spec_from_file_location("inspect_api_updates", ROOT / "security/trivy/inspect-api-updates.py")
    assert spec is not None and spec.loader is not None
    updates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updates)

    assert updates.planned_upgrades("0 upgraded, 0 newly installed.\n") == []
    assert updates.planned_upgrades("Inst libc6 [old] (new Debian)\n1 upgraded\n") == ["Inst libc6 [old] (new Debian)"]


def test_removal_evidence_only_simulates_and_never_forces(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def inspect(argv: list[str]) -> dict[str, object]:
        calls.append(argv)
        return {"exit": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(COMPONENTS, "command_result", inspect)
    monkeypatch.setattr(COMPONENTS.os, "getuid", lambda: 0, raising=False)
    evidence = COMPONENTS.collect_removal_options()

    assert evidence["complete"] is True
    removals = calls[1:]
    assert len(removals) == len(COMPONENTS.REMOVAL_CANDIDATES)
    assert all(argv[:3] == ["dpkg", "--simulate", "--purge"] and len(argv) == 4 for argv in removals)
    assert all(not arg.startswith("--force") for argv in calls for arg in argv)


def test_control_recipe_only_removes_three_privilege_overrides() -> None:
    import difflib

    spec = importlib.util.spec_from_file_location("inspect_api_updates", ROOT / "security/trivy/inspect-api-updates.py")
    assert spec is not None and spec.loader is not None
    updates = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updates)
    original = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    control = updates.make_setid_control(original)
    changes = [line for line in difflib.ndiff(original.splitlines(), control.splitlines()) if line[:2] in ("- ", "+ ")]

    assert len(changes) == 3
    assert all(line.startswith("- ") and "dpkg-statoverride --update --add" in line for line in changes)
    with pytest.raises(ValueError, match="exactly"):
        updates.make_setid_control(control)


def test_control_cli_rejects_arbitrary_input_and_output_paths(tmp_path: Path) -> None:
    output = tmp_path / "external-control.Dockerfile"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "security/trivy/inspect-api-updates.py"),
            "--baseline-dockerfile",
            str(ROOT / "apps/api/Dockerfile"),
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert not output.exists()
