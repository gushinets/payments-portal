#!/usr/bin/env python3
"""Collect read-only component evidence inside the final API image, offline."""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import ssl
import stat
import struct
import subprocess
import sys
from pathlib import Path


COMMANDS = (
    "bzip2recover bzip2 getfattr setfattr getfacl setfacl chacl infocmp tic captoinfo "
    "dpkg-source dpkg-deb dpkg tar rmt rmt-tar nscd iconv localedef locale openssl "
    "systemd-journald systemd-tmpfiles systemd-oomd systemd-homed journalctl homectl "
    "perl ptar pod2text login su chfn chsh mount umount nsenter unshare wall write "
    "sulogin init pidof mesg lslogins logger newuidmap newgidmap sort uniq unexpand diff3 "
    "bash dash sh cp mv install touch chown chgrp chmod rm"
).split()
MODULE_PATHS = (
    "Archive/Tar.pm",
    "File/Temp.pm",
    "Pod/Text.pm",
    "Dpkg/Source/Package/V3/Quilt.pm",
)
LIBRARIES = {
    "c": [
        "glob",
        "glob64",
        "fnmatch",
        "iconv",
        "regexec",
        "swscanf",
        "strfmon",
        "tdelete",
        "ns_printrrf",
        "ns_sprintrr",
        "fp_nquery",
        "fp_query",
        "wordexp",
        "getaddrinfo",
        "gettext",
        "strncasecmp",
    ],
    "acl": ["acl_get_file", "acl_set_file", "acl_extended_file", "acl_delete_def_file"],
    "attr": ["attr_copy_file", "attr_copy_fd"],
    "bz2": ["BZ2_bzDecompress", "BZ2_bzReadOpen"],
    "systemd": ["sd_journal_open", "sd_journal_open_files", "sd_journal_next"],
    "ssl": [
        "SSL_CTX_set1_groups_list",
        "SSL_CTX_dane_enable",
        "DTLS_method",
        "DTLS_client_method",
        "SSL_CTX_set_cipher_list",
    ],
    "crypto": ["PEM_read_bio_PrivateKey", "CMS_verify", "EVP_CIPHER_fetch"],
    "sqlite3": [
        "sqlite3session_create",
        "sqlite3changeset_apply",
        "sqlite3changeset_apply_v2",
        "sqlite3changeset_apply_v3",
        "sqlite3changeset_concat",
        "sqlite3changegroup_add",
        "sqlite3_zipfile_init",
    ],
    "stdc++": ["_ZnwmSt11align_val_t", "_ZnamSt11align_val_t"],
}


def elf_dynamic_info(data: bytes) -> dict[str, object] | None:
    """Read ELF64 dynamic references without executing the inspected object."""
    if data[:4] != b"\x7fELF":
        return None
    if data[4:6] != b"\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 62:
        raise ValueError("Evidence collector requires little-endian x86-64 ELF")
    offset = struct.unpack_from("<Q", data, 40)[0]
    size, count, index = struct.unpack_from("<HHH", data, 58)
    if size != 64 or not count or index == 65535 or offset + size * count > len(data):
        raise ValueError("Unsupported or truncated ELF section table")
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, offset + n * size) for n in range(count)
    ]

    def contents(section: tuple[int, ...]) -> bytes:
        if section[4] + section[5] > len(data):
            raise ValueError("Truncated ELF section")
        return data[section[4] : section[4] + section[5]]

    def string(table: bytes, start: int) -> str:
        return table[start:].split(b"\0", 1)[0].decode(errors="replace")

    needed: list[str] = []
    rpath: list[str] = []
    runpath: list[str] = []
    undefined: list[str] = []
    exported: list[str] = []
    for section in sections:
        if section[1] not in (6, 11):
            continue
        strings = contents(sections[section[6]])
        payload = contents(section)
        if section[1] == 6:
            for n in range(0, len(payload), section[9] or 16):
                tag, value = struct.unpack_from("<qQ", payload, n)
                target = {1: needed, 15: rpath, 29: runpath}.get(tag)
                if target is not None:
                    target.append(string(strings, value))
        else:
            for n in range(0, len(payload), section[9] or 24):
                name, info, other, section_index, _, _ = struct.unpack_from(
                    "<IBBHQQ", payload, n
                )
                if name and section_index == 0:
                    undefined.append(string(strings, name))
                elif name and info >> 4 in (1, 2) and other & 3 in (0, 3):
                    exported.append(string(strings, name))
    return {
        "needed": needed,
        "rpath": rpath,
        "runpath": runpath,
        "undefined_symbols": undefined,
        "exported_symbols": exported,
    }


