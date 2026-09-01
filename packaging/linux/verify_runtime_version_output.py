#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Verify the single-line OpenFusionCmd development identity output."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import sys


MAX_OUTPUT_BYTES = 4096
VERSION_RE = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
REVISION_RE = r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}"


class VersionOutputError(ValueError):
    """Raised when runtime version output is ambiguous or mislabeled."""


def validate_version_output(content: bytes, expected_version: str) -> str:
    if not isinstance(expected_version, str) or not VERSION_RE.fullmatch(
        expected_version
    ):
        raise VersionOutputError("expected version is not canonical SemVer")
    if len(content) > MAX_OUTPUT_BYTES:
        raise VersionOutputError("runtime version output exceeds the size limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VersionOutputError("runtime version output is not UTF-8") from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise VersionOutputError("runtime version output must contain exactly one line")
    pattern = re.compile(
        rf"OpenFusion {re.escape(expected_version)} Revision: "
        rf"(?P<revision>{REVISION_RE}) \(Git(?: shallow)?\)\n\Z"
    )
    match = pattern.fullmatch(text)
    if match is None:
        raise VersionOutputError(
            "runtime version output has the wrong version or revision shape"
        )
    return match.group("revision")


def _read_regular_file(path: Path) -> bytes:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_OUTPUT_BYTES:
            raise VersionOutputError("runtime version output is not a bounded regular file")
        content = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        if identity(before) != identity(after) or len(content) != before.st_size:
            raise VersionOutputError("runtime version output changed while being read")
        return content
    finally:
        os.close(descriptor)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--input", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        revision = validate_version_output(
            _read_regular_file(options.input), options.expected_version
        )
    except (OSError, VersionOutputError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"verified OpenFusionCmd revision: {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
