#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reject quarantined material-pattern assets and build references.

The inherited files listed below declare ``License: "All rights reserved"``.
They are intentionally absent from OpenFusion source and packages unless their
redistribution status is resolved.  This check keeps that quarantine explicit
and also catches renamed pattern files carrying the same declaration.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, List


RESTRICTED_PATTERN_PATHS = (
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal4.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal5.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond2.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond4.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Horizontal5.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Square.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Vertical5.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/aluminum.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/brick01.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/concrete.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cross.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cuprous.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal1.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal2.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/earth.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/general_steel.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/glass.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45L.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45R.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hbone.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/line.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plastic.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plus.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/simple.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/solid.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/square.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/steel.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/titanium.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/wood.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/woodgrain.FCMat",
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/zinc.FCMat",
)

MATERIAL_SOURCE_PREFIX = "src/Mod/Material/"
PATTERN_ROOT = Path("src/Mod/Material/Resources/Materials/Patterns")
RESTRICTED_LICENSE = re.compile(
    r"^\s*License\s*:\s*['\"]?All\s+rights\s+reserved['\"]?\s*(?:#.*)?$",
    re.IGNORECASE | re.MULTILINE,
)


def _read_text(path: Path) -> str:
    """Read repository text deterministically, accepting an optional UTF-8 BOM."""

    return path.read_text(encoding="utf-8-sig")


def _cmake_files(repo_root: Path) -> Iterable[Path]:
    return sorted(repo_root.rglob("CMakeLists.txt"), key=lambda path: path.as_posix())


def find_violations(repo_root: Path) -> List[str]:
    """Return sorted quarantine violations relative to *repo_root*."""

    repo_root = repo_root.resolve()
    violations = []

    for relative in RESTRICTED_PATTERN_PATHS:
        candidate = repo_root / relative
        if candidate.exists() or candidate.is_symlink():
            violations.append(f"restricted path exists: {relative}")

    cmake_texts = []
    for cmake_file in _cmake_files(repo_root):
        try:
            text = _read_text(cmake_file).replace("\\", "/")
        except (OSError, UnicodeError) as error:
            relative = cmake_file.relative_to(repo_root).as_posix()
            violations.append(f"cannot inspect CMake file {relative}: {error}")
            continue
        cmake_texts.append((cmake_file, text))

    for restricted in RESTRICTED_PATTERN_PATHS:
        material_relative = restricted.removeprefix(MATERIAL_SOURCE_PREFIX)
        for cmake_file, text in cmake_texts:
            if material_relative in text or restricted in text:
                relative = cmake_file.relative_to(repo_root).as_posix()
                violations.append(
                    f"restricted path referenced by {relative}: {material_relative}"
                )

    pattern_root = repo_root / PATTERN_ROOT
    if pattern_root.is_dir():
        for pattern_file in sorted(pattern_root.rglob("*.FCMat"), key=lambda path: path.as_posix()):
            try:
                text = _read_text(pattern_file)
            except (OSError, UnicodeError) as error:
                relative = pattern_file.relative_to(repo_root).as_posix()
                violations.append(f"cannot inspect material pattern {relative}: {error}")
                continue
            if RESTRICTED_LICENSE.search(text):
                relative = pattern_file.relative_to(repo_root).as_posix()
                violations.append(f"restricted license declaration in: {relative}")

    return sorted(set(violations))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the root containing this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    violations = find_violations(args.repo_root)
    if violations:
        print("Restricted material pattern guard: FAILED", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(
        "Restricted material pattern guard: PASS "
        f"({len(RESTRICTED_PATTERN_PATHS)} quarantined paths absent)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
