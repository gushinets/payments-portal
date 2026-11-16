"""Verify actual private-path protection on POSIX and Windows test hosts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def assert_private_path(path: Path) -> None:
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
        return
    # Windows st_mode does not describe ACLs. Inspect the real access rules,
    # including inherited grants, instead of weakening the privacy assertion.
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            """
$ErrorActionPreference = 'Stop'
if ([System.IO.Directory]::Exists($env:PAYMENTS_TEST_PRIVATE_PATH)) {
    $acl = [System.IO.Directory]::GetAccessControl($env:PAYMENTS_TEST_PRIVATE_PATH)
} else {
    $acl = [System.IO.File]::GetAccessControl($env:PAYMENTS_TEST_PRIVATE_PATH)
}
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted = @($current, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-4')
if (-not $acl.AreAccessRulesProtected) { exit 1 }
$rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
$allowed = @($rules | Where-Object { $_.AccessControlType -eq 'Allow' })
if ($allowed.Count -eq 0) { exit 2 }
if (@($allowed | Where-Object { $_.IdentityReference.Value -notin $trusted }).Count -ne 0) { exit 3 }
""",
        ],
        env={**os.environ, "PAYMENTS_TEST_PRIVATE_PATH": str(path)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, (
        "Path must have protected ACLs granting access only to the owner, SYSTEM and administrators"
    )
