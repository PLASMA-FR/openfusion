#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create and verify the gated OpenFusion Linux tar.zst staging artifact.

This tool only packages an existing DESTDIR/prefix installation.  It does not
install, rename, patch, or otherwise modify the staged application.
"""

from __future__ import annotations

import argparse
from collections import deque
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Sequence


FORMAT_VERSION = 3
POLICY_VERSION = 2
MAX_SOURCE_DATE_EPOCH = (1 << 33) - 1
MAX_ARCHIVE_BYTES = 16 * 1024**3
MAX_MANIFEST_BYTES = 256 * 1024**2
MAX_CHECKSUM_BYTES = 4096
MAX_ENTRIES = 500_000
MAX_PATH_BYTES = 4095
MAX_TARGET_BYTES = 4095
MAX_PAX_HEADER_BYTES = 64 * 1024
MAX_FILE_BYTES = (1 << 33) - 1
MAX_TOTAL_FILE_BYTES = 32 * 1024**3
MAX_TAR_BYTES = 40 * 1024**3
MAX_SYMLINK_HOPS = 40
MAX_SYMLINK_GRAPH_STEPS = 2_000_000
ZSTD_MEMORY_MIB = 512
PRODUCT_IDENTITY_BLOCKER = (
    "production packaging is blocked: no authenticated OpenFusion executable identity "
    "contract is configured"
)
POLICY_LIMITS = {
    "archive_bytes": MAX_ARCHIVE_BYTES,
    "checksum_bytes": MAX_CHECKSUM_BYTES,
    "entries": MAX_ENTRIES,
    "file_bytes": MAX_FILE_BYTES,
    "manifest_bytes": MAX_MANIFEST_BYTES,
    "path_bytes": MAX_PATH_BYTES,
    "pax_header_bytes": MAX_PAX_HEADER_BYTES,
    "symlink_target_bytes": MAX_TARGET_BYTES,
    "symlink_hops": MAX_SYMLINK_HOPS,
    "symlink_graph_steps": MAX_SYMLINK_GRAPH_STEPS,
    "tar_bytes": MAX_TAR_BYTES,
    "total_file_bytes": MAX_TOTAL_FILE_BYTES,
    "zstd_memory_mib": ZSTD_MEMORY_MIB,
}
SUPPORTED_ARCHITECTURES = {
    "x86_64": {"elf_class": 2, "elf_data": 1, "elf_machine": 62},
}
SEMVER_RE = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
READ_SIZE = 1024 * 1024


class PackagingError(RuntimeError):
    """Raised when a stage or artifact violates the packaging contract."""


@dataclass(frozen=True)
class Snapshot:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    link_count: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "Snapshot":
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            size=value.st_size,
            mtime_ns=value.st_mtime_ns,
            ctime_ns=value.st_ctime_ns,
            link_count=value.st_nlink,
        )


@dataclass(frozen=True)
class SourceRecord:
    relative_path: str
    kind: str
    mode: int
    size: int
    sha256: str | None
    link_target: str | None
    snapshot: Snapshot
    elf_identity: tuple[int, int, int] | None

    def manifest_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "mode": self.mode,
            "path": self.relative_path,
            "type": self.kind,
        }
        if self.kind == "file":
            record["sha256"] = self.sha256
            record["size"] = self.size
        elif self.kind == "symlink":
            record["target"] = self.link_target
        return record


@dataclass(frozen=True)
class SourceScan:
    root_snapshot: Snapshot
    records: tuple[SourceRecord, ...]


@dataclass(frozen=True)
class Entry:
    relative_path: str
    source_path: Path
    kind: str
    mode: int
    size: int
    sha256: str | None
    link_target: str | None
    snapshot: Snapshot

    def manifest_record(self) -> dict[str, object]:
        record: dict[str, object] = {
            "mode": self.mode,
            "path": self.relative_path,
            "type": self.kind,
        }
        if self.kind == "file":
            record["sha256"] = self.sha256
            record["size"] = self.size
        elif self.kind == "symlink":
            record["target"] = self.link_target
        return record


class DigestingReader:
    """A minimal reader that hashes exactly the bytes consumed by tarfile."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self._digest.update(data)
        self.bytes_read += len(data)
        return data

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _validate_text(value: str, label: str) -> None:
    if not value:
        raise PackagingError(f"{label} must not be empty")
    if "\x00" in value or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise PackagingError(f"{label} is not valid UTF-8 text")


def _validate_version(version: str) -> str:
    _validate_text(version, "version")
    if len(version.encode("utf-8")) > 80:
        raise PackagingError(
            f"version is not a supported semantic version: {version!r}"
        )
    match = SEMVER_RE.fullmatch(version)
    if match is None:
        raise PackagingError(
            f"version is not a supported semantic version: {version!r}"
        )
    prerelease = match.group("prerelease")
    if prerelease is not None:
        for identifier in prerelease.split("."):
            if (
                identifier.isdecimal()
                and len(identifier) > 1
                and identifier.startswith("0")
            ):
                raise PackagingError(
                    "numeric semantic-version prerelease identifier has a leading zero: "
                    f"{identifier}"
                )
    return version


def _validate_architecture(architecture: str) -> str:
    if architecture not in SUPPORTED_ARCHITECTURES:
        supported = ", ".join(sorted(SUPPORTED_ARCHITECTURES))
        raise PackagingError(
            f"target architecture must be explicitly selected from: {supported}"
        )
    return architecture


def _validate_prefix(prefix: str) -> PurePosixPath:
    _validate_text(prefix, "install prefix")
    if not prefix.startswith("/") or prefix.startswith("//"):
        raise PackagingError("install prefix must be an absolute POSIX path")
    if prefix != "/" and prefix.endswith("/"):
        raise PackagingError("install prefix must not have a trailing slash")
    components = prefix.split("/")[1:]
    if any(component in {"", ".", ".."} for component in components):
        raise PackagingError(
            "install prefix must be normalized and contain no dot components"
        )
    return PurePosixPath(prefix)


