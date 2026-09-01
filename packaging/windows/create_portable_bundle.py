#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create and independently verify an unsigned OpenFusion Windows bundle.

The input product tree must come from ``cmake --install``. Runtime files are
selected only from files owned by packages in the active Conda prefix, and
every owning package must be present in the repository-controlled Pixi lock.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Iterable
import zipfile

import importlib.util
import sys


FORMAT_VERSION = 1
AMD64_PE_MACHINE = 0x8664
MAX_FILES = 250_000
MAX_FILE_BYTES = (2 * 1024**3) - 1
MAX_PAYLOAD_BYTES = 12 * 1024**3
COPY_CHUNK_BYTES = 1024 * 1024
FORBIDDEN_PROVIDER_NAME = "fcstdthumbnail.dll"
FORBIDDEN_PROVIDER_SHA256 = (
    "cf9985aca43c116fe3565436a9da267de8b7f17ceed8c0cae000cfb40e69a1b0"
)
IGNORED_SUFFIXES = {".pyc", ".pyo", ".a", ".lib", ".exp", ".pdb"}
REQUIRED_RUNTIME_EXECUTABLES = {"ccx.exe", "gmsh.exe", "dot.exe", "unflatten.exe"}
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class BundleError(RuntimeError):
    """A package input or produced artifact violated the bundle contract."""


_SECURITY_SPEC = importlib.util.spec_from_file_location(
    "openfusion_windows_portable_security", Path(__file__).with_name("portable_security.py")
)
if _SECURITY_SPEC is None or _SECURITY_SPEC.loader is None:
    raise RuntimeError("cannot load Windows portable security module")
security = importlib.util.module_from_spec(_SECURITY_SPEC)
sys.modules[_SECURITY_SPEC.name] = security
_SECURITY_SPEC.loader.exec_module(security)


@dataclass(frozen=True)
class PayloadEntry:
    path: PurePosixPath
    source: Path | None
    contents: bytes | None
    origin: str
    size: int
    sha256: str


@dataclass(frozen=True)
class CreateConfig:
    install_root: Path
    conda_prefix: Path
    qt_plugin_manifest: Path
    lock_file: Path
    package_cache: Path
    license_file: Path
    notice_file: Path
    output_dir: Path
    version: str
    source_revision: str
    source_date_epoch: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(COPY_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )


def _safe_relative(value: str | PurePosixPath, label: str) -> PurePosixPath:
    try:
        return security.safe_relative(value, label)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error


def _within(path: Path, root: Path, label: str) -> Path:
    try:
        return security.anchored(path, root, label)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error


def _parse_locked_conda_packages(lock_file: Path):
    try:
        security.reject_reparse_chain(lock_file)
        return security.parse_lock(lock_file)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error


def _is_ignored(relative: PurePosixPath) -> bool:
    return "__pycache__" in {part.casefold() for part in relative.parts} or relative.suffix.casefold() in IGNORED_SUFFIXES


def _runtime_destination(relative: PurePosixPath) -> PurePosixPath | None:
    if _is_ignored(relative):
        return None
    parts = relative.parts
    name = relative.name
    folded_name = name.casefold()
    if len(parts) == 1 and any(
        fnmatch.fnmatch(folded_name, pattern)
        for pattern in ("python*.*", "msvc*.*", "ucrt*.*")
    ):
        return PurePosixPath("bin") / name
    if parts[0].casefold() in {"dlls", "lib"} and len(parts) > 1:
        return PurePosixPath("bin") / PurePosixPath(*parts)
    folded = tuple(part.casefold() for part in parts)
    if len(parts) == 3 and folded[:2] == ("library", "bin"):
        if folded_name == "opengl32sw.dll":
            return None
        if relative.suffix.casefold() == ".dll" or folded_name in REQUIRED_RUNTIME_EXECUTABLES:
            return PurePosixPath("bin") / name
    if (
        len(parts) > 3
        and folded[:3] == ("library", "mingw-w64", "bin")
        and relative.suffix.casefold() == ".dll"
    ):
        return PurePosixPath("bin") / PurePosixPath(*parts[3:])
    if len(parts) > 2 and folded[:2] == ("library", "share"):
        return PurePosixPath("share") / PurePosixPath(*parts[2:])
    if len(parts) > 3 and folded[:3] == ("library", "lib", "ossl-modules"):
        return PurePosixPath("lib") / PurePosixPath(*parts[2:])
    if len(parts) > 2 and folded[:2] == ("library", "ssl"):
        return PurePosixPath("ssl") / PurePosixPath(*parts[2:])
    return None


