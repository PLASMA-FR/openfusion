# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify GUI version queries never initialize a display backend."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess


VERBOSE_FIELD_PREFIXES = (
    "Source revision: ",
    "Source revision date: ",
    "Source repository: ",
)


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
        if completed.returncode == 0:
            raise RuntimeError(f"{query!r} unexpectedly succeeded")
        # The normal parser's legacy output starts with
        # ``OpenFusion VERSION, Libs: ...``.  In particular, ``--`` must bypass
        # this headless path without that normal output becoming a false match.
        if is_headless_version_output(completed.stdout, expected_line):
            raise RuntimeError(
                f"{query!r} incorrectly entered the headless version path: "
                f"{completed.stdout!r}"
            )
    print(f"GUI headless version contract passed: {expected_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
