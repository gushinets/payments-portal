"""Bounded stdlib subprocess execution with checked collections and retained reports."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypedDict


DEFAULT_POSTGRES_WORKERS = 4
CLEANUP_GRACE_SECONDS = 15
TERMINATE_GRACE_SECONDS = 5


class RunnerError(RuntimeError):
    pass


class Partition(StrEnum):
    FAST = "not postgres"
    POSTGRES = "postgres"


class Manifest(TypedDict):
    nodeids: list[str]
    exit_code: int


@dataclass(frozen=True)
class PytestArguments:
    options: list[str]
    selectors: list[str]


@dataclass(frozen=True)
class Invocation:
    command: list[str]
    directory: Path


@dataclass(frozen=True)
class RunnerResult:
    returncode: int
    directory: Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path, returncode: int) -> Manifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError(f"Missing or invalid manifest: {path}") from exc
    if (
        not isinstance(value, dict)
        or type(value.get("exit_code")) is not int
        or value["exit_code"] != returncode
        or not isinstance(value.get("nodeids"), list)
        or any(
            not isinstance(node, str) or "::" not in node for node in value["nodeids"]
        )
        or len(set(value["nodeids"])) != len(value["nodeids"])
    ):
        raise RunnerError(f"Invalid collection/exit code in manifest: {path}")
    return Manifest(nodeids=value["nodeids"], exit_code=value["exit_code"])


def partition_modules(nodeids: Sequence[str], workers: int) -> list[list[str]]:
    """Assign largest modules first, with stable ties and original module/case order."""
    modules: dict[str, list[str]] = {}
    for node in nodeids:
        modules.setdefault(node.split("::", 1)[0], []).append(node)
    buckets: list[list[str]] = [[] for _ in range(min(workers, len(modules)))]
    sizes = [0] * len(buckets)
    assignment: dict[str, int] = {}
    for module, cases in sorted(modules.items(), key=lambda entry: -len(entry[1])):
        index = min(range(len(buckets)), key=lambda i: sizes[i])
        assignment[module] = index
        sizes[index] += len(cases)
    for module, cases in modules.items():
        buckets[assignment[module]].extend(cases)
    return buckets


def validate_arguments(
    arguments: Sequence[str], target: str, root: Path
) -> PytestArguments:
    """Accept selectors and diagnostic flags, never scheduler/report/config overrides."""
    options: list[str] = []
    selectors: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-k", "-m", "--durations"}:
            if index + 1 == len(arguments):
                raise RunnerError(f"Missing value for {argument}")
            value = arguments[index + 1]
            if argument == "-m":
                expected = {
                    "api-fast": Partition.FAST,
                    "api-postgres": Partition.POSTGRES,
                }.get(target)
                if expected is None or value != expected:
                    raise RunnerError(
                        "Only the target's exact marker partition is supported"
                    )
                index += 2
                continue
            if argument == "--durations" and not value.isdecimal():
                raise RunnerError("--durations requires a nonnegative integer")
            options.extend([argument, value])
            index += 2
            continue
        if argument in {
            "-q",
            "-v",
            "-vv",
            "-s",
            "-ra",
            "-x",
            "--disable-warnings",
            "--tb=short",
            "--tb=long",
            "--tb=auto",
        }:
            options.append(argument)
        elif (
            argument.startswith("--durations=")
            and argument.split("=", 1)[1].isdecimal()
        ):
            options.append(argument)
        elif argument.startswith(("-", "@")) or "\n" in argument or "\r" in argument:
            raise RunnerError(f"Unsupported pytest argument: {argument}")
        else:
            file, *node = argument.split("::", 1)
            path = (root / file).resolve()
            tests = (root / "apps/api/tests").resolve()
            if (
                not path.is_relative_to(tests)
                or not path.exists()
                or (path.is_file() and path.suffix != ".py")
            ):
                raise RunnerError(
                    "Test selectors must reference existing Python tests under apps/api/tests"
                )
            selectors.append(
                path.relative_to(root).as_posix() + ("::" + node[0] if node else "")
            )
        index += 1
    return PytestArguments(options, selectors)


@contextmanager
def interrupt_on_termination() -> Iterator[None]:
    def interrupted(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def signal_process(process: subprocess.Popen[bytes], signum: int) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            if signum == signal.SIGINT:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        else:
            os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def stop_processes(processes: Sequence[subprocess.Popen[bytes]]) -> bool:
    """Give pytest SIGINT time to tear down owned fixtures before escalating."""
    forced = False
    for signum, grace in (
        (signal.SIGINT, CLEANUP_GRACE_SECONDS),
        (signal.SIGTERM, TERMINATE_GRACE_SECONDS),
    ):
        for process in processes:
            signal_process(process, signum)
        deadline = time.monotonic() + grace
        for process in processes:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                forced = True
        if all(process.poll() is not None for process in processes):
            return forced
    for process in processes:
        if process.poll() is None:
            if os.name == "nt":
                process.kill()
            else:
                signal_process(process, signal.SIGKILL)
    for process in processes:
        process.wait()
    return True


def execute(
    invocations: Sequence[Invocation], root: Path, environment: dict[str, str]
) -> list[int]:
    processes: list[subprocess.Popen[bytes]] = []
    with ExitStack() as stack:
        try:
            for invocation in invocations:
                log = stack.enter_context(
                    (invocation.directory / "pytest.log").open("wb")
                )
                processes.append(
                    subprocess.Popen(
                        invocation.command,
                        cwd=root,
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name != "nt",
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                        if os.name == "nt"
                        else 0,
                    )
                )
            return [process.wait() for process in processes]
        except BaseException:
            # A second Ctrl-C must not interrupt resource cleanup/join.
            previous = {
                sig: signal.signal(sig, signal.SIG_IGN)
                for sig in (signal.SIGINT, signal.SIGTERM)
            }
            try:
                forced = stop_processes(processes)
                write_json(
                    invocations[0].directory / "interrupted.json",
                    {"forced_termination": forced},
                )
                if forced:
                    print(
                        "Forced worker termination: owned databases may remain in disposable test storage; no sweep performed.",
                        flush=True,
                    )
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
            raise


def pytest_command(directory: Path, arguments: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-p",
        "scripts.pytest_manifest",
        f"--runner-manifest={directory / 'manifest.json'}",
        *arguments,
    ]


def read_junit(path: Path) -> ET.Element:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise RunnerError(f"Missing or invalid JUnit: {path}") from exc
    if root.tag not in {"testsuites", "testsuite"}:
        raise RunnerError(f"Invalid JUnit root: {path}")
    return root


def check_junit(root: ET.Element, expected: Sequence[str], returncode: int) -> None:
    cases = root.findall(".//testcase")
    actual: list[str | None] = []
    for case in cases:
        prop = case.find("properties/property[@name='nodeid']")
        actual.append(None if prop is None else prop.get("value"))
    # pytest can emit a second case for a teardown error after a call failure.
    counts = Counter(actual)
    duplicates = {node for node, count in counts.items() if count > 1}
    valid_teardown_duplicates = {
        case.find("properties/property[@name='nodeid']").get("value")
        for case in cases
        if case.find("error") is not None
        and case.find("properties/property[@name='nodeid']") is not None
    }
    if (
        set(actual) != set(expected)
        or any(count > 2 for count in counts.values())
        or not duplicates.issubset(valid_teardown_duplicates)
    ):
        raise RunnerError("JUnit node IDs do not match the expected collection")
    if returncode == 0 and (root.findall(".//failure") or root.findall(".//error")):
        raise RunnerError("Successful worker contains JUnit failures")


def merge_junit(
    roots: Sequence[ET.Element], destination: Path, errors: Sequence[str]
) -> None:
    merged = ET.Element("testsuites")
    for root in roots:
        merged.extend([root] if root.tag == "testsuite" else list(root))
    if errors:
        suite = ET.SubElement(
            merged,
            "testsuite",
            name="api-runner",
            tests=str(len(errors)),
            errors=str(len(errors)),
        )
        for index, error in enumerate(errors):
            case = ET.SubElement(
                suite,
                "testcase",
                classname="api-runner",
                name=f"infrastructure-{index}",
            )
            ET.SubElement(case, "error", message=error).text = error
    for key, tag in (
        ("tests", "testcase"),
        ("failures", "failure"),
        ("errors", "error"),
        ("skipped", "skipped"),
    ):
        merged.set(key, str(len(merged.findall(f".//{tag}"))))
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(merged).write(destination, encoding="utf-8", xml_declaration=True)


def run_api_tests(
    *,
    root: Path,
    artifacts: Path,
    target: str,
    workers: int,
    environment: dict[str, str],
    arguments: Sequence[str] = (),
    junitxml: Path | None = None,
) -> RunnerResult:
    if not 1 <= workers <= DEFAULT_POSTGRES_WORKERS or (
        target == "api-fast" and workers != 1
    ):
        raise RunnerError("Workers must be 1–4; api-fast supports only --workers 1")
    arguments = validate_arguments(arguments, target, root)
    directory = artifacts / f"{target}-{uuid.uuid4().hex}"
    directory.mkdir(parents=True)
    print(f"API test artifacts: {directory}", flush=True)
    if junitxml is not None:
        # A hard-killed parent must not leave an older success at the requested path.
        merge_junit([], junitxml, [f"API test run has not completed: {directory}"])
    # Clear ambient addopts so -n/--lf/report overrides cannot silently change this run.
    environment = {**environment, "PYTEST_ADDOPTS": ""}
    partitions = (
        [Partition.FAST, Partition.POSTGRES]
        if target == "api"
        else [Partition.POSTGRES if target == "api-postgres" else Partition.FAST]
    )
    errors: list[str] = []
    roots: list[ET.Element] = []
    returncodes: list[int] = []
    interrupted = False
    worker_failed = False
    invocations: list[Invocation] = []
    try:
        with interrupt_on_termination():
            for partition in partitions:
                invocations = []
                part_dir = directory / partition.name.lower()
                part_dir.mkdir()
                collection_dir = part_dir / "collection"
                collection_dir.mkdir()
                command = pytest_command(
                    collection_dir,
                    [
                        "--collect-only",
                        "-q",
                        "-m",
                        partition,
                        *arguments.options,
                        *(arguments.selectors or ["apps/api/tests"]),
                    ],
                )
                code = execute(
                    [Invocation(command, collection_dir)], root, environment
                )[0]
                returncodes.append(code)
                try:
                    manifest = read_manifest(collection_dir / "manifest.json", code)
                    expected = manifest["nodeids"]
                    if code != 0 and not (
                        code == 5 and not expected and target == "api"
                    ):
                        raise RunnerError(
                            f"Collection failed (exit {code}): {collection_dir / 'pytest.log'}"
                        )
                    if not expected:
                        continue
                    assignments = partition_modules(
                        expected, workers if partition == Partition.POSTGRES else 1
                    )
                    write_json(
                        part_dir / "expected.json",
                        {"nodeids": expected, "workers": assignments},
                    )
                    invocations = []
                    for index, nodes in enumerate(assignments):
                        worker_dir = part_dir / f"worker-{index + 1}"
                        worker_dir.mkdir()
                        nodefile = worker_dir / "nodeids.txt"
                        nodefile.write_text("\n".join(nodes) + "\n", encoding="utf-8")
                        invocations.append(
                            Invocation(
                                pytest_command(
                                    worker_dir,
                                    [
                                        "-m",
                                        partition,
                                        f"--junitxml={worker_dir / 'junit.xml'}",
                                        *arguments.options,
                                        f"@{nodefile}",
                                    ],
                                ),
                                worker_dir,
                            )
                        )
                    codes = execute(invocations, root, environment)
                    returncodes.extend(codes)
                    worker_failed = worker_failed or any(codes)
                    for invocation, nodes, code in zip(
                        invocations, assignments, codes, strict=True
                    ):
                        try:
                            report = read_junit(invocation.directory / "junit.xml")
                            roots.append(report)
                            actual = read_manifest(
                                invocation.directory / "manifest.json", code
                            )["nodeids"]
                            if actual != nodes:
                                raise RunnerError(
                                    f"Worker collection differs from expected: {invocation.directory}"
                                )
                            check_junit(report, nodes, code)
                            print(
                                f"{partition.name.lower()}/{invocation.directory.name}: "
                                f"{len(nodes)} cases, exit {code}; log: {invocation.directory / 'pytest.log'}",
                                flush=True,
                            )
                        except RunnerError as exc:
                            errors.append(str(exc))
                except RunnerError as exc:
                    errors.append(str(exc))
    except KeyboardInterrupt:
        interrupted = True
        for invocation in invocations:
            if (invocation.directory / "junit.xml").is_file():
                try:
                    roots.append(read_junit(invocation.directory / "junit.xml"))
                except RunnerError as exc:
                    errors.append(str(exc))
        errors.append(
            "API test run interrupted; children stopped and joined. Inspect interrupted.json for forced termination."
        )
    except OSError as exc:
        errors.append(f"Cannot execute test process: {exc}")
    if not roots and not errors:
        errors.append("No API tests selected")
    merge_junit(roots, directory / "junit.xml", errors)
    if junitxml is not None:
        merge_junit(roots, junitxml, errors)
    code = 130 if interrupted else int(bool(errors) or worker_failed)
    write_json(
        directory / "result.json",
        {"returncode": code, "process_returncodes": returncodes, "errors": errors},
    )
    for error in errors:
        print(error, file=sys.stderr)
    print(
        f"API tests: {len(roots)} worker report(s), exit {code}; JUnit: {directory / 'junit.xml'}",
        flush=True,
    )
    return RunnerResult(code, directory)