def command_result(argv: list[str], timeout: int = 20) -> dict[str, object]:
    """Retain execution errors as errors, never as evidence of component absence."""
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
        return {
            "argv": argv,
            "exit": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "execution_error": type(exc).__name__}


def collect_files(roots: list[Path]) -> tuple[list[str], list[str]]:
    """Enumerate roots without following directory symlinks; expose incomplete traversal."""
    files: set[str] = set()
    errors: list[str] = []

    def on_error(exc: OSError) -> None:
        errors.append(f"{type(exc).__name__}: {exc.filename}")

    for root in roots:
        for directory, names, leaves in os.walk(
            root, followlinks=False, onerror=on_error
        ):
            files.update(str(Path(directory) / name) for name in leaves)
            files.update(
                str(Path(directory) / name)
                for name in names
                if (Path(directory) / name).is_symlink()
            )
    return sorted(files), errors


def file_evidence(path: Path) -> dict[str, object]:
    """Record identity and ownership of a selected existing component."""
    result: dict[str, object] = {"path": str(path)}
    try:
        meta = path.lstat()
        result.update(
            {
                "mode": oct(stat.S_IMODE(meta.st_mode)),
                "uid": meta.st_uid,
                "gid": meta.st_gid,
                "size": meta.st_size,
            }
        )
        if path.is_symlink():
            result["symlink_target"] = os.readlink(path)
        elif path.is_file():
            result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["package_owner"] = command_result(["dpkg-query", "-S", str(path)])
    except OSError as exc:
        result["inspection_error"] = type(exc).__name__
    return result


