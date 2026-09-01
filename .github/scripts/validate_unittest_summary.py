#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Validate the final anchored unittest summary in a captured test log."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
from typing import Sequence


_DURATION = r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
_SUMMARY_CANDIDATE = re.compile(r"^Ran[ \t]+\S+[ \t]+tests?[ \t]+in(?:[ \t]|$)")
_SUMMARY = re.compile(
    rf"^Ran[ \t]+(?P<count>[0-9]+)[ \t]+tests?[ \t]+in[ \t]+"
    rf"(?P<duration>{_DURATION})s[ \t]*$"
)


class SummaryValidationError(RuntimeError):
    """Raised when captured output has no trustworthy unittest summary."""


def validate_unittest_summary(output: str, expected_count: int | None = None) -> int:
    """Return the latest test count after validating every summary candidate."""

    summaries: list[tuple[int, Decimal]] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not _SUMMARY_CANDIDATE.match(line):
            continue

        match = _SUMMARY.fullmatch(line)
        if match is None:
            raise SummaryValidationError(
                f"Malformed unittest summary on line {line_number}: {line!r}"
            )

        duration_text = match.group("duration")
        try:
            duration = Decimal(duration_text)
        except InvalidOperation as error:
            raise SummaryValidationError(
                f"Invalid unittest duration on line {line_number}: {duration_text!r}"
            ) from error
        if not duration.is_finite() or duration < 0:
            raise SummaryValidationError(
                f"Invalid unittest duration on line {line_number}: {duration_text!r}"
            )
        summaries.append((int(match.group("count")), duration))

    if not summaries:
        raise SummaryValidationError("No anchored unittest summary was found")

    count, _duration = summaries[-1]
    if count <= 0:
        raise SummaryValidationError("Final unittest summary reported zero tests")
    if expected_count is not None and count != expected_count:
        raise SummaryValidationError(
            f"Final unittest summary reported {count} tests; expected {expected_count}"
        )
    return count


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected count must be greater than zero")
    return parsed


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Captured unittest output")
    parser.add_argument(
        "--expected-count",
        type=_positive_integer,
        help="Require the final summary to report exactly this many tests",
    )
    parser.add_argument(
        "--count-file",
        type=Path,
        help="Write the validated final test count to this file",
    )
    parser.add_argument(
        "--label",
        default="unittest runner",
        help="Human-readable runner name for diagnostics",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        output = options.log.read_text(encoding="utf-8", errors="replace")
        count = validate_unittest_summary(output, options.expected_count)
        if options.count_file is not None:
            options.count_file.parent.mkdir(parents=True, exist_ok=True)
            options.count_file.write_text(f"{count}\n", encoding="utf-8", newline="\n")
    except (OSError, SummaryValidationError) as error:
        print(f"{options.label} summary validation failed: {error}", file=sys.stderr)
        return 1

    print(f"{options.label} final unittest summary reported {count} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
