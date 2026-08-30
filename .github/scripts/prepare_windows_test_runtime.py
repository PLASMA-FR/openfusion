#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Register build-tree DLL directories for Windows native test execution.

FreeCAD module libraries are deliberately emitted below ``build/Mod`` while
the GoogleTest executables live in ``build/bin``.  Windows does not search
sibling module directories when it resolves a test executable's imports.  In
GitHub Actions, this helper discovers the actual build layout and appends its
runtime directories to ``GITHUB_PATH`` for all subsequent test steps.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Sequence


DYNAMIC_LIBRARY_SUFFIXES = frozenset({".dll", ".pyd"})


class RuntimeLayoutError(RuntimeError):
    """Raised when the Windows build tree cannot support native test launch."""


def _resolved_directory(path: Path, description: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeLayoutError(f"Missing {description}: {path}") from error
    if not resolved.is_dir():
        raise RuntimeLayoutError(f"Expected {description} to be a directory: {path}")
    return resolved


def discover_runtime_layout(build_directory: Path) -> tuple[list[Path], list[Path]]:
    """Return runtime directories and their dynamic artifacts.

    The binary directory is kept first.  Module directories are de-duplicated
    case-insensitively and sorted so both ``GITHUB_PATH`` and diagnostic output
    remain stable across runs.
    """

    build_directory = _resolved_directory(build_directory, "build directory")
    binary_directory = _resolved_directory(build_directory / "bin", "binary directory")
    module_root = _resolved_directory(build_directory / "Mod", "module directory")

    artifacts = sorted(
        (
            candidate.resolve()
            for candidate in module_root.rglob("*")
            if candidate.is_file()
            and candidate.suffix.casefold() in DYNAMIC_LIBRARY_SUFFIXES
        ),
        key=lambda candidate: os.path.normcase(str(candidate)).casefold(),
    )
    if not artifacts:
        raise RuntimeLayoutError(
            f"No .dll or .pyd runtime artifacts were found below {module_root}"
        )

    module_directories: dict[str, Path] = {}
    for artifact in artifacts:
        parent = artifact.parent.resolve()
        try:
            parent.relative_to(module_root)
        except ValueError as error:
            raise RuntimeLayoutError(
                f"Runtime artifact resolves outside the module tree: {artifact}"
            ) from error
        module_directories.setdefault(os.path.normcase(str(parent)).casefold(), parent)

    directories = [binary_directory]
    directories.extend(
        module_directories[key]
        for key in sorted(module_directories)
        if module_directories[key] != binary_directory
    )
    return directories, artifacts


def require_artifacts(artifacts: Sequence[Path], required_names: Sequence[str]) -> None:
    """Fail when a required runtime artifact is absent from the discovered tree."""

    available_names = {artifact.name.casefold() for artifact in artifacts}
    missing_names = sorted(
        name for name in required_names if name.casefold() not in available_names
    )
    if missing_names:
        raise RuntimeLayoutError(
            "Required runtime artifacts were not built: " + ", ".join(missing_names)
        )


def _safe_command_file_line(path: Path) -> str:
    line = str(path)
    if "\n" in line or "\r" in line:
        raise RuntimeLayoutError(f"Runtime directory contains a newline: {path!s}")
    return line


def write_runtime_paths(
    directories: Sequence[Path], github_path: Path, manifest: Path
) -> None:
    """Append directories to GitHub's PATH command file and record diagnostics."""

    lines = [_safe_command_file_line(directory) for directory in directories]
    if not lines:
        raise RuntimeLayoutError("Refusing to register an empty runtime search path")

    github_path.parent.mkdir(parents=True, exist_ok=True)
    with github_path.open("a", encoding="utf-8", newline="\n") as command_file:
        command_file.write("\n".join(lines))
        command_file.write("\n")

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument(
        "--github-path",
        type=Path,
        default=os.environ.get("GITHUB_PATH"),
        help="GitHub Actions PATH command file (defaults to GITHUB_PATH)",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--require-artifact",
        action="append",
        default=[],
        help="Dynamic artifact basename that must exist (repeatable)",
    )
    parsed = parser.parse_args(arguments)
    if parsed.github_path is None:
        parser.error("--github-path is required when GITHUB_PATH is not set")
    return parsed


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        directories, artifacts = discover_runtime_layout(options.build_dir)
        require_artifacts(artifacts, options.require_artifact)
        write_runtime_paths(directories, options.github_path, options.manifest)
    except RuntimeLayoutError as error:
        print(f"Windows test runtime setup failed: {error}", file=sys.stderr)
        return 1

    print(
        f"Registered {len(directories)} runtime directories "
        f"containing {len(artifacts)} dynamic artifacts"
    )
    for directory in directories:
        print(f"  {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