def collect() -> dict[str, object]:
    """Inspect installed components and configuration without attacks or network access."""
    paths, errors = collect_files(
        [Path(p) for p in ("/usr", "/opt", "/app", "/etc/pam.d")]
    )
    selected = [
        p
        for p in paths
        if Path(p).name in COMMANDS
        or any(p.endswith(suffix) for suffix in MODULE_PATHS)
        or re.search(r"/(pam_userdb|pam_systemd_home|libtic).*\.so", p)
        or ("/gconv/" in p and p.endswith(".so"))
    ]
    inventory = command_result(
        [
            "dpkg-query",
            "-W",
            "-f=${binary:Package}\t${Version}\t${source:Package}\t"
            "${source:Version}\t${Essential}\t${Protected}\n",
        ]
    )
    if inventory.get("exit") != 0:
        errors.append("Package inventory command failed")
    libs: dict[str, object] = {}
    for name, symbols in LIBRARIES.items():
        soname = ctypes.util.find_library(name)
        entry: dict[str, object] = {"soname": soname}
        if soname:
            try:
                library = ctypes.CDLL(soname)
                entry["exported_symbols"] = {s: hasattr(library, s) for s in symbols}
            except OSError as exc:
                entry["load_error"] = type(exc).__name__
        libs[name] = entry
    elf_objects = []
    for name in paths:
        try:
            path = Path(name)
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as stream:
                prefix = stream.read(4)
                if prefix != b"\x7fELF":
                    continue
                data = prefix + stream.read()
            details = elf_dynamic_info(data)
            elf_objects.append(
                {
                    "path": name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    **(details or {}),
                }
            )
        except (OSError, ValueError, struct.error) as exc:
            errors.append(f"ELF inspection {type(exc).__name__}: {name}")
    native = []
    for name in paths:
        if (
            (name.startswith("/opt/api-venv/") or "/lib-dynload/" in name)
            and name.endswith(".so")
            and not Path(name).name.startswith("_tkinter")
        ):
            result = command_result(["ldd", name])
            native.append(result)
            if result.get("exit") != 0 or "not found" in str(result.get("stdout", "")):
                errors.append(f"Incomplete native dependency inspection: {name}")
    pam_lines = []
    for name in paths:
        if name.startswith("/etc/pam.d/") or name == "/etc/pam.conf":
            try:
                for line in Path(name).read_text().splitlines():
                    stripped = line.strip()
                    if (
                        stripped
                        and not stripped.startswith("#")
                        and "pam_userdb" in stripped
                    ):
                        # Record only the module and vulnerability-relevant boolean option.
                        pam_lines.append(
                            {
                                "file": name,
                                "module": "pam_userdb",
                                "crypt_none": "crypt=none" in stripped,
                            }
                        )
            except OSError as exc:
                errors.append(f"PAM inspection {type(exc).__name__}: {name}")
    privileged = []
    capability_files = []
    for name in paths:
        path = Path(name)
        try:
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                try:
                    capability = os.getxattr(path, "security.capability")
                    capability_files.append(
                        {"path": name, "capability_hex": capability.hex()}
                    )
                except OSError as exc:
                    if exc.errno not in (errno.ENODATA, errno.ENOTSUP):
                        errors.append(
                            f"Capability inspection {type(exc).__name__}: {name}"
                        )
            if stat.S_ISREG(mode) and mode & (stat.S_ISUID | stat.S_ISGID):
                privileged.append(file_evidence(path))
        except OSError as exc:
            errors.append(f"File mode inspection {type(exc).__name__}: {name}")
    perl = {
        module: command_result(
            [
                "perl",
                f"-M{module}",
                "-e",
                "print $INC{q{" + module.replace("::", "/") + ".pm}}; print qq{\\n};",
            ]
        )
        for module in ("Archive::Tar", "File::Temp", "Pod::Text")
    }
    bundled_crypto = []
    try:
        import psycopg  # noqa: F401 -- loads the locked wheel's native dependencies, no connection
    except ImportError as exc:
        errors.append(f"Required psycopg import failed: {type(exc).__name__}")
    for item in elf_objects:
        name = str(item["path"])
        if "psycopg_binary.libs/" not in name or not Path(name).name.startswith(
            ("libssl", "libcrypto")
        ):
            continue
        result = {"path": name, "sha256": item["sha256"]}
        try:
            library = ctypes.CDLL(name)
            version = library.OpenSSL_version
            version.argtypes = [ctypes.c_int]
            version.restype = ctypes.c_char_p
            result["version"] = version(0).decode()
        except (OSError, AttributeError) as exc:
            result["inspection_error"] = type(exc).__name__
            errors.append(f"Bundled OpenSSL version inspection failed: {name}")
        bundled_crypto.append(result)
    login_flags = {}
    for line in Path("/etc/login.defs").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in (
            "LOG_UNKFAIL_ENAB",
            "SUB_UID_MIN",
            "SUB_UID_MAX",
            "SUB_GID_MIN",
            "SUB_GID_MAX",
        ):
            login_flags[fields[0]] = fields[1]
    selected_files = [file_evidence(Path(p)) for p in selected]
    for item in selected_files + privileged:
        if "inspection_error" in item:
            errors.append(f"Incomplete component identity: {item['path']}")
    audit = command_result(["dpkg", "--audit"])
    if audit.get("exit") != 0 or audit.get("stdout"):
        errors.append("Package audit failed or not clean")
    return {
        "schema_version": 1,
        "uid": os.getuid(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "openssl_python": ssl.OPENSSL_VERSION,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_modules": [
            r[0] for r in sqlite3.connect(":memory:").execute("PRAGMA module_list")
        ],
        "filesystem_encoding": sys.getfilesystemencoding(),
        "bundled_openssl": bundled_crypto,
        "sqlite_compile_options": [
            r[0] for r in sqlite3.connect(":memory:").execute("PRAGMA compile_options")
        ],
        "python_ssl_has_dtls": any("DTLS" in name for name in dir(ssl)),
        "package_inventory": inventory,
        "package_audit": audit,
        "command_lookup": {name: shutil.which(name) for name in COMMANDS},
        "traversal_roots": ["/usr", "/opt", "/app", "/etc/pam.d"],
        "traversed_paths": len(paths),
        "selected_files": selected_files,
        "privileged_files": privileged,
        "capability_files": capability_files,
        "libraries": libs,
        "native_dependencies": native,
        "elf_objects": elf_objects,
        "perl_module_checks": perl,
        "pam_userdb_configurations": pam_lines,
        "login_configuration_flags": login_flags,
        "openssl_features": command_result(["openssl", "list", "-disabled"]),
        "openssl_providers": command_result(["openssl", "list", "-providers"]),
        "openssl_ciphers": command_result(["openssl", "list", "-cipher-algorithms"]),
        "distribution_versions": {
            d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
        },
        "collection_errors": errors,
        "complete": not errors,
        "scope_note": "Component evidence, not an exploitability or deployment-risk decision. "
        "Missing exported symbols do not exclude inline/static code; file absence requires complete traversal.",
    }


if __name__ == "__main__":
    evidence = collect()
    print(json.dumps(evidence, indent=2, sort_keys=True))
    sys.exit(0 if evidence["complete"] else 1)
