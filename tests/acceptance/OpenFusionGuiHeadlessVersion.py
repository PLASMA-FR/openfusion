# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify GUI version queries never initialize a display backend."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess


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
        expected_prefixes = (
            "Source revision: ",
            "Source revision date: ",
            "Source repository: ",
        )
        for line, prefix in zip(lines[1:], expected_prefixes, strict=True):
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
        if completed.stdout.startswith(expected_line):
            raise RuntimeError(
                f"{query!r} incorrectly entered the headless version path: "
                f"{completed.stdout!r}"
            )
    print(f"GUI headless version contract passed: {expected_line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
