"""Bounded stdlib subprocess execution with checked collections and retained reports."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, ExitStack, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict

from scripts.deferred_signals import defer_interrupts


DEFAULT_POSTGRES_WORKERS = 4
CLEANUP_GRACE_SECONDS = 15
TERMINATE_GRACE_SECONDS = 5


class RunnerError(RuntimeError):
    pass


class ReportPublicationError(RuntimeError):
    pass


class Partition(StrEnum):
    FAST = "not postgres"
    POSTGRES = "postgres"


class Manifest(TypedDict):
    nodeids: list[str]
    exit_code: int
    stopped_after_failure: bool


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
        or type(value.get("stopped_after_failure")) is not bool
        or (value["stopped_after_failure"] and returncode != 1)
        or not isinstance(value.get("nodeids"), list)
        or any(
            not isinstance(node, str) or "::" not in node for node in value["nodeids"]
        )
        or len(set(value["nodeids"])) != len(value["nodeids"])
    ):
        raise RunnerError(f"Invalid collection/exit code in manifest: {path}")
    return Manifest(
        nodeids=value["nodeids"],
        exit_code=value["exit_code"],
        stopped_after_failure=value["stopped_after_failure"],
    )


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
            # Keep values attached so pytest treats a leading @ as part of the value.
            options.append(f"{argument}={value}")
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
def interrupt_once() -> Iterator[None]:
    """Keep repeated signals from interrupting cleanup and report publication."""
    received = False

    def interrupted(signum: int, frame: object) -> None:
        nonlocal received
        if not received:
            received = True
            raise KeyboardInterrupt

    previous = {signal.SIGTERM: signal.getsignal(signal.SIGTERM)}
    sigint_handler = signal.getsignal(signal.SIGINT)
    if sigint_handler != signal.SIG_IGN:
        previous[signal.SIGINT] = sigint_handler
    try:
        for signum in previous:
            signal.signal(signum, interrupted)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def signal_process(
    process: subprocess.Popen[bytes], signum: int, *, start_new_session: bool
) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            if signum == signal.SIGINT:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except OSError:
                    if process.poll() is None:
                        process.terminate()
                        return True
            else:
                process.terminate()
        elif start_new_session:
            os.killpg(process.pid, signum)
        else:
            process.send_signal(signum)
    except ProcessLookupError:
        pass
    return False


def stop_processes(
    processes: Sequence[subprocess.Popen[bytes]], *, start_new_session: bool = True
) -> bool:
    """Give pytest SIGINT time to tear down owned fixtures before escalating."""
    forced = False
    for signum, grace in (
        (signal.SIGINT, CLEANUP_GRACE_SECONDS),
        (signal.SIGTERM, TERMINATE_GRACE_SECONDS),
    ):
        for process in processes:
            forced = (
                signal_process(process, signum, start_new_session=start_new_session)
                or forced
            )
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
                signal_process(
                    process, signal.SIGKILL, start_new_session=start_new_session
                )
    for process in processes:
        process.wait()
    return True


def execute(
    invocations: Sequence[Invocation],
    root: Path,
    environment: dict[str, str],
    *,
    timeout: float | None = None,
    start_new_session: bool = True,
) -> list[int]:
    processes: list[subprocess.Popen[bytes]] = []
    with ExitStack() as stack:
        try:
            for invocation in invocations:
                log = stack.enter_context(
                    (invocation.directory / "pytest.log").open("wb")
                )
                with defer_interrupts(signal.SIGINT, signal.SIGTERM):
                    processes.append(
                        subprocess.Popen(
                            invocation.command,
                            cwd=root,
                            env=environment,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=start_new_session and os.name != "nt",
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                            if os.name == "nt"
                            else 0,
                        )
                    )
            return [process.wait(timeout=timeout) for process in processes]
        except BaseException:
            # A second Ctrl-C must not interrupt resource cleanup/join.
            previous = {
                sig: signal.signal(sig, signal.SIG_IGN)
                for sig in (signal.SIGINT, signal.SIGTERM)
            }
            try:
                forced = stop_processes(processes, start_new_session=start_new_session)
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


def check_junit(
    root: ET.Element,
    expected: Sequence[str],
    returncode: int,
    *,
    stopped_after_failure: bool = False,
) -> int:
    cases = root.findall(".//testcase")
    actual: list[str | None] = []
    for case in cases:
        prop = case.find("properties/property[@name='nodeid']")
        actual.append(None if prop is None else prop.get("value"))
    if stopped_after_failure:
        executed = list(dict.fromkeys(actual))
        failed_nodes = {
            node
            for case, node in zip(cases, actual, strict=True)
            if case.find("failure") is not None or case.find("error") is not None
        }
        if (
            returncode != 1
            or not executed
            or executed != list(expected[: len(executed)])
            or failed_nodes != {executed[-1]}
        ):
            raise RunnerError("Invalid JUnit stop-after-failure report")
        # Only a confirmed -x stop may omit the unexecuted collection tail.
        expected = expected[: len(executed)]
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
    has_failures = bool(root.findall(".//failure") or root.findall(".//error"))
    if returncode not in {0, 1}:
        raise RunnerError(f"Unexpected pytest worker exit {returncode}")
    if returncode == 0 and has_failures:
        raise RunnerError("Successful worker contains JUnit failures")
    if returncode == 1 and not has_failures:
        raise RunnerError("Pytest worker exit 1 without JUnit failures")
    return len(counts)


def merge_junit(
    roots: Sequence[ET.Element],
    destination: Path,
    errors: Sequence[str],
    *,
    collection_cases: Sequence[ET.Element] = (),
) -> None:
    merged = ET.Element("testsuites")
    for root in roots:
        merged.extend([root] if root.tag == "testsuite" else list(root))
    if collection_cases:
        suite = ET.SubElement(
            merged,
            "testsuite",
            name="pytest-collection",
            tests=str(len(collection_cases)),
            errors=str(
                sum(case.find("error") is not None for case in collection_cases)
            ),
            skipped=str(
                sum(case.find("skipped") is not None for case in collection_cases)
            ),
            failures="0",
        )
        suite.extend(collection_cases)
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


def retain_worker_reports(
    invocations: Sequence[Invocation],
    reports: dict[Path, ET.Element],
    errors: list[str],
) -> None:
    # execute() has stopped and joined any children it started.
    for invocation in invocations:
        report_path = invocation.directory / "junit.xml"
        if report_path not in reports and report_path.is_file():
            try:
                reports[report_path] = read_junit(report_path)
            except RunnerError as exc:
                errors.append(str(exc))


def retain_collection_cases(path: Path, cases: dict[bytes, ET.Element]) -> None:
    for case in read_junit(path).findall(".//testcase"):
        # Both marker partitions can collect the same skipped or broken file.
        cases.setdefault(ET.tostring(case), case)


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
    directory = artifacts / f"{target}-{uuid.uuid4().hex}"
    arguments = validate_arguments(arguments, target, root)
    directory.mkdir(parents=True)
    print(f"API test artifacts: {directory}", flush=True)
    # Ambient options/plugins must not silently change collection or reporting.
    environment = {**environment, "PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": ""}
    partitions = (
        [Partition.FAST, Partition.POSTGRES]
        if target == "api"
        else [Partition.POSTGRES if target == "api-postgres" else Partition.FAST]
    )
    errors: list[str] = []
    reports: dict[Path, ET.Element] = {}
    collection_cases: dict[bytes, ET.Element] = {}
    collection_report: Path | None = None
    returncodes: list[int] = []
    worker_failed = False
    invocations: list[Invocation] = []

    def finalize_reports(*, interrupted: bool = False) -> RunnerResult:
        roots = list(reports.values())
        report_errors = errors if roots or errors else ["No API tests selected"]
        merged_report = directory / "junit.xml"
        merge_junit(
            roots,
            merged_report,
            report_errors,
            collection_cases=list(collection_cases.values()),
        )
        code = 130 if interrupted else int(bool(report_errors) or worker_failed)
        write_json(
            directory / "result.json",
            {"returncode": code, "process_returncodes": returncodes, "errors": report_errors},
        )
        if junitxml is not None:
            try:
                with TemporaryDirectory(dir=junitxml.parent, prefix=".junit-") as temporary:
                    staged_report = Path(temporary) / "report.xml"
                    shutil.copyfile(merged_report, staged_report)
                    with suppress(FileNotFoundError):
                        shutil.copymode(junitxml, staged_report)
                    staged_report.replace(junitxml)
            except OSError as exc:
                raise ReportPublicationError(f"Cannot publish API test JUnit to {junitxml}: {exc}") from exc
        for error in report_errors:
            print(error, file=sys.stderr)
        print(
            f"API tests: {len(roots)} worker report(s), exit {code}; JUnit: {merged_report}",
            flush=True,
        )
        return RunnerResult(code, directory)

    with interrupt_once():
        try:
            for partition in partitions:
                invocations = []
                try:
                    part_dir = directory / partition.name.lower()
                    part_dir.mkdir()
                    collection_dir = part_dir / "collection"
                    collection_dir.mkdir()
                    collection_report = collection_dir / "junit.xml"
                    command = pytest_command(
                        collection_dir,
                        [
                            "--collect-only",
                            f"--junitxml={collection_report}",
                            "-o",
                            "junit_family=xunit1",
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
                    if code == 0 or collection_report.is_file():
                        retain_collection_cases(collection_report, collection_cases)
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
                            report_path = invocation.directory / "junit.xml"
                            report = read_junit(report_path)
                            reports[report_path] = report
                            manifest = read_manifest(
                                invocation.directory / "manifest.json", code
                            )
                            worker_nodes = manifest["nodeids"]
                            if set(worker_nodes) != set(nodes):
                                raise RunnerError(
                                    f"Worker collection differs from expected: {invocation.directory}"
                                )
                            if (
                                manifest["stopped_after_failure"]
                                and "-x" not in arguments.options
                            ):
                                raise RunnerError(
                                    "Worker stopped after failure without a requested -x"
                                )
                            completed = check_junit(
                                report,
                                worker_nodes,
                                code,
                                stopped_after_failure=manifest["stopped_after_failure"],
                            )
                            print(
                                f"{partition.name.lower()}/{invocation.directory.name}: "
                                f"{completed}/{len(nodes)} cases, exit {code}; log: {invocation.directory / 'pytest.log'}",
                                flush=True,
                            )
                        except RunnerError as exc:
                            errors.append(str(exc))
                except RunnerError as exc:
                    errors.append(str(exc))
                except OSError as exc:
                    retain_worker_reports(invocations, reports, errors)
                    errors.append(
                        f"Cannot execute test process for {partition.name.lower()}: {exc}"
                    )
            return finalize_reports()
        except KeyboardInterrupt:
            if collection_report is not None and collection_report.is_file():
                try:
                    retain_collection_cases(collection_report, collection_cases)
                except RunnerError as exc:
                    errors.append(str(exc))
            retain_worker_reports(invocations, reports, errors)
            errors.append(
                "API test run interrupted; children stopped and joined. "
                "Inspect interrupted.json, when present, for forced termination."
            )
            return finalize_reports(interrupted=True)
