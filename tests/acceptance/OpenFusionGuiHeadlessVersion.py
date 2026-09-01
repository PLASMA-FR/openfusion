# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify GUI version queries never initialize a display backend."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
from typing import Sequence


VERBOSE_FIELD_PREFIXES = (
    "Source revision: ",
    "Source revision date: ",
    "Source repository: ",
)
NORMAL_PATH_OBSERVATION_SECONDS = 2.0
TERMINATE_GRACE_SECONDS = 1.0
KILL_GRACE_SECONDS = 3.0


@dataclass(frozen=True)
class NormalPathObservation:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def is_headless_version_output(output: str, expected_line: str) -> bool:
    """Return whether output has an exact supported headless-version shape."""
    if output == expected_line + "\n":
        return True

    lines = output.splitlines()
    return (
        len(lines) == 4
        and lines[0] == expected_line
        and all(
            line.startswith(prefix) and line != prefix
            for line, prefix in zip(lines[1:], VERBOSE_FIELD_PREFIXES, strict=True)
        )
    )


def _signal_process_group(process: subprocess.Popen[str], force: bool) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        if not force:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError):
                # Preserve the live root PID so the forced tree cleanup can
                # still find every descendant after the grace period.
                pass
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=KILL_GRACE_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        return

    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        pass


def observe_normal_path(
    command: Sequence[str],
    environment: dict[str, str],
    *,
    observation_timeout: float = NORMAL_PATH_OBSERVATION_SECONDS,
    terminate_timeout: float = TERMINATE_GRACE_SECONDS,
    kill_timeout: float = KILL_GRACE_SECONDS,
) -> NormalPathObservation:
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        list(command),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_options,
    )
    try:
        stdout, stderr = process.communicate(timeout=observation_timeout)
        return NormalPathObservation(process.returncode, stdout, stderr, False)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, force=False)
        try:
            stdout, stderr = process.communicate(timeout=terminate_timeout)
        except subprocess.TimeoutExpired:
            _signal_process_group(process, force=True)
            try:
                stdout, stderr = process.communicate(timeout=kill_timeout)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    f"normal-path process group cleanup timed out: {command!r}"
                ) from error
        if process.returncode is None:
            raise RuntimeError(f"normal-path process survived cleanup: {command!r}")
        return NormalPathObservation(process.returncode, stdout, stderr, True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--expected-version", required=True)
    arguments = parser.parse_args()

    environment = os.environ.copy()
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        environment.pop(name, None)
    environment["QT_QPA_PLATFORM"] = "openfusion-version-must-not-load-qpa"

    expected_line = f"OpenFusion {arguments.expected_version}"
    concise_queries = (("--version",), ("-v",))
    verbose_queries = (
        ("--verbose-version",),
        ("--version", "--verbose"),
        ("--verbose", "--version"),
        ("-v", "--verbose"),
    )

    for query in concise_queries + verbose_queries:
        completed = subprocess.run(
            [str(arguments.executable), *query],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{query!r} returned {completed.returncode}: "
                f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
            )
        if completed.stderr:
            raise RuntimeError(f"{query!r} wrote stderr: {completed.stderr!r}")
        lines = completed.stdout.splitlines()
        if query in concise_queries:
            expected_output = expected_line + "\n"
            if completed.stdout != expected_output:
                raise RuntimeError(
                    f"{query!r} output was not exactly {expected_output!r}: "
                    f"{completed.stdout!r}"
                )
            continue

        if len(lines) != 4 or lines[0] != expected_line:
            raise RuntimeError(
                f"{query!r} did not report the exact verbose version shape: "
                f"{completed.stdout!r}"
            )
        for line, prefix in zip(lines[1:], VERBOSE_FIELD_PREFIXES, strict=True):
            if not line.startswith(prefix) or line == prefix:
                raise RuntimeError(
                    f"{query!r} emitted an invalid {prefix!r} field: {line!r}"
                )

    rejected_queries = (
        ("--", "--version"),
        ("model.FCStd", "--version"),
        ("mødél.FCStd", "-v"),
    )
    for query in rejected_queries:
        observation = observe_normal_path(
            [str(arguments.executable), *query],
            environment,
        )
        # The normal parser's legacy output starts with
        # ``OpenFusion VERSION, Libs: ...``.  In particular, ``--`` must bypass
        # this headless path without that normal output becoming a false match.
        # A still-running GUI is valid normal-path evidence and is cleaned up
        # above; no particular normal GUI exit code is required.
        if is_headless_version_output(observation.stdout, expected_line):
            raise RuntimeError(
                f"{query!r} incorrectly entered the headless version path: "
                f"{observation.stdout!r}"
            )
    print(f"GUI headless version contract passed: {expected_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