def _read_qt_plugin_root(manifest: Path, conda_prefix: Path) -> Path:
    try:
        security.reject_reparse_chain(manifest)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    lines = [line.strip() for line in manifest.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(lines) != 2:
        raise BundleError("Qt plugin manifest must contain exactly two paths")
    plugin_root = _within(Path(lines[0]), conda_prefix, "Qt plugin root")
    platform_root = _within(Path(lines[1]), plugin_root, "Qt platform plugin root")
    if platform_root.parent != plugin_root or platform_root.name.casefold() != "platforms":
        raise BundleError("Qt platform plugin path is not the platforms child")
    return plugin_root


def _forbidden(path: PurePosixPath, digest: str) -> None:
    folded_parts = {part.casefold() for part in path.parts}
    if FORBIDDEN_PROVIDER_NAME in folded_parts or digest == FORBIDDEN_PROVIDER_SHA256:
        raise BundleError(f"quarantined thumbnail provider in payload: {path.as_posix()}")
    if path.name.casefold() == "opengl32sw.dll":
        raise BundleError(f"software renderer retained under unsafe name: {path.as_posix()}")


class PayloadBuilder:
    def __init__(self) -> None:
        self.entries: dict[PurePosixPath, PayloadEntry] = {}
        self.casefold_paths: dict[str, PurePosixPath] = {}
        self.total_size = 0

    def add_file(self, path: PurePosixPath, source: Path, origin: str) -> None:
        try:
            security.reject_reparse_chain(source)
        except security.SecurityError as error:
            raise BundleError(str(error)) from error
        source = source.resolve(strict=True)
        if not source.is_file():
            raise BundleError(f"payload input is not a regular file: {source}")
        size = source.stat().st_size
        if size > MAX_FILE_BYTES:
            raise BundleError(f"payload file exceeds size limit: {path.as_posix()}")
        digest = _sha256_file(source)
        self._add(PayloadEntry(path, source, None, origin, size, digest))

    def add_bytes(self, path: PurePosixPath, contents: bytes, origin: str) -> None:
        self._add(
            PayloadEntry(path, None, contents, origin, len(contents), hashlib.sha256(contents).hexdigest())
        )

    def _add(self, entry: PayloadEntry) -> None:
        path = _safe_relative(entry.path, "payload path")
        _forbidden(path, entry.sha256)
        try:
            folded = security.windows_alias_key(path)
        except security.SecurityError as error:
            raise BundleError(str(error)) from error
        alias = self.casefold_paths.setdefault(folded, path)
        if alias != path:
            raise BundleError(f"case-insensitive payload path collision: {alias}, {path}")
        previous = self.entries.get(path)
        if previous is not None:
            if previous.sha256 != entry.sha256 or previous.size != entry.size:
                raise BundleError(f"conflicting payload sources for {path.as_posix()}")
            return
        self.entries[path] = entry
        self.total_size += entry.size
        if len(self.entries) > MAX_FILES:
            raise BundleError("payload exceeds file-count limit")
        if self.total_size > MAX_PAYLOAD_BYTES:
            raise BundleError("payload exceeds total-size limit")


def _add_product_tree(builder: PayloadBuilder, install_root: Path) -> None:
    try:
        security.reject_reparse_chain(install_root)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    install_root = install_root.resolve(strict=True)
    for root, directories, filenames in os.walk(install_root, followlinks=False):
        root_path = Path(root)
        for directory in tuple(directories):
            candidate = root_path / directory
            if security.is_reparse(candidate):
                raise BundleError(f"installed product contains a reparse point: {candidate}")
        for filename in sorted(filenames, key=str.casefold):
            source = root_path / filename
            if security.is_reparse(source):
                raise BundleError(f"installed product contains a reparse point: {source}")
            relative = _safe_relative(source.relative_to(install_root).as_posix(), "installed path")
            builder.add_file(relative, source, "openfusion-install")


def _add_runtime(
    builder: PayloadBuilder,
    conda_prefix: Path,
    qt_plugin_root: Path,
    owned,
) -> set:
    prefix = conda_prefix.resolve(strict=True)
    plugin_relative = _safe_relative(qt_plugin_root.relative_to(prefix).as_posix(), "Qt plugin path")
    used: set = set()
    selected_sources: set[PurePosixPath] = set()

    for relative, candidates in sorted(owned.items(), key=lambda item: item[0].as_posix().encode("utf-8")):
        if relative == plugin_relative or plugin_relative in relative.parents:
            continue
        destination = _runtime_destination(relative)
        if destination is None:
            continue
        source = prefix.joinpath(*relative.parts)
        if not source.exists() or source.is_dir():
            continue
        source = _within(source, prefix, "Conda runtime file")
        try:
            owned_file = security.resolve_owned_file(source, candidates, relative)
        except security.SecurityError as error:
            raise BundleError(str(error)) from error
        owner = owned_file.owner
        builder.add_file(destination, source, f"conda:{owner.identity}")
        selected_sources.add(relative)
        used.add(owner)

    plugin_count = 0
    for relative, candidates in sorted(owned.items(), key=lambda item: item[0].as_posix().encode("utf-8")):
        if plugin_relative not in relative.parents:
            continue
        suffix = relative.relative_to(plugin_relative)
        if _is_ignored(suffix):
            continue
        source = prefix.joinpath(*relative.parts)
        if not source.exists() or source.is_dir():
            continue
        source = _within(source, prefix, "Qt plugin")
        try:
            owned_file = security.resolve_owned_file(source, candidates, relative)
        except security.SecurityError as error:
            raise BundleError(str(error)) from error
        owner = owned_file.owner
        builder.add_file(PurePosixPath("plugins") / suffix, source, f"conda:{owner.identity}")
        selected_sources.add(relative)
        used.add(owner)
        plugin_count += 1
    if plugin_count == 0:
        raise BundleError("locked Qt plugin tree is empty")

    renderer_relative = PurePosixPath("Library/bin/opengl32sw.dll")
    renderer_candidates = owned.get(renderer_relative)
    if renderer_candidates is None:
        raise BundleError("software OpenGL renderer is not owned by locked qt6-main")
    renderer = _within(prefix.joinpath(*renderer_relative.parts), prefix, "software OpenGL renderer")
    try:
        renderer_file = security.resolve_owned_file(
            renderer, renderer_candidates, renderer_relative, required_owner="qt6-main"
        )
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    renderer_owner = renderer_file.owner
    builder.add_file(PurePosixPath("bin/opengl32.dll"), renderer, f"conda:{renderer_owner.identity}")
    selected_sources.add(renderer_relative)
    used.add(renderer_owner)

    for base in (prefix / "Library" / "bin", prefix / "DLLs", qt_plugin_root):
        if not base.exists():
            continue
        for candidate in base.rglob("*"):
            if not candidate.is_file() or candidate.suffix.casefold() not in {".exe", ".dll", ".pyd"}:
                continue
            relative = _safe_relative(candidate.relative_to(prefix).as_posix(), "native runtime path")
            if relative == renderer_relative or relative in selected_sources:
                continue
            if relative not in owned:
                raise BundleError(f"unowned native runtime file in active prefix: {relative}")

    return used


def _require_payload(builder: PayloadBuilder) -> None:
    required = (
        "bin/OpenFusion.exe",
        "bin/OpenFusionCmd.exe",
        "bin/python.exe",
        "bin/python311.dll",
        "bin/DLLs/_ssl.pyd",
        "bin/ccx.exe",
        "bin/gmsh.exe",
        "bin/dot.exe",
        "bin/unflatten.exe",
        "bin/opengl32.dll",
        "bin/python311._pth",
        "OpenFusionPython.cmd",
        "plugins/platforms/qwindows.dll",
        "plugins/platforms/qoffscreen.dll",
        "ssl/openssl.cnf",
        "ssl/cacert.pem",
        "lib/ossl-modules/legacy.dll",
        "COPYING",
        "NOTICE.md",
        "share/doc/openfusion/LICENSE",
        "share/doc/openfusion/NOTICE.md",
        "share/doc/openfusion/THIRD_PARTY_NOTICES.md",
    )
    folded = {path.as_posix().casefold() for path in builder.entries}
    missing = [path for path in required if path.casefold() not in folded]
    if missing:
        raise BundleError(f"portable payload is missing required files: {', '.join(missing)}")


def _zip_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    try:
        moment = datetime.fromtimestamp(epoch, timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise BundleError("SOURCE_DATE_EPOCH is outside the supported range") from error
    if moment.year < 1980 or moment.year > 2107:
        raise BundleError("SOURCE_DATE_EPOCH is outside the ZIP timestamp range")
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second // 2 * 2)


def _write_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, entry: PayloadEntry) -> None:
    with archive.open(info, "w", force_zip64=False) as destination:
        if entry.contents is not None:
            destination.write(entry.contents)
        elif entry.source is not None:
            with entry.source.open("rb") as source:
                shutil.copyfileobj(source, destination, COPY_CHUNK_BYTES)
        else:
            raise AssertionError("payload entry has no contents")


def create_bundle(config: CreateConfig) -> tuple[Path, Path, Path]:
    if not VERSION_RE.fullmatch(config.version):
        raise BundleError(f"invalid OpenFusion version: {config.version!r}")
    revision = config.source_revision.lower()
    if not REVISION_RE.fullmatch(revision):
        raise BundleError(f"invalid source revision: {config.source_revision!r}")
    lock_file = config.lock_file.resolve(strict=True)
    lock_sha256 = _sha256_file(lock_file)
    locked = _parse_locked_conda_packages(lock_file)
    try:
        owned, _ = security.load_conda_ownership(
            config.conda_prefix.resolve(strict=True), locked, config.package_cache.resolve(strict=True)
        )
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    qt_plugin_root = _read_qt_plugin_root(config.qt_plugin_manifest, config.conda_prefix)

    builder = PayloadBuilder()
    _add_product_tree(builder, config.install_root)
    used_packages = _add_runtime(builder, config.conda_prefix, qt_plugin_root, owned)
    builder.add_file(PurePosixPath("COPYING"), config.license_file, "openfusion-source")
    builder.add_file(PurePosixPath("NOTICE.md"), config.notice_file, "openfusion-source")
    builder.add_bytes(
        PurePosixPath("bin/qt6.conf"),
        b"[Paths]\r\nPrefix = ..\r\nPlugins = plugins\r\nTranslations = share/qt6/translations\r\n",
        "openfusion-packager",
    )
    builder.add_bytes(
        PurePosixPath("bin/python311._pth"),
        b"Lib\r\nLib\\site-packages\r\nDLLs\r\nimport site\r\n",
        "openfusion-packager",
    )
    builder.add_bytes(
        PurePosixPath("OpenFusion.cmd"),
        b"@echo off\r\nset \"CONDA_PREFIX=\"\r\nset \"PYTHONPATH=\"\r\nset \"PYTHONHOME=%~dp0bin\"\r\nset \"PATH=%~dp0bin;%SystemRoot%\\System32;%SystemRoot%\"\r\nset \"QT_PLUGIN_PATH=%~dp0plugins\"\r\nset \"QT_QPA_PLATFORM_PLUGIN_PATH=%~dp0plugins\\platforms\"\r\nset \"QT_OPENGL=desktop\"\r\nset \"OPENSSL_CONF=%~dp0ssl\\openssl.cnf\"\r\nset \"SSL_CERT_FILE=%~dp0ssl\\cacert.pem\"\r\nset \"OPENSSL_MODULES=%~dp0lib\\ossl-modules\"\r\nset \"OPENFUSION_PORTABLE_ROOT=%~dp0\"\r\n\"%~dp0bin\\OpenFusion.exe\" %*\r\n",
        "openfusion-packager",
    )
    builder.add_bytes(
        PurePosixPath("OpenFusionCmd.cmd"),
        b"@echo off\r\nset \"CONDA_PREFIX=\"\r\nset \"PYTHONPATH=\"\r\nset \"PYTHONHOME=%~dp0bin\"\r\nset \"PATH=%~dp0bin;%SystemRoot%\\System32;%SystemRoot%\"\r\nset \"QT_PLUGIN_PATH=%~dp0plugins\"\r\nset \"QT_QPA_PLATFORM_PLUGIN_PATH=%~dp0plugins\\platforms\"\r\nset \"QT_OPENGL=desktop\"\r\nset \"OPENSSL_CONF=%~dp0ssl\\openssl.cnf\"\r\nset \"SSL_CERT_FILE=%~dp0ssl\\cacert.pem\"\r\nset \"OPENSSL_MODULES=%~dp0lib\\ossl-modules\"\r\nset \"OPENFUSION_PORTABLE_ROOT=%~dp0\"\r\n\"%~dp0bin\\OpenFusionCmd.exe\" %*\r\n",
        "openfusion-packager",
    )
    builder.add_bytes(
        PurePosixPath("OpenFusionPython.cmd"),
        b"@echo off\r\nset \"CONDA_PREFIX=\"\r\nset \"PYTHONPATH=\"\r\nset \"PYTHONHOME=%~dp0bin\"\r\nset \"PATH=%~dp0bin;%SystemRoot%\\System32;%SystemRoot%\"\r\nset \"QT_PLUGIN_PATH=%~dp0plugins\"\r\nset \"QT_QPA_PLATFORM_PLUGIN_PATH=%~dp0plugins\\platforms\"\r\nset \"QT_OPENGL=desktop\"\r\nset \"OPENSSL_CONF=%~dp0ssl\\openssl.cnf\"\r\nset \"SSL_CERT_FILE=%~dp0ssl\\cacert.pem\"\r\nset \"OPENSSL_MODULES=%~dp0lib\\ossl-modules\"\r\nset \"OPENFUSION_PORTABLE_ROOT=%~dp0\"\r\n\"%~dp0bin\\python.exe\" %*\r\n",
        "openfusion-packager",
    )
    _require_payload(builder)
    native_contents = {}
    for entry in builder.entries.values():
        if entry.path.suffix.casefold() not in {".exe", ".dll", ".pyd"}:
            continue
        if entry.size > security.MAX_PE_BYTES:
            raise BundleError(f"PE exceeds inspection limit: {entry.path}")
        native_contents[entry.path] = (
            entry.contents if entry.contents is not None else entry.source.read_bytes()
        )
    try:
        api_contracts, api_set_evidence = security.api_set_contract()
        pe_dependencies = security.pe_evidence(native_contents, api_contracts)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error

    artifact_name = f"OpenFusion-{config.version}-Windows-x86_64-unsigned.zip"
    archive_root = artifact_name[: -len("-unsigned.zip")]
    manifest_name = f"{artifact_name}.manifest.json"
    checksum_name = f"{artifact_name}.sha256"
    payload_entries = sorted(builder.entries.values(), key=lambda entry: entry.path.as_posix().encode("utf-8"))
    manifest = {
        "api_set_contract": api_set_evidence,
        "architecture": "x86_64",
        "archive_root": archive_root,
        "artifact": artifact_name,
        "canonical_entrypoints": ["bin/OpenFusion.exe", "bin/OpenFusionCmd.exe"],
        "entries": [
            {
                "origin": entry.origin,
                "path": entry.path.as_posix(),
                "sha256": entry.sha256,
                "size": entry.size,
            }
            for entry in payload_entries
        ],
        "format_version": FORMAT_VERSION,
        "legal_policy_sha256": security.legal_policy_sha256(),
        "pe_dependencies": pe_dependencies,
        "pixi_lock_sha256": lock_sha256,
        "platform": "windows",
        "relocation": security.RELOCATION,
        "runtime_packages": [
            {
                "build": owner.build,
                "name": owner.name,
                "package_sha256": owner.package_sha256,
                "package_size": owner.package_size,
                "subdir": owner.subdir,
                "url": owner.url,
                "version": owner.version,
            }
            for owner in sorted(
                used_packages, key=lambda value: (value.name, value.version, value.build, value.url)
            )
        ],
        "source_date_epoch": config.source_date_epoch,
        "source_revision": revision,
        "system_dll_policy_sha256": security.system_policy_sha256(),
        "unsigned_development_artifact": True,
        "version": config.version,
    }
    manifest_bytes = _canonical_json(manifest)
    embedded_manifest = PayloadEntry(
        PurePosixPath("manifest.json"),
        None,
        manifest_bytes,
        "openfusion-packager",
        len(manifest_bytes),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    archive_entries = sorted(
        (*payload_entries, embedded_manifest),
        key=lambda entry: entry.path.as_posix().encode("utf-8"),
    )
    timestamp = _zip_datetime(config.source_date_epoch)
    output_dir = config.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / artifact_name
    manifest_path = output_dir / manifest_name
    checksum_path = output_dir / checksum_name
    try:
        security.reject_reparse_chain(output_dir)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    for destination in (archive_path, manifest_path, checksum_path):
        if destination.exists() or destination.is_symlink():
            raise BundleError(f"refusing to replace existing package output: {destination}")

    with tempfile.TemporaryDirectory(prefix=".openfusion-windows-", dir=output_dir) as temporary:
        temporary_root = Path(temporary)
        temporary_archive = temporary_root / artifact_name
        with zipfile.ZipFile(
            temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
        ) as archive:
            for entry in archive_entries:
                info = zipfile.ZipInfo(f"{archive_root}/{entry.path.as_posix()}", timestamp)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                _write_zip_member(archive, info, entry)
        archive_digest = _sha256_file(temporary_archive)
        temporary_manifest = temporary_root / manifest_name
        temporary_checksum = temporary_root / checksum_name
        temporary_manifest.write_bytes(manifest_bytes)
        temporary_checksum.write_text(f"{archive_digest}  {artifact_name}\n", encoding="ascii")
        verify_bundle(
            temporary_archive,
            temporary_manifest,
            temporary_checksum,
            expected_version=config.version,
            expected_source_revision=revision,
            expected_lock_sha256=lock_sha256,
        )
        published = []
        try:
            for source, destination in (
                (temporary_manifest, manifest_path),
                (temporary_checksum, checksum_path),
                (temporary_archive, archive_path),
            ):
                os.link(source, destination)
                published.append(destination)
            verify_bundle(
                archive_path,
                manifest_path,
                checksum_path,
                expected_version=config.version,
                expected_source_revision=revision,
                expected_lock_sha256=lock_sha256,
            )
        except Exception:
            for destination in reversed(published):
                destination.unlink(missing_ok=True)
            raise
    return archive_path, manifest_path, checksum_path


def verify_bundle(
    archive_path: Path,
    manifest_path: Path,
    checksum_path: Path,
    *,
    expected_version: str,
    expected_source_revision: str,
    expected_lock_sha256: str,
) -> None:
    try:
        for path in (archive_path, manifest_path, checksum_path):
            security.reject_reparse_chain(path)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    archive_path = archive_path.resolve(strict=True)
    if manifest_path.name != f"{archive_path.name}.manifest.json":
        raise BundleError("portable manifest filename is not canonical")
    if checksum_path.name != f"{archive_path.name}.sha256":
        raise BundleError("portable checksum filename is not canonical")
    manifest_bytes = manifest_path.resolve(strict=True).read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise BundleError("portable manifest is invalid JSON") from error
    if _canonical_json(manifest) != manifest_bytes:
        raise BundleError("portable manifest is not canonical JSON")
    try:
        security.validate_manifest_schema(manifest)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error
    expected_coordinates = (
        manifest.get("format_version") == FORMAT_VERSION,
        manifest.get("artifact") == archive_path.name,
        manifest.get("version") == expected_version,
        manifest.get("source_revision") == expected_source_revision.lower(),
        manifest.get("pixi_lock_sha256") == expected_lock_sha256.lower(),
        manifest.get("unsigned_development_artifact") is True,
        manifest.get("platform") == "windows",
        manifest.get("architecture") == "x86_64",
        manifest.get("legal_policy_sha256") == security.legal_policy_sha256(),
        manifest.get("system_dll_policy_sha256") == security.system_policy_sha256(),
        manifest.get("api_set_contract") == security.api_set_contract()[1],
    )
    if not all(expected_coordinates):
        raise BundleError("portable manifest coordinates do not match expectations")
    archive_digest = _sha256_file(archive_path)
    checksum = checksum_path.resolve(strict=True).read_text(encoding="ascii")
    if checksum != f"{archive_digest}  {archive_path.name}\n":
        raise BundleError("portable archive checksum does not match")

    records = manifest.get("entries")
    if not isinstance(records, list) or not records or len(records) > MAX_FILES:
        raise BundleError("portable manifest has an invalid entry inventory")
    expected: dict[str, dict[str, object]] = {}
    expected_casefold: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"origin", "path", "sha256", "size"}:
            raise BundleError("portable manifest entry is not an object")
        relative = _safe_relative(str(record.get("path", "")), "manifest path")
        digest = str(record.get("sha256", "")).lower()
        size = record.get("size")
        if not SHA256_RE.fullmatch(digest) or not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise BundleError(f"portable manifest entry is invalid: {relative}")
        try:
            folded = security.windows_alias_key(relative)
        except security.SecurityError as error:
            raise BundleError(str(error)) from error
        if folded in expected_casefold:
            raise BundleError(f"case-insensitive manifest collision: {relative}")
        expected_casefold.add(folded)
        expected[relative.as_posix()] = record
        _forbidden(relative, digest)

    archive_root = str(manifest.get("archive_root", ""))
    _safe_relative(archive_root, "archive root")
    source_date_epoch = manifest.get("source_date_epoch")
    if not isinstance(source_date_epoch, int):
        raise BundleError("portable manifest has an invalid source timestamp")
    expected_timestamp = _zip_datetime(source_date_epoch)
    seen: set[str] = set()
    previous_name: bytes | None = None
    total = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        if archive.comment:
            raise BundleError("portable archive comment is forbidden")
        native_contents = {}
        for info in archive.infolist():
            try:
                security.validate_zip_info(archive_path, archive, info)
            except security.SecurityError as error:
                raise BundleError(str(error)) from error
            if (
                info.date_time != expected_timestamp
                or info.create_system != 3
                or ((info.external_attr >> 16) & 0o777) != 0o644
                or info.compress_type != zipfile.ZIP_DEFLATED
            ):
                raise BundleError(f"portable archive metadata is not normalized: {info.filename}")
            encoded_name = info.filename.encode("utf-8")
            if previous_name is not None and encoded_name <= previous_name:
                raise BundleError("portable archive members are not strictly sorted")
            previous_name = encoded_name
            prefix = f"{archive_root}/"
            if not info.filename.startswith(prefix) or info.is_dir():
                raise BundleError(f"unexpected portable archive member: {info.filename}")
            relative_text = info.filename[len(prefix) :]
            relative = _safe_relative(relative_text, "archive member")
            if relative_text == "manifest.json":
                if archive.read(info) != manifest_bytes:
                    raise BundleError("embedded portable manifest does not match")
                continue
            record = expected.get(relative_text)
            if record is None or relative_text in seen:
                raise BundleError(f"unexpected or duplicate portable member: {relative_text}")
            if info.file_size != record["size"]:
                raise BundleError(f"portable member size mismatch: {relative_text}")
            digest = hashlib.sha256()
            native_payload = (
                bytearray() if relative.suffix.casefold() in {".exe", ".dll", ".pyd"} else None
            )
            with archive.open(info, "r") as source:
                for chunk in iter(lambda: source.read(COPY_CHUNK_BYTES), b""):
                    digest.update(chunk)
                    if native_payload is not None:
                        if len(native_payload) + len(chunk) > security.MAX_PE_BYTES:
                            raise BundleError(f"PE exceeds inspection limit: {relative_text}")
                        native_payload.extend(chunk)
            if digest.hexdigest() != record["sha256"]:
                raise BundleError(f"portable member hash mismatch: {relative_text}")
            if native_payload is not None:
                native_contents[relative] = bytes(native_payload)
            seen.add(relative_text)
            total += info.file_size
            if total > MAX_PAYLOAD_BYTES:
                raise BundleError("portable archive exceeds total-size limit")
    if seen != set(expected):
        raise BundleError("portable archive is missing manifested payload entries")
    try:
        if manifest.get("pe_dependencies") != security.pe_evidence(
            native_contents, security.api_set_contract()[0]
        ):
            raise BundleError("portable PE dependency evidence differs from payload")
        security.verify_legal_archive(archive_path, archive_root)
    except security.SecurityError as error:
        raise BundleError(str(error)) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    for argument in (
        "install-root",
        "conda-prefix",
        "qt-plugin-manifest",
        "lock-file",
        "package-cache",
        "license-file",
        "notice-file",
        "output-dir",
        "version",
        "source-revision",
        "source-date-epoch",
    ):
        create.add_argument(f"--{argument}", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--checksum", required=True)
    verify.add_argument("--expected-version", required=True)
    verify.add_argument("--expected-source-revision", required=True)
    verify.add_argument("--expected-lock-sha256", required=True)
    fetch = subparsers.add_parser("fetch-cache")
    fetch.add_argument("--lock-file", required=True)
    fetch.add_argument("--package-cache", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "create":
            archive, manifest, checksum = create_bundle(
                CreateConfig(
                    install_root=Path(arguments.install_root),
                    conda_prefix=Path(arguments.conda_prefix),
                    qt_plugin_manifest=Path(arguments.qt_plugin_manifest),
                    lock_file=Path(arguments.lock_file),
                    package_cache=Path(arguments.package_cache),
                    license_file=Path(arguments.license_file),
                    notice_file=Path(arguments.notice_file),
                    output_dir=Path(arguments.output_dir),
                    version=arguments.version,
                    source_revision=arguments.source_revision,
                    source_date_epoch=int(arguments.source_date_epoch),
                )
            )
            print(json.dumps({"archive": str(archive), "checksum": str(checksum), "manifest": str(manifest)}, sort_keys=True))
        elif arguments.command == "fetch-cache":
            lock = _parse_locked_conda_packages(Path(arguments.lock_file))
            try:
                security.fetch_archives(lock, Path(arguments.package_cache))
            except security.SecurityError as error:
                raise BundleError(str(error)) from error
            print("OpenFusion locked Conda archive cache authenticated")
        else:
            verify_bundle(
                Path(arguments.archive),
                Path(arguments.manifest),
                Path(arguments.checksum),
                expected_version=arguments.expected_version,
                expected_source_revision=arguments.expected_source_revision,
                expected_lock_sha256=arguments.expected_lock_sha256,
            )
            print("OpenFusion Windows portable bundle verified")
    except (BundleError, OSError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"error: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
