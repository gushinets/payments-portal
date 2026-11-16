"""Run whole pytest modules in bounded processes using the existing environment."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING
from uuid import uuid4
import xml.etree.ElementTree as ET

if TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--collection-manifest", type=Path)


def pytest_collection_finish(session: pytest.Session) -> None:
    path = session.config.getoption("collection_manifest")
    if path is not None:
        # pytest shortens nodeids for paths outside rootdir (e.g. harness tests).
        nodeids = [
            str(item.path) + "::" + item.nodeid.split("::", 1)[1]
            for item in session.items
        ]
        path.write_text(json.dumps(nodeids), encoding="utf-8")


def read_manifest(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Invalid pytest collection manifest")
    return value


def partition_files(nodeids: list[str], workers: int) -> list[list[str]]:
    counts = Counter(nodeid.split("::", 1)[0] for nodeid in nodeids)
    groups: list[list[str]] = [[] for _ in range(min(workers, len(counts)))]
    weights = [0] * len(groups)
    for filename, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        index = min(range(len(groups)), key=weights.__getitem__)
        groups[index].append(filename)
        weights[index] += count
    return groups


def merge_junit(paths: list[Path], destination: Path) -> None:
    suites = ET.Element("testsuites")
    for path in paths:
        root = ET.parse(path).getroot()
        suites.extend([root] if root.tag == "testsuite" else list(root))
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(destination, encoding="utf-8", xml_declaration=True)


def stop_workers(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                # Give pytest a chance to close clients and drop its own databases.
                process.send_signal(signal.SIGINT)
    for process in processes:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_parallel(
    *,
    root: Path,
    test_path: str,
    marker: str | None,
    workers: int,
    artifacts: Path,
    junitxml: Path | None,
) -> int:
    if workers < 1:
        raise ValueError("workers must be positive")
    # This harness runs repository test partitions, not arbitrary pytest options.
    selection: list[str] = []
    if marker == "postgres":
        selection = ["-m", "postgres"]
    elif marker == "not postgres":
        selection = ["-m", "not postgres"]
    elif marker is not None:
        raise ValueError("Unsupported test partition")
    # pytest handles --version before parsing the option terminator.
    test_path = str((root / test_path).resolve())
    artifacts.mkdir(parents=True)
    common = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-p",
        "scripts.pytest_parallel",
        "-q",
        f"--rootdir={root}",
    ]
    manifest = artifacts / "collection.json"
    with (artifacts / "collection.log").open("w", encoding="utf-8") as output:
        collection = subprocess.run(
            [
                *common,
                *selection,
                "--collect-only",
                f"--collection-manifest={manifest}",
                f"--junitxml={artifacts / 'collection.xml'}",
                "--",
                test_path,
            ],
            cwd=root,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if collection.returncode:
        if junitxml is not None:
            collection_report = artifacts / "collection.xml"
            merge_junit(
                [collection_report] if collection_report.exists() else [], junitxml
            )
        print((artifacts / "collection.log").read_text(encoding="utf-8"), flush=True)
        return collection.returncode
    expected = read_manifest(manifest)
    groups = partition_files(expected, workers)
    print(
        f"Running {len(expected)} tests in {len(groups)} processes; logs: {artifacts}",
        flush=True,
    )
    processes: list[subprocess.Popen[bytes]] = []
    finished: set[int] = set()
    started = time.monotonic()
    try:
        for index, files in enumerate(groups):
            with (artifacts / f"worker-{index}.log").open(
                "w", encoding="utf-8"
            ) as output:
                processes.append(
                    subprocess.Popen(
                        [
                            *common,
                            *selection,
                            f"--basetemp={artifacts / f'tmp-{index}'}",
                            f"--collection-manifest={artifacts / f'worker-{index}.json'}",
                            f"--junitxml={artifacts / f'worker-{index}.xml'}",
                            "--",
                            *files,
                        ],
                        cwd=root,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                )
        while len(finished) < len(processes):
            for index, process in enumerate(processes):
                if index in finished or process.poll() is None:
                    continue
                finished.add(index)
                output = (artifacts / f"worker-{index}.log").read_text(encoding="utf-8")
                print(f"Worker {index}: exit {process.returncode}", flush=True)
                print(
                    output
                    if process.returncode
                    else "\n".join(output.splitlines()[-2:]),
                    flush=True,
                )
            if len(finished) < len(processes):
                time.sleep(0.2)
    finally:
        stop_workers(processes)

    actual: list[str] = []
    reports: list[Path] = []
    complete = True
    for index in range(len(processes)):
        worker_manifest = artifacts / f"worker-{index}.json"
        report = artifacts / f"worker-{index}.xml"
        if worker_manifest.exists() and report.exists():
            actual.extend(read_manifest(worker_manifest))
            reports.append(report)
        else:
            complete = False
    if junitxml is not None:
        merge_junit(reports, junitxml)
    if not complete or Counter(actual) != Counter(expected):
        print(
            "ERROR: incomplete worker reports or collection differs between processes",
            flush=True,
        )
        return 1
    print(
        f"Finished {len(expected)} tests in {time.monotonic() - started:.1f}s",
        flush=True,
    )
    return 1 if any(process.returncode for process in processes) else 0


def main() -> int:
    signal.signal(signal.SIGTERM, lambda signum, _: sys.exit(128 + signum))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--marker")
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("test_path")
    args = parser.parse_args()
    root = Path.cwd()
    return run_parallel(
        root=root,
        test_path=args.test_path,
        marker=args.marker,
        workers=args.workers,
        artifacts=root / ".harness" / "test-runs" / uuid4().hex,
        junitxml=args.junitxml,
    )


if __name__ == "__main__":
    raise SystemExit(main())
