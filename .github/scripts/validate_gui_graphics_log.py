#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reject GUI logs that show an unusable or corrupted OpenGL context."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Sequence


HARD_GRAPHICS_FAILURE_PATTERNS = (
    re.compile(r"This system is running OpenGL 1\.\d+(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(
        r"QOpenGLWidget: Failed to create (?:wrapper texture|context)", re.IGNORECASE
    ),
    re.compile(r"QOpenGLContext::makeCurrent\(\) failed", re.IGNORECASE),
    re.compile(
        r"Failed to create (?:a suitable )?(?:platform )?OpenGL context", re.IGNORECASE
    ),
    re.compile(
        r"Coin warning in cc_glglue_instance\(\): Error when setting up the GL context",
        re.IGNORECASE,
    ),
    re.compile(r"The error message is: Access violation", re.IGNORECASE),
)
RECOVERABLE_GRAPHICS_WARNING_PATTERNS = (
    re.compile(r"The frame buffer has become invalid", re.IGNORECASE),
    re.compile(
        r"Attempted to call beginFrame\(\) within a still active frame",
        re.IGNORECASE,
    ),
)
GRAPHICS_FAILURE_SIGNATURE_COUNT = len(HARD_GRAPHICS_FAILURE_PATTERNS) + 1


class GraphicsLogError(RuntimeError):
    """Raised when a GUI log is missing or reports graphics corruption."""


def validate_graphics_log(path: Path) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise GraphicsLogError(f"Cannot read GUI application log: {path}") from error
    if not text.strip():
        raise GraphicsLogError(f"GUI application log is empty: {path}")

    lines = text.splitlines()
    failures: list[str] = []
    for pattern in HARD_GRAPHICS_FAILURE_PATTERNS:
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                failures.append(f"line {line_number}: {line.strip()}")
                break
    recoverable_hits: list[str] = []
    for pattern in RECOVERABLE_GRAPHICS_WARNING_PATTERNS:
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                recoverable_hits.append(f"line {line_number}: {line.strip()}")
                break
    if len(recoverable_hits) == len(RECOVERABLE_GRAPHICS_WARNING_PATTERNS):
        failures.append(
            "combined recoverable warnings indicate a corrupted frame lifecycle: "
            + " | ".join(recoverable_hits)
        )
    if failures:
        raise GraphicsLogError(
            "GUI graphics diagnostics reported an unusable context:\n  "
            + "\n  ".join(failures)
        )
    return len(lines), GRAPHICS_FAILURE_SIGNATURE_COUNT


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--label", default="GUI")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        line_count, signature_count = validate_graphics_log(options.log)
    except GraphicsLogError as error:
        print(f"{options.label} graphics validation failed: {error}", file=sys.stderr)
        return 1
    print(
        f"{options.label} graphics validation passed: "
        f"{line_count} log lines, {signature_count} failure signatures absent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
