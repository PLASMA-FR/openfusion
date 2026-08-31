#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Prepare the build-tree runtime and Qt graphics stack for Windows tests.

FreeCAD module libraries are deliberately emitted below ``build/Mod`` while
the GoogleTest executables live in ``build/bin``.  Windows does not search
sibling module directories when it resolves a test executable's imports.  In
GitHub Actions, this helper discovers the actual build layout and appends its
runtime directories to ``GITHUB_PATH`` for all subsequent test steps.  It also
validates the qmake-derived CTest Qt plugin manifest and exports the exact
plugin directories through ``GITHUB_ENV``.  GPU-less CI runners additionally
need Qt's locked Mesa renderer staged as app-local ``opengl32.dll`` so Qt,
Coin, and FreeCAD's native OpenGL calls all resolve through one implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Sequence

import yaml


DYNAMIC_LIBRARY_SUFFIXES = frozenset({".dll", ".pyd"})
QT_PLATFORM_PLUGIN_BASENAME_GROUPS = (
    frozenset({"qwindows.dll", "qwindowsd.dll"}),
    frozenset({"qoffscreen.dll", "qoffscreend.dll"}),
)
QT_PLUGIN_PATH_VARIABLE = "QT_PLUGIN_PATH"
QT_PLATFORM_PLUGIN_PATH_VARIABLE = "QT_QPA_PLATFORM_PLUGIN_PATH"
SOFTWARE_OPENGL_BASENAME = "opengl32sw.dll"
DESKTOP_OPENGL_BASENAME = "opengl32.dll"
SOFTWARE_OPENGL_RELATIVE_PATH = Path("Library") / "bin" / SOFTWARE_OPENGL_BASENAME
SOFTWARE_OPENGL_PACKAGE = "qt6-main"
QT_OPENGL_VARIABLE = "QT_OPENGL"
QT_OPENGL_DESKTOP_BACKEND = "desktop"
STAGED_OPENGL_PATH_VARIABLE = "OPENFUSION_STAGED_OPENGL_PATH"
STAGED_OPENGL_SHA256_VARIABLE = "OPENFUSION_STAGED_OPENGL_SHA256"
STAGED_OPENGL_PACKAGE_VARIABLE = "OPENFUSION_STAGED_OPENGL_PACKAGE"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


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