def _canonical_directory(path_value: str | Path, label: str) -> Path:
    raw_path = os.fspath(path_value)
    if (
        not os.path.isabs(raw_path)
        or raw_path.startswith("//")
        or raw_path != os.path.normpath(raw_path)
    ):
        raise PackagingError(f"{label} must be a normalized absolute path: {raw_path}")
    path = Path(raw_path)
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as error:
        raise PackagingError(f"cannot access {label} {path}: {error}") from error
    if path != resolved:
        raise PackagingError(
            f"{label} must be canonical and must not traverse symlinks: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise PackagingError(f"{label} is not a directory: {path}")
    return path


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _open_directory(path: Path, label: str) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = next_descriptor
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise PackagingError(f"{label} is not a directory: {path}")
        return current
    except OSError as error:
        os.close(current)
        raise PackagingError(f"cannot safely open {label} {path}: {error}") from error
    except Exception:
        os.close(current)
        raise


def _open_prefix_at(destdir_descriptor: int, prefix: PurePosixPath) -> int:
    current = os.dup(destdir_descriptor)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for component in prefix.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = next_descriptor
        return current
    except OSError as error:
        os.close(current)
        raise PackagingError(
            f"installed prefix cannot be opened without following symlinks: {prefix}: {error}"
        ) from error


def _remove_tree_at(parent_descriptor: int, name: str) -> None:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        os.fchmod(directory, 0o700)
        for child in os.listdir(directory):
            metadata = os.stat(child, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                _remove_tree_at(directory, child)
            else:
                os.unlink(child, dir_fd=directory)
    finally:
        os.close(directory)
    os.rmdir(name, dir_fd=parent_descriptor)


@contextlib.contextmanager
def _private_output_workspace(output_descriptor: int) -> Iterator[tuple[str, int]]:
    private_name = ""
    for _ in range(128):
        candidate = f".openfusion-package-{secrets.token_hex(16)}"
        try:
            os.mkdir(candidate, 0o700, dir_fd=output_descriptor)
            private_name = candidate
            break
        except FileExistsError:
            continue
    if not private_name:
        raise PackagingError("could not allocate a private packaging workspace")
    private_descriptor: int | None = None
    try:
        private_descriptor = _open_prefix_at(
            output_descriptor, PurePosixPath(f"/{private_name}")
        )
        if stat.S_IMODE(os.fstat(private_descriptor).st_mode) != 0o700:
            raise PackagingError("private packaging workspace mode is not 0700")
        yield private_name, private_descriptor
    finally:
        if private_descriptor is not None:
            os.close(private_descriptor)
        try:
            _remove_tree_at(output_descriptor, private_name)
        except FileNotFoundError:
            pass


def _descriptor_path(descriptor: int, child: str = "") -> Path:
    base = Path(f"/proc/self/fd/{descriptor}")
    return base / child if child else base


def _require_directory_identity(
    path: Path, expected_descriptor: int, label: str
) -> None:
    reopened = _open_directory(path, label)
    try:
        expected = os.fstat(expected_descriptor)
        current = os.fstat(reopened)
        if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
            raise PackagingError(f"{label} path was replaced during packaging")
    finally:
        os.close(reopened)


def _directory_descriptor_is_within(
    child_descriptor: int, parent_descriptor: int
) -> bool:
    """Check directory ancestry by identity, including bind-mounted aliases."""

    target = os.fstat(parent_descriptor)
    target_identity = (target.st_dev, target.st_ino)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.dup(child_descriptor)
    try:
        for _ in range(MAX_PATH_BYTES):
            metadata = os.fstat(current)
            current_identity = (metadata.st_dev, metadata.st_ino)
            if current_identity == target_identity:
                return True
            ancestor = os.open("..", directory_flags, dir_fd=current)
            try:
                ancestor_metadata = os.fstat(ancestor)
            except Exception:
                os.close(ancestor)
                raise
            ancestor_identity = (ancestor_metadata.st_dev, ancestor_metadata.st_ino)
            if ancestor_identity == current_identity:
                os.close(ancestor)
                return False
            os.close(current)
            current = ancestor
    except OSError as error:
        raise PackagingError(
            f"cannot validate output directory ancestry: {error}"
        ) from error
    finally:
        os.close(current)
    raise PackagingError("output directory ancestry exceeds the safety bound")


def _validate_relative_path(relative_path: str) -> None:
    _validate_text(relative_path, "archive path")
    if len(relative_path.encode("utf-8")) > MAX_PATH_BYTES:
        raise PackagingError(
            f"archive path exceeds the policy limit: {relative_path!r}"
        )
    path = PurePosixPath(relative_path)
    if path.is_absolute() or str(path) != relative_path:
        raise PackagingError(f"archive path is not normalized: {relative_path!r}")
    if any(component in {"", ".", ".."} for component in path.parts):
        raise PackagingError(
            f"archive path contains an unsafe component: {relative_path!r}"
        )


def _validate_symlink(relative_path: str, target: str) -> None:
    _validate_text(target, f"symlink target for {relative_path}")
    if len(target.encode("utf-8")) > MAX_TARGET_BYTES:
        raise PackagingError(
            f"symlink target exceeds the policy limit: {relative_path}"
        )
    if target.startswith("/"):
        raise PackagingError(
            f"absolute symlink is not relocatable: {relative_path} -> {target}"
        )
    resolved_components = list(PurePosixPath(relative_path).parts[:-1])
    for component in target.split("/"):
        if component in {"", "."}:
            continue
        if component == "..":
            if not resolved_components:
                raise PackagingError(
                    f"symlink escapes the packaged prefix: {relative_path} -> {target}"
                )
            resolved_components.pop()
        else:
            _validate_text(component, f"symlink target component for {relative_path}")
            resolved_components.append(component)


def _validate_symlink_graph(
    records: Sequence[tuple[str, str, str | None]],
    *,
    maximum_steps: int = MAX_SYMLINK_GRAPH_STEPS,
) -> None:
    """Resolve every symlink against the complete payload graph."""

    if (
        type(maximum_steps) is not int
        or maximum_steps <= 0
        or maximum_steps > MAX_SYMLINK_GRAPH_STEPS
    ):
        raise PackagingError("symlink graph work budget is invalid")

    entry_types: dict[str, str] = {}
    symlink_targets: dict[str, str] = {}
    for relative_path, kind, target in records:
        if relative_path in entry_types:
            raise PackagingError(f"duplicate payload path: {relative_path}")
        entry_types[relative_path] = kind
        if kind == "symlink":
            if target is None:
                raise PackagingError(f"symlink target is missing: {relative_path}")
            _validate_symlink(relative_path, target)
            symlink_targets[relative_path] = target

    steps = 0

    def consume_step() -> None:
        nonlocal steps
        steps += 1
        if steps > maximum_steps:
            raise PackagingError(
                f"symlink graph exceeds the {maximum_steps}-step work budget"
            )

    for link_path, initial_target in symlink_targets.items():
        consume_step()
        resolved = list(PurePosixPath(link_path).parent.parts)
        pending = deque(initial_target.split("/"))
        seen_states: set[tuple[str, tuple[str, ...]]] = set()
        hops = 1
        while pending:
            consume_step()
            component = pending.popleft()
            if component in {"", "."}:
                continue
            if component == "..":
                if not resolved:
                    raise PackagingError(
                        f"composed symlink escapes the packaged prefix: {link_path}"
                    )
                resolved.pop()
                continue

            resolved.append(component)
            candidate = "/".join(resolved)
            kind = entry_types.get(candidate)
            if kind == "symlink":
                hops += 1
                state = (candidate, tuple(pending))
                if state in seen_states:
                    raise PackagingError(
                        f"symlink cycle is forbidden: {link_path} reaches {candidate}"
                    )
                if hops > MAX_SYMLINK_HOPS:
                    raise PackagingError(
                        f"symlink resolution exceeds {MAX_SYMLINK_HOPS} hops: {link_path}"
                    )
                seen_states.add(state)
                resolved.pop()
                for target_component in reversed(symlink_targets[candidate].split("/")):
                    pending.appendleft(target_component)
            elif pending and kind != "directory":
                detail = "missing" if kind is None else kind
                raise PackagingError(
                    f"symlink traverses a non-directory payload entry ({detail}): "
                    f"{link_path} through {candidate}"
                )

        final_path = "/".join(resolved)
        final_kind = "directory" if not final_path else entry_types.get(final_path)
        if final_kind is None:
            raise PackagingError(
                f"dangling symlink is forbidden: {link_path} resolves to {final_path}"
            )


def _product_identity_status(version: str, allow_test_bypass: bool) -> str:
    if not allow_test_bypass:
        raise PackagingError(PRODUCT_IDENTITY_BLOCKER)
    match = SEMVER_RE.fullmatch(version)
    assert match is not None
    prerelease = match.group("prerelease") or ""
    if "test" not in prerelease.split("."):
        raise PackagingError(
            "test-only product identity bypass requires a SemVer prerelease identifier "
            "named test"
        )
    return "test-only-bypass"


def _normalized_mode(metadata: os.stat_result, kind: str) -> int:
    if kind == "file":
        return 0o755 if metadata.st_mode & 0o111 else 0o644
    if kind == "directory":
        return 0o755
    if kind == "symlink":
        return 0o777
    raise AssertionError(f"unrecognized entry kind: {kind}")


def _reject_privileged_mode(metadata: os.stat_result, relative_path: str) -> None:
    if metadata.st_mode & 0o7000:
        raise PackagingError(
            f"setuid, setgid, and sticky mode bits are forbidden: {relative_path or '.'}"
        )


def _reject_xattrs_fd(descriptor: int, relative_path: str) -> None:
    try:
        attributes = os.listxattr(descriptor)
    except OSError as error:
        raise PackagingError(
            f"cannot prove xattr/ACL/capability absence for {relative_path or '.'}: {error}"
        ) from error
    if attributes:
        detail = ", ".join(sorted(attributes))
        raise PackagingError(
            f"xattrs, ACLs, and file capabilities are not preserved and are forbidden on "
            f"{relative_path or '.'}: {detail}"
        )


def _reject_symlink_xattrs(
    parent_descriptor: int, name: str, relative_path: str
) -> None:
    anchored_path = f"/proc/self/fd/{parent_descriptor}/{name}"
    try:
        attributes = os.listxattr(anchored_path, follow_symlinks=False)
    except OSError as error:
        raise PackagingError(
            f"cannot prove symlink xattr absence for {relative_path}: {error}"
        ) from error
    if attributes:
        detail = ", ".join(sorted(attributes))
        raise PackagingError(
            f"xattrs are forbidden on symlink {relative_path}: {detail}"
        )


def _reject_sparse_file(metadata: os.stat_result, relative_path: str) -> None:
    allocated_bytes = getattr(metadata, "st_blocks", 0) * 512
    if metadata.st_size > 0 and allocated_bytes < metadata.st_size:
        raise PackagingError(f"sparse staged files are forbidden: {relative_path}")


def _elf_identity(header: bytes, relative_path: str) -> tuple[int, int, int] | None:
    if not header.startswith(b"\x7fELF"):
        return None
    if len(header) < 24:
        raise PackagingError(f"truncated ELF header: {relative_path}")
    elf_class = header[4]
    elf_data = header[5]
    if elf_class not in {1, 2} or elf_data not in {1, 2}:
        raise PackagingError(f"invalid ELF class or byte order: {relative_path}")
    byte_order = "little" if elf_data == 1 else "big"
    elf_type = int.from_bytes(header[16:18], byte_order)
    elf_machine = int.from_bytes(header[18:20], byte_order)
    elf_version = int.from_bytes(header[20:24], byte_order)
    if header[6] != 1 or elf_version != 1 or elf_type not in {1, 2, 3, 4}:
        raise PackagingError(f"invalid ELF identity header: {relative_path}")
    return elf_class, elf_data, elf_machine


def _validate_elf_identity(
    identity: tuple[int, int, int], relative_path: str, architecture: str
) -> None:
    expected = SUPPORTED_ARCHITECTURES[architecture]
    expected_identity = (
        expected["elf_class"],
        expected["elf_data"],
        expected["elf_machine"],
    )
    if identity != expected_identity:
        raise PackagingError(
            f"ELF architecture mismatch for {relative_path}: {identity} != "
            f"{expected_identity} ({architecture})"
        )


def _sorted_directory_names(descriptor: int, relative_path: str) -> list[str]:
    try:
        names = os.listdir(descriptor)
        names.sort(key=lambda name: name.encode("utf-8", errors="strict"))
    except (OSError, UnicodeError) as error:
        raise PackagingError(
            f"cannot enumerate staged directory {relative_path or '.'}: {error}"
        ) from error
    for name in names:
        _validate_text(name, f"filename under {relative_path or '.'}")
    return names


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise PackagingError("short write while creating private snapshot")
        view = view[written:]


def _copy_and_hash_regular_file(
    source_directory: int,
    destination_directory: int | None,
    name: str,
    relative_path: str,
    expected: Snapshot,
    normalized_mode: int,
    epoch: int,
    architecture: str,
) -> tuple[str, tuple[int, int, int] | None]:
    source_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        source = os.open(name, source_flags, dir_fd=source_directory)
    except OSError as error:
        raise PackagingError(
            f"cannot safely open staged file {relative_path}: {error}"
        ) from error
    destination: int | None = None
    try:
        before = os.fstat(source)
        if Snapshot.from_stat(before) != expected or not stat.S_ISREG(before.st_mode):
            raise PackagingError(
                f"staged file changed before snapshot: {relative_path}"
            )
        _reject_privileged_mode(before, relative_path)
        _reject_sparse_file(before, relative_path)
        _reject_xattrs_fd(source, relative_path)
        if before.st_nlink != 1:
            raise PackagingError(
                f"hardlinked staged files are forbidden: {relative_path}"
            )
        if before.st_size > MAX_FILE_BYTES:
            raise PackagingError(
                f"staged file exceeds the per-file policy limit: {relative_path}"
            )
        if destination_directory is not None:
            destination_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            destination = os.open(
                name, destination_flags, 0o600, dir_fd=destination_directory
            )
        digest = hashlib.sha256()
        header = bytearray()
        total = 0
        while data := os.read(source, READ_SIZE):
            total += len(data)
            if total > before.st_size or total > MAX_FILE_BYTES:
                raise PackagingError(f"staged file grew while copying: {relative_path}")
            if len(header) < 64:
                header.extend(data[: 64 - len(header)])
            digest.update(data)
            if destination is not None:
                _write_all(destination, data)
        after = os.fstat(source)
        if Snapshot.from_stat(after) != expected or total != before.st_size:
            raise PackagingError(
                f"staged file changed during snapshot: {relative_path}"
            )
        identity = _elf_identity(bytes(header), relative_path)
        if identity is not None:
            _validate_elf_identity(identity, relative_path, architecture)
        if destination is not None:
            snapshot_mode = 0o555 if normalized_mode == 0o755 else 0o444
            os.fchmod(destination, snapshot_mode)
            os.utime(destination, ns=(epoch * 1_000_000_000,) * 2)
            os.fsync(destination)
        return digest.hexdigest(), identity
    finally:
        if destination is not None:
            os.close(destination)
        os.close(source)


def _scan_source_tree(
    source_root: int,
    destination_root: int | None,
    epoch: int,
    architecture: str,
) -> SourceScan:
    root_before = os.fstat(source_root)
    if not stat.S_ISDIR(root_before.st_mode):
        raise PackagingError("installed prefix descriptor is not a directory")
    _reject_privileged_mode(root_before, "")
    _reject_xattrs_fd(source_root, "")
    root_snapshot = Snapshot.from_stat(root_before)
    pending: list[tuple[int, int | None, str]] = [
        (
            os.dup(source_root),
            os.dup(destination_root) if destination_root is not None else None,
            "",
        )
    ]
    records: list[SourceRecord] = []
    total_file_bytes = 0
    manifest_size_budget = 16 * 1024
    try:
        while pending:
            source_directory, destination_directory, parent_relative = pending.pop()
            try:
                directory_before = Snapshot.from_stat(os.fstat(source_directory))
                _reject_privileged_mode(os.fstat(source_directory), parent_relative)
                _reject_xattrs_fd(source_directory, parent_relative)
                names_before = _sorted_directory_names(
                    source_directory, parent_relative
                )
                for name in names_before:
                    relative_path = (
                        f"{parent_relative}/{name}" if parent_relative else name
                    )
                    _validate_relative_path(relative_path)
                    try:
                        metadata = os.stat(
                            name, dir_fd=source_directory, follow_symlinks=False
                        )
                    except OSError as error:
                        raise PackagingError(
                            f"cannot inspect staged entry {relative_path}: {error}"
                        ) from error
                    snapshot = Snapshot.from_stat(metadata)
                    if stat.S_ISDIR(metadata.st_mode):
                        _reject_privileged_mode(metadata, relative_path)
                        child_flags = (
                            os.O_RDONLY
                            | getattr(os, "O_CLOEXEC", 0)
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0)
                        )
                        child_source = os.open(
                            name, child_flags, dir_fd=source_directory
                        )
                        child_destination: int | None = None
                        try:
                            if Snapshot.from_stat(os.fstat(child_source)) != snapshot:
                                raise PackagingError(
                                    f"staged directory changed before snapshot: {relative_path}"
                                )
                            if destination_directory is not None:
                                os.mkdir(name, 0o700, dir_fd=destination_directory)
                                child_destination = os.open(
                                    name, child_flags, dir_fd=destination_directory
                                )
                            pending.append(
                                (child_source, child_destination, relative_path)
                            )
                            child_source = -1
                            child_destination = None
                        finally:
                            if child_destination is not None:
                                os.close(child_destination)
                            if child_source >= 0:
                                os.close(child_source)
                        records.append(
                            SourceRecord(
                                relative_path,
                                "directory",
                                0o755,
                                0,
                                None,
                                None,
                                snapshot,
                                None,
                            )
                        )
                    elif stat.S_ISREG(metadata.st_mode):
                        normalized_mode = _normalized_mode(metadata, "file")
                        digest, identity = _copy_and_hash_regular_file(
                            source_directory,
                            destination_directory,
                            name,
                            relative_path,
                            snapshot,
                            normalized_mode,
                            epoch,
                            architecture,
                        )
                        total_file_bytes += metadata.st_size
                        if total_file_bytes > MAX_TOTAL_FILE_BYTES:
                            raise PackagingError(
                                "staged tree exceeds the total file-size policy limit"
                            )
                        records.append(
                            SourceRecord(
                                relative_path,
                                "file",
                                normalized_mode,
                                metadata.st_size,
                                digest,
                                None,
                                snapshot,
                                identity,
                            )
                        )
                    elif stat.S_ISLNK(metadata.st_mode):
                        if metadata.st_nlink != 1:
                            raise PackagingError(
                                f"hardlinked staged symlinks are forbidden: {relative_path}"
                            )
                        _reject_symlink_xattrs(source_directory, name, relative_path)
                        try:
                            target = os.readlink(name, dir_fd=source_directory)
                        except OSError as error:
                            raise PackagingError(
                                f"cannot read staged symlink {relative_path}: {error}"
                            ) from error
                        _validate_symlink(relative_path, target)
                        if (
                            Snapshot.from_stat(
                                os.stat(
                                    name, dir_fd=source_directory, follow_symlinks=False
                                )
                            )
                            != snapshot
                        ):
                            raise PackagingError(
                                f"staged symlink changed during snapshot: {relative_path}"
                            )
                        if destination_directory is not None:
                            os.symlink(target, name, dir_fd=destination_directory)
                            os.utime(
                                name,
                                ns=(epoch * 1_000_000_000,) * 2,
                                dir_fd=destination_directory,
                                follow_symlinks=False,
                            )
                        records.append(
                            SourceRecord(
                                relative_path,
                                "symlink",
                                0o777,
                                0,
                                None,
                                target,
                                snapshot,
                                None,
                            )
                        )
                    else:
                        raise PackagingError(
                            f"special files are forbidden in the package: {relative_path} "
                            f"(mode {stat.filemode(metadata.st_mode)})"
                        )
                    if len(records) > MAX_ENTRIES:
                        raise PackagingError(
                            "staged tree exceeds the entry-count policy limit"
                        )
                    manifest_size_budget += (
                        len(
                            json.dumps(
                                records[-1].manifest_record(),
                                ensure_ascii=False,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                        )
                        + 1
                    )
                    if manifest_size_budget > MAX_MANIFEST_BYTES:
                        raise PackagingError(
                            "staged tree exceeds the manifest-size policy limit"
                        )
                names_after = _sorted_directory_names(source_directory, parent_relative)
                if names_after != names_before:
                    raise PackagingError(
                        f"staged directory membership changed during snapshot: "
                        f"{parent_relative or '.'}"
                    )
                if Snapshot.from_stat(os.fstat(source_directory)) != directory_before:
                    raise PackagingError(
                        f"staged directory metadata changed during snapshot: "
                        f"{parent_relative or '.'}"
                    )
                if destination_directory is not None:
                    os.fchmod(destination_directory, 0o555)
                    os.utime(destination_directory, ns=(epoch * 1_000_000_000,) * 2)
                    os.fsync(destination_directory)
            finally:
                if destination_directory is not None:
                    os.close(destination_directory)
                os.close(source_directory)
    finally:
        for source_directory, destination_directory, _ in pending:
            if destination_directory is not None:
                os.close(destination_directory)
            os.close(source_directory)
    root_after = Snapshot.from_stat(os.fstat(source_root))
    if root_after != root_snapshot:
        raise PackagingError("installed prefix root changed during snapshot")
    records.sort(key=lambda record: record.relative_path.encode("utf-8"))
    _validate_symlink_graph(
        [(record.relative_path, record.kind, record.link_target) for record in records]
    )
    return SourceScan(root_snapshot, tuple(records))


def _create_private_snapshot(
    source_descriptor: int,
    private_descriptor: int,
    epoch: int,
    architecture: str,
    version: str,
    test_only_bypass_product_identity: bool,
) -> tuple[Path, str, SourceScan]:
    os.mkdir("snapshot", 0o700, dir_fd=private_descriptor)
    snapshot_descriptor = _open_prefix_at(
        private_descriptor, PurePosixPath("/snapshot")
    )
    try:
        copied = _scan_source_tree(
            source_descriptor, snapshot_descriptor, epoch, architecture
        )
        if not copied.records:
            raise PackagingError("installed prefix is empty")
        audited = _scan_source_tree(source_descriptor, None, epoch, architecture)
        if copied != audited:
            raise PackagingError(
                "installed prefix changed between private snapshot and source audit"
            )
        identity_status = _product_identity_status(
            version, test_only_bypass_product_identity
        )
        os.fsync(snapshot_descriptor)
    finally:
        os.close(snapshot_descriptor)
    return _descriptor_path(private_descriptor, "snapshot"), identity_status, copied


def _snapshot_matches(path: Path, snapshot: Snapshot) -> bool:
    try:
        current = Snapshot.from_stat(path.lstat())
    except OSError:
        return False
    return current == snapshot


def _open_regular_file(entry: Entry) -> tuple[BinaryIO, os.stat_result]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(entry.source_path, flags)
    except OSError as error:
        raise PackagingError(
            f"cannot safely open staged file {entry.relative_path}: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if Snapshot.from_stat(metadata) != entry.snapshot or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise PackagingError(
                f"staged file changed while packaging: {entry.relative_path}"
            )
        return os.fdopen(descriptor, "rb", closefd=True), metadata
    except Exception:
        os.close(descriptor)
        raise


def _hash_regular_file(path: Path, relative_path: str, snapshot: Snapshot) -> str:
    provisional = Entry(
        relative_path=relative_path,
        source_path=path,
        kind="file",
        mode=0,
        size=snapshot.size,
        sha256=None,
        link_target=None,
        snapshot=snapshot,
    )
    digest = hashlib.sha256()
    with _open_regular_file(provisional)[0] as stream:
        while data := stream.read(READ_SIZE):
            digest.update(data)
        if Snapshot.from_stat(os.fstat(stream.fileno())) != snapshot:
            raise PackagingError(f"staged file changed while hashing: {relative_path}")
    return digest.hexdigest()


def _scan_tree(root: Path) -> list[Entry]:
    entries: list[Entry] = []
    pending: list[tuple[Path, str]] = [(root, "")]
    while pending:
        directory, parent_relative = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(
                    iterator,
                    key=lambda item: item.name.encode("utf-8", errors="strict"),
                )
        except (OSError, UnicodeError) as error:
            raise PackagingError(
                f"cannot scan staged directory {directory}: {error}"
            ) from error
        for child in children:
            _validate_text(child.name, f"filename under {parent_relative or '.'}")
            relative_path = (
                f"{parent_relative}/{child.name}" if parent_relative else child.name
            )
            _validate_relative_path(relative_path)
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as error:
                raise PackagingError(
                    f"cannot inspect staged entry {relative_path}: {error}"
                ) from error
            snapshot = Snapshot.from_stat(metadata)
            source_path = directory / child.name
            if stat.S_ISDIR(metadata.st_mode):
                entries.append(
                    Entry(
                        relative_path,
                        source_path,
                        "directory",
                        _normalized_mode(metadata, "directory"),
                        0,
                        None,
                        None,
                        snapshot,
                    )
                )
                pending.append((source_path, relative_path))
            elif stat.S_ISREG(metadata.st_mode):
                digest = _hash_regular_file(source_path, relative_path, snapshot)
                entries.append(
                    Entry(
                        relative_path,
                        source_path,
                        "file",
                        _normalized_mode(metadata, "file"),
                        metadata.st_size,
                        digest,
                        None,
                        snapshot,
                    )
                )
            elif stat.S_ISLNK(metadata.st_mode):
                try:
                    target = os.readlink(source_path)
                except OSError as error:
                    raise PackagingError(
                        f"cannot read staged symlink {relative_path}: {error}"
                    ) from error
                _validate_symlink(relative_path, target)
                if not _snapshot_matches(source_path, snapshot):
                    raise PackagingError(
                        f"staged symlink changed while scanning: {relative_path}"
                    )
                entries.append(
                    Entry(
                        relative_path,
                        source_path,
                        "symlink",
                        _normalized_mode(metadata, "symlink"),
                        0,
                        None,
                        target,
                        snapshot,
                    )
                )
            else:
                raise PackagingError(
                    f"special files are forbidden in the package: {relative_path} "
                    f"(mode {stat.filemode(metadata.st_mode)})"
                )

    if not entries:
        raise PackagingError("installed prefix is empty")
    entries.sort(key=lambda entry: entry.relative_path.encode("utf-8"))
    _validate_symlink_graph(
        [(entry.relative_path, entry.kind, entry.link_target) for entry in entries]
    )
    return entries


def _validate_payload_elf(entries: Sequence[Entry], architecture: str) -> None:
    for entry in entries:
        if entry.kind != "file":
            continue
        try:
            with entry.source_path.open("rb") as stream:
                header = stream.read(64)
                identity = _elf_identity(header, entry.relative_path)
        except OSError as error:
            raise PackagingError(
                f"cannot inspect ELF identity for {entry.relative_path}: {error}"
            ) from error
        if identity is None:
            continue
        _validate_elf_identity(identity, entry.relative_path, architecture)


def _tar_info(name: str, kind: str, mode: int, epoch: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mode = mode
    info.mtime = epoch
    info.pax_headers = {}
    if kind == "directory":
        info.type = tarfile.DIRTYPE
        info.size = 0
    elif kind == "file":
        info.type = tarfile.REGTYPE
    elif kind == "symlink":
        info.type = tarfile.SYMTYPE
        info.size = 0
    else:
        raise AssertionError(f"unrecognized entry kind: {kind}")
    return info


def _write_tar(
    tar_path: Path, archive_root: str, entries: Sequence[Entry], epoch: int
) -> None:
    with tarfile.open(
        tar_path, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8"
    ) as archive:
        archive.addfile(_tar_info(archive_root, "directory", 0o755, epoch))
        for entry in entries:
            if not _snapshot_matches(entry.source_path, entry.snapshot):
                raise PackagingError(
                    f"staged entry changed while packaging: {entry.relative_path}"
                )
            archive_name = f"{archive_root}/{entry.relative_path}"
            info = _tar_info(archive_name, entry.kind, entry.mode, epoch)
            if entry.kind == "directory":
                archive.addfile(info)
            elif entry.kind == "symlink":
                info.linkname = entry.link_target or ""
                archive.addfile(info)
            else:
                info.size = entry.size
                stream, _ = _open_regular_file(entry)
                with stream:
                    reader = DigestingReader(stream)
                    archive.addfile(info, reader)
                    final_snapshot = Snapshot.from_stat(os.fstat(stream.fileno()))
                    if final_snapshot != entry.snapshot:
                        raise PackagingError(
                            f"staged file changed while writing archive: {entry.relative_path}"
                        )
                    if (
                        reader.bytes_read != entry.size
                        or reader.hexdigest != entry.sha256
                    ):
                        raise PackagingError(
                            "staged file content changed while writing archive: "
                            f"{entry.relative_path}"
                        )


def _find_zstd(zstd_value: str | None) -> Path:
    candidate = zstd_value or shutil.which("zstd")
    if not candidate:
        raise PackagingError("zstd was not found on PATH; no dependency was downloaded")
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        located = shutil.which(candidate)
        if not located:
            raise PackagingError(f"zstd executable was not found: {candidate}")
        candidate_path = Path(located)
    try:
        resolved = candidate_path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise PackagingError(
            f"cannot inspect zstd executable {candidate_path}: {error}"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise PackagingError(f"zstd is not an executable regular file: {resolved}")
    return resolved


def _run_zstd_bounded(
    arguments: Sequence[str],
    source: BinaryIO,
    output: BinaryIO,
    maximum_size: int,
    limit_error: str,
) -> None:
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                arguments,
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=errors,
            )
        except OSError as error:
            raise PackagingError(f"could not execute zstd: {error}") from error
        assert process.stdout is not None
        size = 0
        try:
            while data := process.stdout.read(READ_SIZE):
                size += len(data)
                if size > maximum_size:
                    raise PackagingError(limit_error)
                written = output.write(data)
                if written != len(data):
                    raise PackagingError("short write while capturing zstd output")
        except Exception:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        finally:
            process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            errors.seek(0)
            detail = errors.read()[-4000:].decode("utf-8", errors="replace").strip()
            raise PackagingError(f"zstd failed with exit code {return_code}: {detail}")


def _compress(tar_path: Path, archive_path: Path, zstd: Path) -> None:
    with tar_path.open("rb") as source, archive_path.open("wb") as output:
        _run_zstd_bounded(
            [
                str(zstd),
                "--compress",
                "--stdout",
                "--quiet",
                "--threads=1",
                f"-M{ZSTD_MEMORY_MIB}MB",
                "--no-sparse",
                "-19",
            ],
            source,
            output,
            MAX_ARCHIVE_BYTES,
            "compressed archive exceeds the absolute policy limit",
        )
        output.flush()
        os.fsync(output.fileno())


def _decompress(
    archive_path: Path, tar_path: Path, zstd: Path, maximum_size: int
) -> None:
    arguments = [
        str(zstd),
        "--decompress",
        "--stdout",
        "--quiet",
        f"-M{ZSTD_MEMORY_MIB}MB",
        "--no-sparse",
    ]
    with archive_path.open("rb") as source, tar_path.open("wb") as output:
        _run_zstd_bounded(
            arguments,
            source,
            output,
            maximum_size,
            "decompressed tar exceeds the manifest-derived size limit",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(READ_SIZE):
            digest.update(data)
    return digest.hexdigest()


def _manifest_bytes(
    artifact_name: str,
    manifest_name: str,
    checksum_name: str,
    archive_root: str,
    version: str,
    architecture: str,
    prefix: str,
    epoch: int,
    entries: Sequence[Entry],
    archive_sha256: str,
    product_identity: str,
) -> bytes:
    for entry in entries:
        member_name = f"{archive_root}/{entry.relative_path}"
        if len(member_name.encode("utf-8")) > MAX_PATH_BYTES:
            raise PackagingError(
                f"archive member path exceeds the policy limit: {entry.relative_path}"
            )
    manifest = {
        "architecture": architecture,
        "archive_root": archive_root,
        "archive_sha256": archive_sha256,
        "artifact": artifact_name,
        "checksum": checksum_name,
        "product_identity": product_identity,
        "entries": [entry.manifest_record() for entry in entries],
        "format_version": FORMAT_VERSION,
        "install_prefix": prefix,
        "manifest": manifest_name,
        "normalization": {
            "directory_mode": 0o755,
            "executable_mode": 0o755,
            "file_mode": 0o644,
            "gid": 0,
            "gname": "root",
            "mtime": epoch,
            "symlink_mode": 0o777,
            "uid": 0,
            "uname": "root",
        },
        "policy": {"limits": POLICY_LIMITS, "version": POLICY_VERSION},
        "source_date_epoch": epoch,
        "version": version,
    }
    return (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse_manifest(
    manifest_bytes: bytes, *, allow_test_identity_bypass: bool = False
) -> dict[str, object]:
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise PackagingError("manifest exceeds the absolute policy limit")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackagingError(
            f"manifest is not canonical UTF-8 JSON: {error}"
        ) from error
    if not isinstance(manifest, dict):
        raise PackagingError("manifest root must be an object")
    required_keys = {
        "architecture",
        "archive_root",
        "archive_sha256",
        "artifact",
        "checksum",
        "entries",
        "format_version",
        "install_prefix",
        "manifest",
        "normalization",
        "policy",
        "product_identity",
        "source_date_epoch",
        "version",
    }
    if set(manifest) != required_keys:
        raise PackagingError("manifest fields do not match the supported format")
    if (
        type(manifest["format_version"]) is not int
        or manifest["format_version"] != FORMAT_VERSION
    ):
        raise PackagingError("manifest format version is unsupported")
    product_identity = manifest["product_identity"]
    if product_identity != "test-only-bypass":
        raise PackagingError(
            "manifest product identity is unsupported until the production contract exists"
        )
    if not allow_test_identity_bypass:
        raise PackagingError(
            "test-only product identity bypass is not accepted without the explicit test "
            "API flag"
        )
    architecture = manifest["architecture"]
    if not isinstance(architecture, str):
        raise PackagingError("manifest architecture must be a string")
    _validate_architecture(architecture)
    version = manifest["version"]
    if not isinstance(version, str):
        raise PackagingError("manifest version must be a string")
    _validate_version(version)
    match = SEMVER_RE.fullmatch(version)
    assert match is not None
    prerelease = match.group("prerelease") or ""
    if "test" not in prerelease.split("."):
        raise PackagingError(
            "product identity bypass is restricted to test-version fixtures"
        )
    prefix = manifest["install_prefix"]
    if not isinstance(prefix, str):
        raise PackagingError("manifest install prefix must be a string")
    _validate_prefix(prefix)
    artifact_name = f"openfusion-{version}-linux-{architecture}.tar.zst"
    manifest_name = f"{artifact_name}.manifest.json"
    checksum_name = f"{artifact_name}.sha256"
    archive_root = f"openfusion-{version}-linux-{architecture}"
    if (
        manifest["artifact"] != artifact_name
        or manifest["manifest"] != manifest_name
        or manifest["checksum"] != checksum_name
        or manifest["archive_root"] != archive_root
    ):
        raise PackagingError("manifest artifact identity is inconsistent")
    policy = manifest["policy"]
    if not isinstance(policy, dict) or set(policy) != {"limits", "version"}:
        raise PackagingError("manifest packaging policy has invalid fields")
    limits = policy["limits"]
    if not isinstance(limits, dict) or set(limits) != set(POLICY_LIMITS):
        raise PackagingError("manifest packaging limits have invalid fields")
    if type(policy["version"]) is not int or policy["version"] != POLICY_VERSION:
        raise PackagingError("manifest packaging policy version is unsupported")
    if any(
        type(limits[name]) is not int or limits[name] != expected
        for name, expected in POLICY_LIMITS.items()
    ):
        raise PackagingError(
            "manifest packaging policy is unsupported or has altered limits"
        )
    digest = manifest["archive_sha256"]
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise PackagingError("manifest archive SHA-256 is invalid")
    epoch = manifest["source_date_epoch"]
    if (
        not isinstance(epoch, int)
        or isinstance(epoch, bool)
        or epoch < 0
        or epoch > MAX_SOURCE_DATE_EPOCH
    ):
        raise PackagingError("manifest SOURCE_DATE_EPOCH is invalid")
    expected_normalization = {
        "directory_mode": 0o755,
        "executable_mode": 0o755,
        "file_mode": 0o644,
        "gid": 0,
        "gname": "root",
        "mtime": epoch,
        "symlink_mode": 0o777,
        "uid": 0,
        "uname": "root",
    }
    normalization = manifest["normalization"]
    if not isinstance(normalization, dict) or set(normalization) != set(
        expected_normalization
    ):
        raise PackagingError("manifest normalization fields are invalid")
    numeric_normalization = {
        "directory_mode",
        "executable_mode",
        "file_mode",
        "gid",
        "mtime",
        "symlink_mode",
        "uid",
    }
    if any(type(normalization[name]) is not int for name in numeric_normalization):
        raise PackagingError("manifest normalization numeric fields are invalid")
    if any(type(normalization[name]) is not str for name in {"gname", "uname"}):
        raise PackagingError("manifest normalization owner names are invalid")
    if normalization != expected_normalization:
        raise PackagingError("manifest normalization policy is inconsistent")
    records = manifest["entries"]
    if not isinstance(records, list) or not records:
        raise PackagingError("manifest entries must be a non-empty list")
    if len(records) > MAX_ENTRIES:
        raise PackagingError("manifest exceeds the entry-count policy limit")
    previous_path: str | None = None
    known_types: dict[str, object] = {}
    total_file_bytes = 0
    for record in records:
        if not isinstance(record, dict):
            raise PackagingError("manifest entry must be an object")
        kind = record.get("type")
        if not isinstance(kind, str):
            raise PackagingError("manifest entry type must be a string")
        expected_fields = {
            "directory": {"mode", "path", "type"},
            "file": {"mode", "path", "sha256", "size", "type"},
            "symlink": {"mode", "path", "target", "type"},
        }.get(kind)
        if expected_fields is None or set(record) != expected_fields:
            raise PackagingError("manifest entry fields are invalid")
        relative_path = record["path"]
        if not isinstance(relative_path, str):
            raise PackagingError("manifest entry path must be a string")
        _validate_relative_path(relative_path)
        if len(f"{archive_root}/{relative_path}".encode("utf-8")) > MAX_PATH_BYTES:
            raise PackagingError(
                f"archive member path exceeds the policy limit: {relative_path}"
            )
        if previous_path is not None and relative_path.encode(
            "utf-8"
        ) <= previous_path.encode("utf-8"):
            raise PackagingError(
                "manifest entries are not in strict bytewise path order"
            )
        previous_path = relative_path
        parent = str(PurePosixPath(relative_path).parent)
        if parent != "." and known_types.get(parent) != "directory":
            raise PackagingError(
                f"manifest entry parent is not a directory: {relative_path}"
            )
        known_types[relative_path] = kind
        expected_mode = {"directory": 0o755, "symlink": 0o777}.get(kind)
        mode = record["mode"]
        if not isinstance(mode, int) or isinstance(mode, bool):
            raise PackagingError(f"manifest mode is invalid for {relative_path}")
        if kind == "file":
            if mode not in {0o644, 0o755}:
                raise PackagingError(
                    f"manifest file mode is invalid for {relative_path}"
                )
            size = record["size"]
            file_digest = record["sha256"]
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise PackagingError(f"manifest size is invalid for {relative_path}")
            if size > MAX_FILE_BYTES:
                raise PackagingError(
                    f"manifest file exceeds the policy limit: {relative_path}"
                )
            total_file_bytes += size
            if total_file_bytes > MAX_TOTAL_FILE_BYTES:
                raise PackagingError(
                    "manifest exceeds the total file-size policy limit"
                )
            if (
                not isinstance(file_digest, str)
                or SHA256_RE.fullmatch(file_digest) is None
            ):
                raise PackagingError(f"manifest SHA-256 is invalid for {relative_path}")
        elif mode != expected_mode:
            raise PackagingError(f"manifest mode is invalid for {relative_path}")
        if kind == "symlink":
            target = record["target"]
            if not isinstance(target, str):
                raise PackagingError(
                    f"manifest symlink target is invalid for {relative_path}"
                )
            _validate_symlink(relative_path, target)
    _validate_symlink_graph(
        [
            (
                str(record["path"]),
                str(record["type"]),
                str(record["target"]) if record["type"] == "symlink" else None,
            )
            for record in records
        ]
    )
    canonical_json = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    canonical = f"{canonical_json}\n".encode("utf-8")
    if canonical != manifest_bytes:
        raise PackagingError("manifest JSON is not in canonical form")
    return manifest


def _expected_members(
    manifest: dict[str, object],
) -> Iterator[tuple[str, dict[str, object] | None]]:
    archive_root = manifest["archive_root"]
    assert isinstance(archive_root, str)
    records = manifest["entries"]
    assert isinstance(records, list)
    yield archive_root, None
    for value in records:
        assert isinstance(value, dict)
        yield f"{archive_root}/{value['path']}", value


def _stream_tar_members(archive: tarfile.TarFile) -> Iterator[tarfile.TarInfo]:
    """Yield sequential members without retaining tarfile's member cache."""

    while True:
        member = archive.next()
        if member is None:
            archive.members.clear()
            return
        try:
            yield member
        finally:
            archive.members.clear()


def _verify_member_metadata(
    member: tarfile.TarInfo,
    expected_name: str,
    record: dict[str, object] | None,
    epoch: int,
) -> None:
    if member.name != expected_name:
        raise PackagingError(
            f"archive member order/path mismatch: {member.name!r} != {expected_name!r}"
        )
    if (
        member.uid != 0
        or member.gid != 0
        or member.uname != "root"
        or member.gname != "root"
    ):
        raise PackagingError(
            f"archive ownership metadata is not normalized: {member.name}"
        )
    if member.mtime != epoch:
        raise PackagingError(f"archive mtime is not normalized: {member.name}")
    if set(member.pax_headers) - {"path", "linkpath"}:
        raise PackagingError(f"archive contains unexpected PAX metadata: {member.name}")
    if member.sparse is not None or member.type == tarfile.GNUTYPE_SPARSE:
        raise PackagingError(f"sparse tar members are forbidden: {member.name}")
    if record is None:
        kind = "directory"
        mode = 0o755
    else:
        kind = str(record["type"])
        mode = int(record["mode"])
    member_kind = (
        "directory"
        if member.isdir()
        else "file" if member.isreg() else "symlink" if member.issym() else "special"
    )
    if member_kind != kind:
        raise PackagingError(f"archive member type mismatch: {member.name}")
    if member.mode != mode:
        raise PackagingError(f"archive member mode mismatch: {member.name}")
    if kind == "file":
        assert record is not None
        if member.size != record["size"]:
            raise PackagingError(f"archive member size mismatch: {member.name}")
    elif member.size != 0:
        raise PackagingError(f"non-file archive member has content: {member.name}")
    if kind == "symlink":
        assert record is not None
        if member.linkname != record["target"]:
            raise PackagingError(f"archive symlink target mismatch: {member.name}")


def _preflight_tar_structure(tar_path: Path) -> None:
    file_size = tar_path.stat().st_size
    header_count = 0
    zero_blocks = 0
    with tar_path.open("rb") as stream:
        while stream.tell() < file_size:
            block = stream.read(tarfile.BLOCKSIZE)
            if len(block) != tarfile.BLOCKSIZE:
                raise PackagingError("tar ends with a partial header block")
            if block == b"\0" * tarfile.BLOCKSIZE:
                zero_blocks += 1
                if zero_blocks >= 2:
                    while remainder := stream.read(READ_SIZE):
                        if remainder.strip(b"\0"):
                            raise PackagingError(
                                "tar has nonzero data after its end marker"
                            )
                    return
                continue
            if zero_blocks:
                raise PackagingError("tar has a nonzero header after an end marker")
            header_count += 1
            if header_count > (MAX_ENTRIES + 1) * 2 + 2:
                raise PackagingError("tar exceeds the physical-header policy limit")
            try:
                member_size = tarfile.nti(block[124:136])
            except (tarfile.InvalidHeaderError, ValueError) as error:
                raise PackagingError(
                    f"tar has an invalid size field: {error}"
                ) from error
            if member_size is None or member_size < 0:
                raise PackagingError("tar has a negative or missing member size")
            member_type = block[156:157]
            if member_type == tarfile.XHDTYPE:
                if member_size > MAX_PAX_HEADER_BYTES:
                    raise PackagingError("PAX extended header exceeds the policy limit")
            elif member_type in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                if member_size > MAX_FILE_BYTES:
                    raise PackagingError("tar member exceeds the per-file policy limit")
            elif member_type in {tarfile.DIRTYPE, tarfile.SYMTYPE}:
                if member_size != 0:
                    raise PackagingError("non-file tar header declares payload bytes")
            elif member_type == tarfile.GNUTYPE_SPARSE:
                raise PackagingError("sparse tar members are forbidden")
            else:
                raise PackagingError(
                    f"tar contains a forbidden physical header type: {member_type!r}"
                )
            padded_size = (member_size + tarfile.BLOCKSIZE - 1) & ~(
                tarfile.BLOCKSIZE - 1
            )
            next_offset = stream.tell() + padded_size
            if next_offset > file_size:
                raise PackagingError("tar member payload extends beyond the file")
            stream.seek(padded_size, os.SEEK_CUR)
    raise PackagingError("tar is missing its two-block end marker")


def _extract_and_verify_tar(tar_path: Path, manifest: dict[str, object]) -> None:
    if tar_path.stat().st_size > MAX_TAR_BYTES:
        raise PackagingError("decompressed tar exceeds the absolute policy limit")
    _preflight_tar_structure(tar_path)
    expected_members = _expected_members(manifest)
    epoch = int(manifest["source_date_epoch"])
    archive_root = str(manifest["archive_root"])
    with tempfile.TemporaryDirectory(
        prefix="openfusion-tar-verify-"
    ) as extraction_value:
        extraction_root = Path(extraction_value)
        directory_paths: list[Path] = []
        with tarfile.open(tar_path, mode="r:", encoding="utf-8") as archive:
            expected_iterator = iter(expected_members)
            member_count = 0
            for member in _stream_tar_members(archive):
                member_count += 1
                if member_count > MAX_ENTRIES + 1:
                    raise PackagingError(
                        "archive exceeds the member-count policy limit"
                    )
                try:
                    expected_name, record = next(expected_iterator)
                except StopIteration as error:
                    raise PackagingError(
                        "archive contains members absent from the manifest"
                    ) from error
                _verify_member_metadata(member, expected_name, record, epoch)
                output_path = extraction_root.joinpath(
                    *PurePosixPath(member.name).parts
                )
                if not _path_is_within(output_path, extraction_root):
                    raise PackagingError(
                        f"archive member escapes extraction root: {member.name}"
                    )
                if member.isdir():
                    output_path.mkdir(mode=0o700)
                    directory_paths.append(output_path)
                elif member.isreg():
                    assert record is not None
                    source = archive.extractfile(member)
                    if source is None:
                        raise PackagingError(
                            f"archive member content is missing: {member.name}"
                        )
                    digest = hashlib.sha256()
                    with output_path.open("xb") as destination:
                        while data := source.read(READ_SIZE):
                            destination.write(data)
                            digest.update(data)
                    if digest.hexdigest() != record["sha256"]:
                        raise PackagingError(
                            f"archive member digest mismatch: {member.name}"
                        )
                    output_path.chmod(int(record["mode"]))
                    os.utime(output_path, (epoch, epoch))
                elif member.issym():
                    assert record is not None
                    os.symlink(str(record["target"]), output_path)
                    os.utime(output_path, (epoch, epoch), follow_symlinks=False)
            try:
                next(expected_iterator)
            except StopIteration:
                pass
            else:
                raise PackagingError(
                    "archive is missing members declared by the manifest"
                )
        for directory in reversed(directory_paths):
            directory.chmod(0o755)
            os.utime(directory, (epoch, epoch))

        payload_root = extraction_root / archive_root
        extracted_entries = _scan_tree(payload_root)
        extracted_records = [entry.manifest_record() for entry in extracted_entries]
        if extracted_records != manifest["entries"]:
            raise PackagingError("extracted payload does not match manifest")
        root_metadata = payload_root.lstat()
        if (
            stat.S_IMODE(root_metadata.st_mode) != 0o755
            or root_metadata.st_mtime_ns != epoch * 1_000_000_000
        ):
            raise PackagingError("extracted archive root metadata is not normalized")
        _validate_payload_elf(extracted_entries, str(manifest["architecture"]))
        canonical_tar = extraction_root / "canonical.tar"
        _write_tar(canonical_tar, archive_root, extracted_entries, epoch)
        if _sha256_file(canonical_tar) != _sha256_file(tar_path):
            raise PackagingError(
                "decompressed tar is not in canonical deterministic form"
            )


def _verify_archive_data(
    archive_path: Path,
    manifest_bytes: bytes,
    zstd: Path,
    require_artifact_basename: bool,
    allow_test_identity_bypass: bool,
) -> dict[str, object]:
    manifest = _parse_manifest(
        manifest_bytes, allow_test_identity_bypass=allow_test_identity_bypass
    )
    if require_artifact_basename and archive_path.name != manifest["artifact"]:
        raise PackagingError("archive filename does not match its manifest")
    archive_size = archive_path.stat().st_size
    if archive_size > MAX_ARCHIVE_BYTES:
        raise PackagingError("archive exceeds the compressed-size policy limit")
    archive_digest = _sha256_file(archive_path)
    if archive_digest != manifest["archive_sha256"]:
        raise PackagingError("archive SHA-256 does not match its manifest")
    records = manifest["entries"]
    assert isinstance(records, list)
    payload_size = sum(
        int(record["size"])
        for record in records
        if isinstance(record, dict) and record.get("type") == "file"
    )
    manifest_derived_size = payload_size + max(
        16 * 1024 * 1024, (len(records) + 1) * 16 * 1024
    )
    maximum_tar_size = min(MAX_TAR_BYTES, manifest_derived_size)
    with tempfile.NamedTemporaryFile(
        prefix="openfusion-verify-", suffix=".tar", delete=False
    ) as handle:
        tar_path = Path(handle.name)
    try:
        _decompress(archive_path, tar_path, zstd, maximum_tar_size)
        _extract_and_verify_tar(tar_path, manifest)
    finally:
        tar_path.unlink(missing_ok=True)
    return manifest


def _create_private_file(
    private_descriptor: int, name: str, content: bytes, maximum_size: int
) -> Path:
    if len(content) > maximum_size:
        raise PackagingError(f"private output exceeds its policy limit: {name}")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=private_descriptor)
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return _descriptor_path(private_descriptor, name)


def _publish_archive_last(
    private_descriptor: int,
    output_descriptor: int,
    artifact_name: str,
    manifest_name: str,
    checksum_name: str,
) -> None:
    published: list[tuple[str, tuple[int, int]]] = []

    def prepare_and_link(name: str) -> None:
        source = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=private_descriptor,
        )
        try:
            os.fchmod(source, 0o644)
            os.fsync(source)
            source_metadata = os.fstat(source)
        finally:
            os.close(source)
        os.link(
            name,
            name,
            src_dir_fd=private_descriptor,
            dst_dir_fd=output_descriptor,
            follow_symlinks=False,
        )
        published.append((name, (source_metadata.st_dev, source_metadata.st_ino)))

    try:
        prepare_and_link(manifest_name)
        prepare_and_link(checksum_name)
        os.fsync(output_descriptor)
        prepare_and_link(artifact_name)
        os.fsync(output_descriptor)
    except Exception:
        for name, expected_identity in reversed(published):
            try:
                current = os.stat(name, dir_fd=output_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (current.st_dev, current.st_ino) == expected_identity:
                os.unlink(name, dir_fd=output_descriptor)
        try:
            os.fsync(output_descriptor)
        except OSError:
            pass
        raise


def _open_regular_path_once(path_value: str | Path, label: str) -> tuple[Path, int]:
    raw_path = os.fspath(path_value)
    if (
        not os.path.isabs(raw_path)
        or raw_path.startswith("//")
        or raw_path != os.path.normpath(raw_path)
    ):
        raise PackagingError(
            f"{label} path must be normalized and absolute: {raw_path}"
        )
    path = Path(raw_path)
    components = path.parts
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open("/", directory_flags)
    try:
        for component in components[1:-1]:
            next_descriptor = os.open(component, directory_flags, dir_fd=current)
            os.close(current)
            current = next_descriptor
        file_flags = (
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(components[-1], file_flags, dir_fd=current)
    except OSError as error:
        raise PackagingError(f"cannot safely open {label} {path}: {error}") from error
    finally:
        os.close(current)
    try:
        metadata = os.fstat(descriptor)
    except Exception:
        os.close(descriptor)
        raise
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise PackagingError(f"{label} is not a regular file: {path}")
    return path, descriptor


def _copy_open_file_bounded(
    source_descriptor: int,
    destination: Path,
    label: str,
    maximum_size: int,
) -> None:
    before = os.fstat(source_descriptor)
    if before.st_size > maximum_size:
        raise PackagingError(f"{label} exceeds the absolute policy limit")
    _reject_sparse_file(before, label)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    destination_descriptor = os.open(destination, flags, 0o600)
    total = 0
    try:
        try:
            while data := os.read(source_descriptor, READ_SIZE):
                total += len(data)
                if total > maximum_size or total > before.st_size:
                    raise PackagingError(
                        f"{label} changed or exceeded its limit while copying"
                    )
                _write_all(destination_descriptor, data)
            os.fsync(destination_descriptor)
        finally:
            os.close(destination_descriptor)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    after = os.fstat(source_descriptor)
    if (
        Snapshot.from_stat(after) != Snapshot.from_stat(before)
        or total != before.st_size
    ):
        destination.unlink(missing_ok=True)
        raise PackagingError(f"{label} changed while being copied for verification")


def _source_date_epoch() -> int:
    value = os.environ.get("SOURCE_DATE_EPOCH")
    if value is None:
        raise PackagingError("SOURCE_DATE_EPOCH must be set")
    if not value.isascii() or not value.isdecimal():
        raise PackagingError("SOURCE_DATE_EPOCH must contain only decimal digits")
    epoch = int(value)
    if epoch > MAX_SOURCE_DATE_EPOCH:
        raise PackagingError("SOURCE_DATE_EPOCH is outside the supported range")
    return epoch


def build_package(
    destdir_value: str | Path,
    prefix_value: str,
    version_value: str,
    architecture_value: str,
    output_dir_value: str | Path,
    epoch: int,
    zstd_value: str | None = None,
    *,
    staging_is_quiescent: bool = False,
    output_is_exclusive: bool = False,
    _test_only_bypass_product_identity: bool = False,
) -> tuple[Path, Path, Path]:
    """Build, verify, and atomically expose an archive, manifest, and checksum."""

    if not staging_is_quiescent:
        raise PackagingError(
            "the caller must stop installation activity and explicitly confirm a quiescent stage"
        )
    if not output_is_exclusive:
        raise PackagingError(
            "the caller must exclusively control the output directory during publication"
        )
    if (
        not isinstance(epoch, int)
        or isinstance(epoch, bool)
        or epoch < 0
        or epoch > MAX_SOURCE_DATE_EPOCH
    ):
        raise PackagingError("SOURCE_DATE_EPOCH is outside the supported range")
    version = _validate_version(version_value)
    architecture = _validate_architecture(architecture_value)
    prefix = _validate_prefix(prefix_value)
    destdir = _canonical_directory(destdir_value, "DESTDIR")
    output_dir = _canonical_directory(output_dir_value, "output directory")
    source_path = destdir.joinpath(*prefix.parts[1:])
    if _path_is_within(output_dir, source_path):
        raise PackagingError("output directory must not be inside the installed prefix")
    zstd = _find_zstd(zstd_value)

    archive_root = f"openfusion-{version}-linux-{architecture}"
    artifact_name = f"{archive_root}.tar.zst"
    manifest_name = f"{artifact_name}.manifest.json"
    checksum_name = f"{artifact_name}.sha256"
    destdir_descriptor = _open_directory(destdir, "DESTDIR")
    output_descriptor = _open_directory(output_dir, "output directory")
    source_descriptor: int | None = None
    try:
        try:
            fcntl.flock(output_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise PackagingError(
                f"cannot acquire exclusive packaging lock on {output_dir}: {error}"
            ) from error
        source_descriptor = _open_prefix_at(destdir_descriptor, prefix)
        if _directory_descriptor_is_within(output_descriptor, source_descriptor):
            raise PackagingError(
                "output directory must not be inside the installed prefix"
            )
        for final_name in (artifact_name, manifest_name, checksum_name):
            try:
                os.stat(final_name, dir_fd=output_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise PackagingError(
                f"refusing to overwrite existing output: {output_dir / final_name}"
            )
        with _private_output_workspace(output_descriptor) as (_, private_descriptor):
            snapshot_path, product_identity, source_scan = _create_private_snapshot(
                source_descriptor,
                private_descriptor,
                epoch,
                architecture,
                version,
                _test_only_bypass_product_identity,
            )
            entries = _scan_tree(snapshot_path)
            _validate_payload_elf(entries, architecture)

            tar_path = _descriptor_path(private_descriptor, "payload.tar")
            _write_tar(tar_path, archive_root, entries, epoch)
            tar_path.chmod(0o600)
            if tar_path.stat().st_size > MAX_TAR_BYTES:
                raise PackagingError("canonical tar exceeds the absolute policy limit")

            compressed_path = _descriptor_path(private_descriptor, artifact_name)
            _compress(tar_path, compressed_path, zstd)
            compressed_path.chmod(0o600)
            if compressed_path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise PackagingError(
                    "compressed archive exceeds the absolute policy limit"
                )
            archive_digest = _sha256_file(compressed_path)

            manifest_content = _manifest_bytes(
                artifact_name,
                manifest_name,
                checksum_name,
                archive_root,
                version,
                architecture,
                str(prefix),
                epoch,
                entries,
                archive_digest,
                product_identity,
            )
            manifest_path = _create_private_file(
                private_descriptor,
                manifest_name,
                manifest_content,
                MAX_MANIFEST_BYTES,
            )
            manifest_digest = _sha256_file(manifest_path)
            checksum_content = (
                f"{archive_digest}  {artifact_name}\n"
                f"{manifest_digest}  {manifest_name}\n"
            ).encode("ascii")
            _create_private_file(
                private_descriptor,
                checksum_name,
                checksum_content,
                MAX_CHECKSUM_BYTES,
            )

            _verify_archive_data(
                compressed_path,
                manifest_content,
                zstd,
                False,
                _test_only_bypass_product_identity,
            )
            _require_directory_identity(destdir, destdir_descriptor, "DESTDIR")
            _require_directory_identity(
                output_dir, output_descriptor, "output directory"
            )
            reopened_source = _open_prefix_at(destdir_descriptor, prefix)
            try:
                if Snapshot.from_stat(os.fstat(reopened_source)) != Snapshot.from_stat(
                    os.fstat(source_descriptor)
                ):
                    raise PackagingError(
                        "installed prefix root was replaced or changed before publication"
                    )
            finally:
                os.close(reopened_source)
            final_source_scan = _scan_source_tree(
                source_descriptor, None, epoch, architecture
            )
            if final_source_scan != source_scan:
                raise PackagingError(
                    "installed prefix changed after the private snapshot and before publication"
                )
            _publish_archive_last(
                private_descriptor,
                output_descriptor,
                artifact_name,
                manifest_name,
                checksum_name,
            )
        return (
            output_dir / artifact_name,
            output_dir / manifest_name,
            output_dir / checksum_name,
        )
    except FileExistsError as error:
        raise PackagingError(
            f"refusing to overwrite an output created concurrently: {error.filename}"
        ) from error
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        os.close(output_descriptor)
        os.close(destdir_descriptor)


def verify_package(
    archive_value: str | Path,
    manifest_value: str | Path,
    checksum_value: str | Path,
    zstd_value: str | None = None,
    *,
    _test_only_bypass_product_identity: bool = False,
) -> None:
    """Verify names, checksums, tar metadata, safe extraction, and the payload manifest."""

    archive_input = Path(archive_value)
    manifest_input = Path(manifest_value)
    checksum_input = Path(checksum_value)
    expected_manifest_name = f"{archive_input.name}.manifest.json"
    expected_checksum_name = f"{archive_input.name}.sha256"
    if (
        manifest_input.name != expected_manifest_name
        or checksum_input.name != expected_checksum_name
    ):
        raise PackagingError("archive companion basenames are inconsistent")
    if not (archive_input.parent == manifest_input.parent == checksum_input.parent):
        raise PackagingError("archive companions must be supplied from one directory")
    zstd = _find_zstd(zstd_value)
    opened: list[int] = []
    try:
        archive_source_path, archive_source = _open_regular_path_once(
            archive_input, "archive"
        )
        opened.append(archive_source)
        manifest_source_path, manifest_source = _open_regular_path_once(
            manifest_input, "manifest"
        )
        opened.append(manifest_source)
        checksum_source_path, checksum_source = _open_regular_path_once(
            checksum_input, "checksum"
        )
        opened.append(checksum_source)
        with tempfile.TemporaryDirectory(
            prefix="openfusion-package-inputs-"
        ) as private_value:
            private = Path(private_value)
            private.chmod(0o700)
            archive_path = private / archive_source_path.name
            manifest_path = private / manifest_source_path.name
            checksum_path = private / checksum_source_path.name
            _copy_open_file_bounded(
                archive_source,
                archive_path,
                "archive",
                MAX_ARCHIVE_BYTES,
            )
            _copy_open_file_bounded(
                manifest_source,
                manifest_path,
                "manifest",
                MAX_MANIFEST_BYTES,
            )
            _copy_open_file_bounded(
                checksum_source,
                checksum_path,
                "checksum",
                MAX_CHECKSUM_BYTES,
            )
            for descriptor in opened:
                os.close(descriptor)
            opened.clear()

            manifest_bytes = manifest_path.read_bytes()
            manifest = _parse_manifest(
                manifest_bytes,
                allow_test_identity_bypass=_test_only_bypass_product_identity,
            )
            if (
                manifest_path.name != manifest["manifest"]
                or checksum_path.name != manifest["checksum"]
                or archive_path.name != manifest["artifact"]
            ):
                raise PackagingError("manifest companion identities are inconsistent")
            archive_digest = _sha256_file(archive_path)
            if archive_digest != manifest["archive_sha256"]:
                raise PackagingError("archive SHA-256 does not match its manifest")
            manifest_digest = _sha256_file(manifest_path)
            expected_checksum = (
                f"{manifest['archive_sha256']}  {manifest['artifact']}\n"
                f"{manifest_digest}  {manifest['manifest']}\n"
            ).encode("ascii")
            if checksum_path.read_bytes() != expected_checksum:
                raise PackagingError(
                    "checksum file does not match the archive and manifest"
                )
            _verify_archive_data(
                archive_path,
                manifest_bytes,
                zstd,
                True,
                _test_only_bypass_product_identity,
            )
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build and verify a staged tar.zst")
    build.add_argument("--destdir", required=True, help="canonical absolute DESTDIR")
    build.add_argument(
        "--prefix", required=True, help="exact absolute POSIX install prefix"
    )
    build.add_argument("--version", required=True, help="semantic OpenFusion version")
    build.add_argument(
        "--architecture",
        required=True,
        choices=sorted(SUPPORTED_ARCHITECTURES),
        help="trusted target architecture, validated against staged ELF files",
    )
    build.add_argument(
        "--output-dir", required=True, help="canonical absolute output directory"
    )
    build.add_argument(
        "--staging-is-quiescent",
        action="store_true",
        help="confirm that all installation writers have stopped",
    )
    build.add_argument(
        "--output-is-exclusive",
        action="store_true",
        help="confirm exclusive control of the output directory during publication",
    )
    build.add_argument("--zstd", help="zstd executable; defaults to PATH lookup")

    verify = subparsers.add_parser(
        "verify", help="verify a previously built staged tar.zst"
    )
    verify.add_argument(
        "--archive", required=True, help="canonical absolute tar.zst path"
    )
    verify.add_argument(
        "--manifest", required=True, help="canonical absolute manifest path"
    )
    verify.add_argument(
        "--checksum", required=True, help="canonical absolute checksum path"
    )
    verify.add_argument("--zstd", help="zstd executable; defaults to PATH lookup")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        if args.command == "build":
            artifact, manifest, checksum = build_package(
                args.destdir,
                args.prefix,
                args.version,
                args.architecture,
                args.output_dir,
                _source_date_epoch(),
                args.zstd,
                staging_is_quiescent=args.staging_is_quiescent,
                output_is_exclusive=args.output_is_exclusive,
            )
            print(artifact)
            print(manifest)
            print(checksum)
        else:
            verify_package(args.archive, args.manifest, args.checksum, args.zstd)
            print(f"verified: {args.archive}")
    except PackagingError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (
        MemoryError,
        OSError,
        OverflowError,
        tarfile.TarError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"error: packaging operation failed safely: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