def _resolved_file(path: Path, description: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise RuntimeLayoutError(f"Missing {description}: {path}") from error
    if not resolved.is_file():
        raise RuntimeLayoutError(f"Expected {description} to be a file: {path}")
    return resolved


def _sha256(path: Path, description: str) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RuntimeLayoutError(f"Cannot hash {description}: {path}") from error
    return digest.hexdigest()


def _normalized_conda_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").casefold()


def locked_conda_software_opengl(
    environment: dict[str, str], lock_file: Path
) -> tuple[Path, str]:
    """Return the renderer and package provenance from the locked active environment."""

    prefix = environment.get("CONDA_PREFIX", "")
    if not prefix:
        raise RuntimeLayoutError(
            "CONDA_PREFIX is required to locate the locked software OpenGL renderer"
        )
    prefix_path = _resolved_directory(Path(prefix), "active Conda prefix")
    source = _resolved_file(
        prefix_path / SOFTWARE_OPENGL_RELATIVE_PATH,
        "software OpenGL renderer",
    )
    try:
        source.relative_to(prefix_path)
    except ValueError as error:
        raise RuntimeLayoutError(
            f"Software OpenGL renderer resolves outside CONDA_PREFIX: {source}"
        ) from error

    metadata_directory = _resolved_directory(
        prefix_path / "conda-meta", "Conda package metadata directory"
    )
    expected_file = _normalized_conda_path(SOFTWARE_OPENGL_RELATIVE_PATH.as_posix())
    owners: list[dict[str, object]] = []
    try:
        metadata_files = sorted(metadata_directory.glob("*.json"))
        for metadata_file in metadata_files:
            record = json.loads(metadata_file.read_text(encoding="utf-8"))
            files = record.get("files", [])
            if isinstance(files, list) and any(
                isinstance(item, str) and _normalized_conda_path(item) == expected_file
                for item in files
            ):
                owners.append(record)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeLayoutError(
            "Cannot inspect Conda package ownership metadata"
        ) from error
    if len(owners) != 1:
        raise RuntimeLayoutError(
            "Expected exactly one Conda package to own "
            f"{SOFTWARE_OPENGL_RELATIVE_PATH.as_posix()}, found {len(owners)}"
        )

    owner = owners[0]
    name = owner.get("name")
    version = owner.get("version")
    build = owner.get("build")
    subdir = owner.get("subdir")
    package_url = owner.get("url")
    if (
        name != SOFTWARE_OPENGL_PACKAGE
        or not isinstance(version, str)
        or not version
        or not isinstance(build, str)
        or not build
        or subdir != "win-64"
        or not isinstance(package_url, str)
        or not package_url
    ):
        raise RuntimeLayoutError(
            "Software OpenGL renderer is not owned by a complete win-64 "
            f"{SOFTWARE_OPENGL_PACKAGE} package record"
        )

    lock_file = _resolved_file(lock_file, "Pixi lock file")
    try:
        lock = yaml.safe_load(lock_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RuntimeLayoutError(f"Cannot parse Pixi lock file: {lock_file}") from error
    packages = lock.get("packages") if isinstance(lock, dict) else None
    if not isinstance(packages, list):
        raise RuntimeLayoutError("Pixi lock file does not contain a packages list")
    locked_records = [
        package
        for package in packages
        if isinstance(package, dict) and package.get("conda") == package_url
    ]
    if len(locked_records) != 1:
        raise RuntimeLayoutError(
            "Conda renderer owner URL is not uniquely present in the Pixi lock: "
            f"{package_url}"
        )
    package_sha256 = str(locked_records[0].get("sha256", "")).casefold()
    if SHA256_PATTERN.fullmatch(package_sha256) is None:
        raise RuntimeLayoutError("Locked renderer package has no valid SHA-256 digest")

    provenance = (
        f"{name}-{version}-{build} package_sha256={package_sha256} url={package_url}"
    )
    return source, provenance


def stage_software_opengl(source: Path, binary_directory: Path) -> tuple[Path, str]:
    """Stage Qt's Mesa renderer under the native OpenGL dependency basename."""

    source = _resolved_file(source, "software OpenGL renderer")
    if source.name.casefold() != SOFTWARE_OPENGL_BASENAME:
        raise RuntimeLayoutError(
            "Software OpenGL renderer must be named "
            f"{SOFTWARE_OPENGL_BASENAME}: {source}"
        )
    binary_directory = _resolved_directory(binary_directory, "binary directory")
    destination = binary_directory / DESKTOP_OPENGL_BASENAME
    source_digest = _sha256(source, "software OpenGL renderer")

    if destination.exists():
        destination = _resolved_file(destination, "staged OpenGL renderer")
        if _sha256(destination, "staged OpenGL renderer") != source_digest:
            raise RuntimeLayoutError(
                "Refusing to replace a different app-local OpenGL renderer: "
                f"{destination}"
            )
        return destination, source_digest

    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeLayoutError(
            f"Cannot stage software OpenGL renderer at {destination}"
        ) from error

    if _sha256(destination, "staged OpenGL renderer") != source_digest:
        try:
            destination.unlink()
        except OSError:
            pass
        raise RuntimeLayoutError(
            f"Staged software OpenGL renderer failed verification: {destination}"
        )
    return destination, source_digest


def discover_qt_plugin_layout(manifest: Path) -> tuple[Path, Path]:
    """Validate and return qmake-derived Qt plugin directories."""

    manifest = _resolved_file(manifest, "Qt plugin manifest")
    try:
        manifest_lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise RuntimeLayoutError(
            f"Cannot read Qt plugin manifest: {manifest}"
        ) from error

    if len(manifest_lines) != 2 or any(
        not line or line != line.strip() for line in manifest_lines
    ):
        raise RuntimeLayoutError(
            "Qt plugin manifest must contain exactly two nonempty path lines"
        )

    candidates = [Path(line) for line in manifest_lines]
    if any(not candidate.is_absolute() for candidate in candidates):
        raise RuntimeLayoutError("Qt plugin manifest paths must be absolute")

    plugin_directory = _resolved_directory(candidates[0], "Qt plugin directory")
    platform_directory = _resolved_directory(
        candidates[1], "Qt platform plugin directory"
    )
    expected_platform_directory = _resolved_directory(
        plugin_directory / "platforms", "Qt platforms directory"
    )
    try:
        platform_is_expected = platform_directory.samefile(expected_platform_directory)
    except OSError as error:
        raise RuntimeLayoutError(
            "Cannot compare the Qt platform plugin directory with the queried "
            f"plugin root: {plugin_directory}"
        ) from error
    if not platform_is_expected:
        raise RuntimeLayoutError(
            "Qt platform plugin directory must be the platforms child of the "
            f"queried plugin root: {plugin_directory}"
        )

    try:
        plugin_names = frozenset(
            candidate.name.casefold()
            for candidate in platform_directory.iterdir()
            if candidate.is_file()
        )
    except OSError as error:
        raise RuntimeLayoutError(
            f"Cannot inspect Qt platform plugin directory: {platform_directory}"
        ) from error
    missing_plugin_groups = [
        " or ".join(sorted(accepted_names))
        for accepted_names in QT_PLATFORM_PLUGIN_BASENAME_GROUPS
        if plugin_names.isdisjoint(accepted_names)
    ]
    if missing_plugin_groups:
        raise RuntimeLayoutError(
            "Qt platform plugin directory is missing required artifacts: "
            + ", ".join(missing_plugin_groups)
        )

    return plugin_directory, platform_directory


def _safe_command_file_line(path: Path, description: str) -> str:
    line = str(path)
    if "\n" in line or "\r" in line:
        raise RuntimeLayoutError(f"{description} contains a newline: {path!s}")
    return line


def write_runtime_paths(
    directories: Sequence[Path], github_path: Path, manifest: Path
) -> None:
    """Append directories to GitHub's PATH command file and record diagnostics."""

    lines = [
        _safe_command_file_line(directory, "Runtime directory")
        for directory in directories
    ]
    if not lines:
        raise RuntimeLayoutError("Refusing to register an empty runtime search path")

    github_path.parent.mkdir(parents=True, exist_ok=True)
    with github_path.open("a", encoding="utf-8", newline="\n") as command_file:
        command_file.write("\n".join(lines))
        command_file.write("\n")

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_qt_plugin_environment(
    plugin_directory: Path, platform_directory: Path, github_environment: Path
) -> None:
    """Append validated Qt plugin assignments to GitHub's environment file."""

    assignments = (
        (
            QT_PLUGIN_PATH_VARIABLE,
            _safe_command_file_line(plugin_directory, "Qt plugin directory"),
        ),
        (
            QT_PLATFORM_PLUGIN_PATH_VARIABLE,
            _safe_command_file_line(platform_directory, "Qt platform plugin directory"),
        ),
    )
    github_environment.parent.mkdir(parents=True, exist_ok=True)
    with github_environment.open("a", encoding="utf-8", newline="\n") as command_file:
        for name, value in assignments:
            command_file.write(f"{name}={value}\n")


def write_software_opengl_environment(
    renderer: Path,
    digest: str,
    provenance: str,
    github_environment: Path,
) -> None:
    """Force Qt through the staged app-local renderer and retain exact evidence."""

    assignments = (
        (QT_OPENGL_VARIABLE, QT_OPENGL_DESKTOP_BACKEND),
        (
            STAGED_OPENGL_PATH_VARIABLE,
            _safe_command_file_line(renderer, "Staged OpenGL renderer"),
        ),
        (STAGED_OPENGL_SHA256_VARIABLE, digest),
        (STAGED_OPENGL_PACKAGE_VARIABLE, provenance),
    )
    github_environment.parent.mkdir(parents=True, exist_ok=True)
    with github_environment.open("a", encoding="utf-8", newline="\n") as command_file:
        for name, value in assignments:
            if "\n" in value or "\r" in value:
                raise RuntimeLayoutError(f"{name} contains a newline")
            command_file.write(f"{name}={value}\n")


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument(
        "--github-path",
        type=Path,
        default=os.environ.get("GITHUB_PATH"),
        help="GitHub Actions PATH command file (defaults to GITHUB_PATH)",
    )
    parser.add_argument(
        "--github-env",
        type=Path,
        default=os.environ.get("GITHUB_ENV"),
        help="GitHub Actions environment command file (defaults to GITHUB_ENV)",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qt-plugin-manifest", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument(
        "--stage-software-opengl",
        action="store_true",
        help=(
            "Stage the active locked environment's opengl32sw.dll as the "
            "app-local opengl32.dll used by GPU-less Windows runners"
        ),
    )
    parser.add_argument(
        "--require-artifact",
        action="append",
        default=[],
        help="Dynamic artifact basename that must exist (repeatable)",
    )
    parsed = parser.parse_args(arguments)
    if parsed.github_path is None:
        parser.error("--github-path is required when GITHUB_PATH is not set")
    if parsed.github_env is None:
        parser.error("--github-env is required when GITHUB_ENV is not set")
    return parsed


def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    try:
        directories, artifacts = discover_runtime_layout(options.build_dir)
        require_artifacts(artifacts, options.require_artifact)
        plugin_directory, platform_directory = discover_qt_plugin_layout(
            options.qt_plugin_manifest
        )
        staged_renderer = None
        renderer_provenance = None
        if options.stage_software_opengl:
            if options.lock_file is None:
                raise RuntimeLayoutError(
                    "--lock-file is required with --stage-software-opengl"
                )
            renderer_source, renderer_provenance = locked_conda_software_opengl(
                dict(os.environ), options.lock_file
            )
            staged_renderer = stage_software_opengl(renderer_source, directories[0])
        write_runtime_paths(directories, options.github_path, options.manifest)
        write_qt_plugin_environment(
            plugin_directory, platform_directory, options.github_env
        )
        if staged_renderer is not None and renderer_provenance is not None:
            renderer, digest = staged_renderer
            write_software_opengl_environment(
                renderer,
                digest,
                renderer_provenance,
                options.github_env,
            )
    except RuntimeLayoutError as error:
        print(f"Windows test runtime setup failed: {error}", file=sys.stderr)
        return 1

    print(
        f"Registered {len(directories)} runtime directories "
        f"containing {len(artifacts)} dynamic artifacts"
    )
    for directory in directories:
        print(f"  {directory}")
    print(f"Registered {QT_PLUGIN_PATH_VARIABLE}={plugin_directory}")
    print(f"Registered {QT_PLATFORM_PLUGIN_PATH_VARIABLE}={platform_directory}")
    if staged_renderer is not None:
        renderer, digest = staged_renderer
        print(f"Staged software OpenGL renderer={renderer} sha256={digest}")
        print(f"Locked software OpenGL package={renderer_provenance}")
        print(f"Registered {QT_OPENGL_VARIABLE}={QT_OPENGL_DESKTOP_BACKEND}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
