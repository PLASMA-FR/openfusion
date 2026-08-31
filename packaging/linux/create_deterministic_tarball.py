#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create and verify the gated OpenFusion Linux tar.zst staging artifact.

This tool only packages an existing DESTDIR/prefix installation.  It does not
install, rename, patch, or otherwise modify the staged application.
"""

from __future__ import annotations

import argparse
import base64
from collections import deque
import contextlib
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Sequence


FORMAT_VERSION = 4
POLICY_VERSION = 3
IDENTITY_FORMAT_VERSION = 1
BUILD_PROVENANCE_FORMAT_VERSION = 1
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
MAX_IDENTITY_BYTES = 1024 * 1024
MAX_PROVENANCE_BYTES = 1024 * 1024
MAX_OPENSSL_OUTPUT_BYTES = 64 * 1024
IDENTITY_ALGORITHM = "ed25519"
IDENTITY_RELATIVE_PATH = "share/openfusion/executable-identity.json"
PAYLOAD_TREE_DOMAIN = b"OpenFusion Linux payload tree and policy v1\0"
PRODUCTION_IDENTITY_KEY_SHA256_ALLOWLIST: frozenset[str] = frozenset()
CANONICAL_EXECUTABLES = {
    "cli": "bin/OpenFusionCmd",
    "gui": "bin/OpenFusion",
}
COMPATIBILITY_EXECUTABLES = {
    "cli": "bin/FreeCADCmd",
    "gui": "bin/FreeCAD",
}
POLICY_LIMITS = {
    "archive_bytes": MAX_ARCHIVE_BYTES,
    "checksum_bytes": MAX_CHECKSUM_BYTES,
    "entries": MAX_ENTRIES,
    "file_bytes": MAX_FILE_BYTES,
    "identity_bytes": MAX_IDENTITY_BYTES,
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
    "aarch64": {"elf_class": 2, "elf_data": 1, "elf_machine": 183},
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
SOURCE_REVISION_RE = re.compile(r"[0-9a-f]{40}\Z")
READ_SIZE = 1024 * 1024
LEGAL_POLICY_FORMAT_VERSION = 1
LEGAL_POLICY_PATH = Path(__file__).resolve().with_name("legal_quarantine.json")
MAX_LEGAL_POLICY_BYTES = 256 * 1024
MAX_LEGAL_SCAN_FILE_BYTES = 1024 * 1024**2
MAX_LEGAL_LFS_POINTER_BYTES = 1024
LEGAL_SCAN_CHUNK_BYTES = 64 * 1024
LEGAL_TEXT_OVERLAP_BYTES = 512
LEGAL_LFS_POINTER = re.compile(
    rb"version https://git-lfs\.github\.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n?\Z"
)
LEGAL_ARR_METADATA = re.compile(
    rb"(?:^|[^a-z0-9_])[\"']?license[\"']? *[:=] *[\"']?"
    rb"all rights reserved(?:[\"']|[^a-z0-9_])"
)
ORIGIN_RUNPATH_MARKER = b"$ORIGIN/../lib"


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


@dataclass
class TrustedExecutable:
    source_path: Path
    descriptor: int
    snapshot: Snapshot
    sha256: str
    closed: bool = False

    def __fspath__(self) -> str:
        return f"/proc/self/fd/{self.descriptor}"

    def assert_unchanged(self) -> None:
        if Snapshot.from_stat(os.fstat(self.descriptor)) != self.snapshot:
            raise PackagingError(f"trusted executable changed during use: {self.source_path}")

    def close(self) -> None:
        if not self.closed:
            os.close(self.descriptor)
            self.closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass


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


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _read_regular_path_bounded(
    path_value: str | Path, label: str, maximum_size: int
) -> bytes:
    _, descriptor = _open_regular_path_once(path_value, label)
    try:
        before = os.fstat(descriptor)
        if before.st_size > maximum_size:
            raise PackagingError(f"{label} exceeds the absolute policy limit")
        content = bytearray()
        while data := os.read(descriptor, min(READ_SIZE, maximum_size + 1)):
            content.extend(data)
            if len(content) > maximum_size or len(content) > before.st_size:
                raise PackagingError(f"{label} changed or exceeded its limit while reading")
        after = os.fstat(descriptor)
        if Snapshot.from_stat(after) != Snapshot.from_stat(before) or len(content) != before.st_size:
            raise PackagingError(f"{label} changed while being read")
        return bytes(content)
    finally:
        os.close(descriptor)


def _sha256_regular_path_bounded(
    path_value: str | Path, label: str, maximum_size: int
) -> str:
    _, descriptor = _open_regular_path_once(path_value, label)
    try:
        before = os.fstat(descriptor)
        if before.st_size > maximum_size:
            raise PackagingError(f"{label} exceeds the absolute policy limit")
        digest = hashlib.sha256()
        total = 0
        while data := os.read(descriptor, READ_SIZE):
            total += len(data)
            if total > maximum_size or total > before.st_size:
                raise PackagingError(f"{label} changed or exceeded its limit while hashing")
            digest.update(data)
        after = os.fstat(descriptor)
        if Snapshot.from_stat(after) != Snapshot.from_stat(before) or total != before.st_size:
            raise PackagingError(f"{label} changed while being hashed")
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _write_new_regular_path(path_value: str | Path, label: str, content: bytes) -> Path:
    raw_path = os.fspath(path_value)
    if (
        not os.path.isabs(raw_path)
        or raw_path.startswith("//")
        or raw_path != os.path.normpath(raw_path)
    ):
        raise PackagingError(f"{label} path must be normalized and absolute: {raw_path}")
    path = Path(raw_path)
    parent = _canonical_directory(path.parent, f"{label} parent directory")
    if path.parent != parent or path.name in {"", ".", ".."}:
        raise PackagingError(f"{label} path is not canonical: {path}")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as error:
        raise PackagingError(f"refusing to overwrite existing {label}: {path}") from error
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return path


def _find_openssl(openssl_value: str | None) -> TrustedExecutable:
    candidate = openssl_value or shutil.which("openssl")
    if not candidate:
        raise PackagingError("openssl was not found on PATH; no dependency was downloaded")
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        located = shutil.which(candidate)
        if not located:
            raise PackagingError(f"openssl executable was not found: {candidate}")
        candidate_path = Path(located)
    try:
        resolved = candidate_path.resolve(strict=True)
    except OSError as error:
        raise PackagingError(f"cannot inspect openssl executable {candidate_path}: {error}") from error
    _, descriptor = _open_regular_path_once(resolved, "openssl executable")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
            raise PackagingError(f"openssl is not an executable regular file: {resolved}")
        snapshot = Snapshot.from_stat(metadata)
        digest = hashlib.sha256()
        total = 0
        while data := os.read(descriptor, READ_SIZE):
            total += len(data)
            if total > MAX_FILE_BYTES or total > metadata.st_size:
                raise PackagingError("openssl executable changed or exceeded its limit")
            digest.update(data)
        if total != metadata.st_size or Snapshot.from_stat(os.fstat(descriptor)) != snapshot:
            raise PackagingError("openssl executable changed while being authenticated")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return TrustedExecutable(resolved, descriptor, snapshot, digest.hexdigest())
    except Exception:
        os.close(descriptor)
        raise


def _limit_subprocess_file_output() -> None:
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_OPENSSL_OUTPUT_BYTES, MAX_OPENSSL_OUTPUT_BYTES),
    )


def _run_openssl(arguments: Sequence[str | os.PathLike[str]], label: str) -> bytes:
    trusted = [argument for argument in arguments if isinstance(argument, TrustedExecutable)]
    pass_fds = tuple(tool.descriptor for tool in trusted)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                pass_fds=pass_fds,
                preexec_fn=_limit_subprocess_file_output,
            )
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise PackagingError(f"openssl {label} exceeded its time limit") from error
        except OSError as error:
            raise PackagingError(f"openssl {label} failed safely: {error}") from error
        output_size = output.tell()
        error_size = errors.tell()
        if output_size > MAX_OPENSSL_OUTPUT_BYTES or error_size > MAX_OPENSSL_OUTPUT_BYTES:
            raise PackagingError(f"openssl {label} output exceeds the policy limit")
        output.seek(0)
        errors.seek(0)
        stdout = output.read()
        stderr = errors.read()
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise PackagingError(f"openssl {label} failed with exit code {return_code}: {detail}")
        for tool in trusted:
            tool.assert_unchanged()
        return stdout


def _public_key_der(public_key: Path, openssl: Path | TrustedExecutable) -> bytes:
    value = _run_openssl(
        [openssl, "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"],
        "public-key normalization",
    )
    # RFC 8410 SubjectPublicKeyInfo: id-Ed25519 followed by a 32-byte public key.
    if len(value) != 44 or not value.startswith(bytes.fromhex("302a300506032b6570032100")):
        raise PackagingError("trusted identity key is not a canonical Ed25519 public key")
    return value


def _copy_key_to_private_workspace(
    key_value: str | Path, label: str, workspace: Path
) -> Path:
    content = _read_regular_path_bounded(key_value, label, MAX_IDENTITY_BYTES)
    destination = workspace / f"{label.replace(' ', '-')}.pem"
    destination.write_bytes(content)
    destination.chmod(0o600)
    return destination


def _validate_build_provenance(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackagingError("build provenance must be a JSON object")
    required = {
        "build_type",
        "builder",
        "cmake_cache_sha256",
        "compiler",
        "dependency_lock_sha256",
        "format_version",
        "generator",
        "openssl_sha256",
        "openssl_version",
        "source_date_epoch",
        "source_revision",
        "version",
    }
    if set(value) != required:
        raise PackagingError("build provenance fields do not match the supported contract")
    if type(value["format_version"]) is not int or value["format_version"] != BUILD_PROVENANCE_FORMAT_VERSION:
        raise PackagingError("build provenance format version is unsupported")
    for name in ("build_type", "builder", "compiler", "generator", "openssl_version"):
        field = value[name]
        if not isinstance(field, str):
            raise PackagingError(f"build provenance {name} must be a string")
        _validate_text(field, f"build provenance {name}")
        if len(field.encode("utf-8")) > 256:
            raise PackagingError(f"build provenance {name} exceeds the policy limit")
    version = value["version"]
    if not isinstance(version, str):
        raise PackagingError("build provenance version must be a string")
    _validate_version(version)
    revision = value["source_revision"]
    if not isinstance(revision, str) or SOURCE_REVISION_RE.fullmatch(revision) is None:
        raise PackagingError("build provenance source revision must be a full lowercase Git object ID")
    for name in ("cmake_cache_sha256", "dependency_lock_sha256", "openssl_sha256"):
        digest = value[name]
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise PackagingError(f"build provenance {name} is not a lowercase SHA-256")
    epoch = value["source_date_epoch"]
    if type(epoch) is not int or epoch < 0 or epoch > MAX_SOURCE_DATE_EPOCH:
        raise PackagingError("build provenance SOURCE_DATE_EPOCH is invalid")
    return value


def _parse_build_provenance(content: bytes) -> dict[str, object]:
    if len(content) > MAX_PROVENANCE_BYTES:
        raise PackagingError("build provenance exceeds the policy limit")
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackagingError(f"build provenance is not canonical UTF-8 JSON: {error}") from error
    provenance = _validate_build_provenance(value)
    if _canonical_json_bytes(provenance) != content:
        raise PackagingError("build provenance JSON is not in canonical form")
    return provenance


def _validate_identity_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackagingError("executable identity payload must be an object")
    required = {
        "architecture",
        "build_provenance",
        "dependency_lock",
        "executables",
        "format_version",
        "install_prefix",
        "platform",
        "product",
        "payload_tree",
        "release_channel",
        "source_date_epoch",
        "source_revision",
        "version",
    }
    if set(value) != required:
        raise PackagingError("executable identity fields do not match the supported contract")
    if type(value["format_version"]) is not int or value["format_version"] != IDENTITY_FORMAT_VERSION:
        raise PackagingError("executable identity format version is unsupported")
    if value["product"] != "OpenFusion" or value["platform"] != "linux":
        raise PackagingError("executable identity product/platform is not OpenFusion Linux")
    architecture = value["architecture"]
    if not isinstance(architecture, str):
        raise PackagingError("executable identity architecture must be a string")
    _validate_architecture(architecture)
    version = value["version"]
    if not isinstance(version, str):
        raise PackagingError("executable identity version must be a string")
    _validate_version(version)
    prefix = value["install_prefix"]
    if not isinstance(prefix, str):
        raise PackagingError("executable identity install prefix must be a string")
    _validate_prefix(prefix)
    channel = value["release_channel"]
    if channel not in {"development", "production"}:
        raise PackagingError("executable identity release channel is unsupported")
    match = SEMVER_RE.fullmatch(version)
    assert match is not None
    prerelease = (match.group("prerelease") or "").split(".")
    if channel == "development" and "dev" not in prerelease:
        raise PackagingError("development executable identity requires a dev SemVer prerelease")
    if channel == "production" and "dev" in prerelease:
        raise PackagingError("production executable identity cannot use a dev SemVer prerelease")
    revision = value["source_revision"]
    if not isinstance(revision, str) or SOURCE_REVISION_RE.fullmatch(revision) is None:
        raise PackagingError("executable identity source revision is invalid")
    lock = value["dependency_lock"]
    if not isinstance(lock, dict) or set(lock) != {"path", "sha256"}:
        raise PackagingError("executable identity dependency lock fields are invalid")
    if lock["path"] != "pixi.lock" or not isinstance(lock["sha256"], str) or SHA256_RE.fullmatch(lock["sha256"]) is None:
        raise PackagingError("executable identity dependency lock is invalid")
    provenance = _validate_build_provenance(value["build_provenance"])
    epoch = value["source_date_epoch"]
    if type(epoch) is not int or epoch < 0 or epoch > MAX_SOURCE_DATE_EPOCH:
        raise PackagingError("executable identity SOURCE_DATE_EPOCH is invalid")
    if (
        provenance["source_revision"] != revision
        or provenance["dependency_lock_sha256"] != lock["sha256"]
        or provenance["version"] != version
        or provenance["source_date_epoch"] != epoch
    ):
        raise PackagingError("executable identity provenance is inconsistent")
    payload_tree = value["payload_tree"]
    if not isinstance(payload_tree, dict) or set(payload_tree) != {
        "domain",
        "entry_count",
        "policy_sha256",
        "sha256",
        "total_file_bytes",
    }:
        raise PackagingError("executable identity payload-tree fields are invalid")
    if (
        type(payload_tree["entry_count"]) is not int
        or payload_tree["entry_count"] <= 0
        or payload_tree["entry_count"] > MAX_ENTRIES
        or payload_tree["domain"] != PAYLOAD_TREE_DOMAIN[:-1].decode("ascii")
        or not isinstance(payload_tree["policy_sha256"], str)
        or SHA256_RE.fullmatch(payload_tree["policy_sha256"]) is None
        or type(payload_tree["total_file_bytes"]) is not int
        or payload_tree["total_file_bytes"] <= 0
        or payload_tree["total_file_bytes"] > MAX_TOTAL_FILE_BYTES
        or not isinstance(payload_tree["sha256"], str)
        or SHA256_RE.fullmatch(payload_tree["sha256"]) is None
    ):
        raise PackagingError("executable identity payload-tree commitment is invalid")
    executables = value["executables"]
    if not isinstance(executables, dict) or set(executables) != set(CANONICAL_EXECUTABLES):
        raise PackagingError("executable identity roles are invalid")
    for role, expected_path in CANONICAL_EXECUTABLES.items():
        record = executables[role]
        if not isinstance(record, dict) or set(record) != {
            "compatibility_path",
            "path",
            "sha256",
            "size",
        }:
            raise PackagingError(f"executable identity {role} fields are invalid")
        if record["path"] != expected_path:
            raise PackagingError(f"executable identity {role} path is not canonical")
        if record["compatibility_path"] != COMPATIBILITY_EXECUTABLES[role]:
            raise PackagingError(f"executable identity {role} compatibility path is not canonical")
        if not isinstance(record["sha256"], str) or SHA256_RE.fullmatch(record["sha256"]) is None:
            raise PackagingError(f"executable identity {role} SHA-256 is invalid")
        if type(record["size"]) is not int or record["size"] <= 0 or record["size"] > MAX_FILE_BYTES:
            raise PackagingError(f"executable identity {role} size is invalid")
    if executables["gui"]["sha256"] == executables["cli"]["sha256"]:
        raise PackagingError("GUI and CLI executable identities must bind distinct bytes")
    return value


def _identity_envelope_bytes(value: object) -> bytes:
    if not isinstance(value, dict):
        raise PackagingError("signed executable identity must be an object")
    return _canonical_json_bytes(value)


def _sign_identity_payload(
    payload: dict[str, object], signing_key_value: str | Path, openssl: Path
) -> dict[str, object]:
    _validate_identity_payload(payload)
    payload_bytes = _canonical_json_bytes(payload)
    with tempfile.TemporaryDirectory(prefix="openfusion-identity-sign-") as workspace_value:
        workspace = Path(workspace_value)
        workspace.chmod(0o700)
        private_key = _copy_key_to_private_workspace(signing_key_value, "signing key", workspace)
        public_key = workspace / "public.pem"
        _run_openssl(
            [openssl, "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            "public-key derivation",
        )
        public_key.chmod(0o600)
        public_der = _public_key_der(public_key, openssl)
        payload_path = workspace / "payload.json"
        signature_path = workspace / "signature.bin"
        payload_path.write_bytes(payload_bytes)
        _run_openssl(
            [
                openssl,
                "pkeyutl",
                "-sign",
                "-inkey",
                str(private_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-out",
                str(signature_path),
            ],
            "identity signing",
        )
        signature = signature_path.read_bytes()
    if len(signature) != 64:
        raise PackagingError("Ed25519 identity signature has an invalid size")
    return {
        "algorithm": IDENTITY_ALGORITHM,
        "key_sha256": hashlib.sha256(public_der).hexdigest(),
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def _verify_identity_envelope(
    envelope: object,
    trusted_public_key_value: str | Path,
    openssl: Path,
    expected_key_sha256: str,
    expected_release_channel: str,
) -> dict[str, object]:
    if not isinstance(envelope, dict) or set(envelope) != {"algorithm", "key_sha256", "payload", "signature"}:
        raise PackagingError("signed executable identity envelope fields are invalid")
    if envelope["algorithm"] != IDENTITY_ALGORITHM:
        raise PackagingError("signed executable identity algorithm is unsupported")
    payload = _validate_identity_payload(envelope["payload"])
    key_digest = envelope["key_sha256"]
    if not isinstance(key_digest, str) or SHA256_RE.fullmatch(key_digest) is None:
        raise PackagingError("signed executable identity key fingerprint is invalid")
    if SHA256_RE.fullmatch(expected_key_sha256) is None:
        raise PackagingError("expected identity key fingerprint is invalid")
    if expected_release_channel not in {"development", "production"}:
        raise PackagingError("expected identity release channel is invalid")
    if expected_release_channel == "production":
        if not PRODUCTION_IDENTITY_KEY_SHA256_ALLOWLIST:
            raise PackagingError("production identity trust anchor is not configured")
        if expected_key_sha256 not in PRODUCTION_IDENTITY_KEY_SHA256_ALLOWLIST:
            raise PackagingError("expected production identity key is not the configured trust anchor")
    if key_digest != expected_key_sha256:
        raise PackagingError("signed executable identity key fingerprint is not the expected trust anchor")
    if payload["release_channel"] != expected_release_channel:
        raise PackagingError("signed executable identity release channel is not the expected channel")
    signature_text = envelope["signature"]
    if not isinstance(signature_text, str) or len(signature_text) > 128:
        raise PackagingError("signed executable identity signature encoding is invalid")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise PackagingError("signed executable identity signature is not canonical base64") from error
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != signature_text:
        raise PackagingError("signed executable identity signature has an invalid size or encoding")
    with tempfile.TemporaryDirectory(prefix="openfusion-identity-verify-") as workspace_value:
        workspace = Path(workspace_value)
        workspace.chmod(0o700)
        public_key = _copy_key_to_private_workspace(
            trusted_public_key_value, "trusted public key", workspace
        )
        public_der = _public_key_der(public_key, openssl)
        if hashlib.sha256(public_der).hexdigest() != key_digest:
            raise PackagingError("signed executable identity key fingerprint does not match the trusted key")
        payload_path = workspace / "payload.json"
        signature_path = workspace / "signature.bin"
        payload_path.write_bytes(_canonical_json_bytes(payload))
        signature_path.write_bytes(signature)
        _run_openssl(
            [
                openssl,
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-rawin",
                "-in",
                str(payload_path),
                "-sigfile",
                str(signature_path),
            ],
            "identity verification",
        )
    return payload


def _parse_identity_document(
    content: bytes,
    trusted_public_key_value: str | Path,
    openssl: Path,
    expected_key_sha256: str,
    expected_release_channel: str,
) -> tuple[dict[str, object], dict[str, object]]:
    if len(content) > MAX_IDENTITY_BYTES:
        raise PackagingError("signed executable identity exceeds the policy limit")
    try:
        envelope = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackagingError(f"signed executable identity is not canonical UTF-8 JSON: {error}") from error
    if _identity_envelope_bytes(envelope) != content:
        raise PackagingError("signed executable identity JSON is not in canonical form")
    payload = _verify_identity_envelope(
        envelope,
        trusted_public_key_value,
        openssl,
        expected_key_sha256,
        expected_release_channel,
    )
    assert isinstance(envelope, dict)
    return envelope, payload


def _records_by_path(records: Sequence[SourceRecord | Entry]) -> dict[str, SourceRecord | Entry]:
    return {record.relative_path: record for record in records}


def _payload_tree_commitment(
    records: Sequence[SourceRecord | Entry],
) -> dict[str, object]:
    payload_records = [
        record.manifest_record()
        for record in records
        if record.relative_path != IDENTITY_RELATIVE_PATH
    ]
    payload_records.sort(key=lambda record: str(record["path"]).encode("utf-8"))
    total_file_bytes = sum(
        int(record["size"])
        for record in payload_records
        if record["type"] == "file"
    )
    policy_bytes = _canonical_json_bytes(
        {"limits": POLICY_LIMITS, "version": POLICY_VERSION}
    )
    records_bytes = _canonical_json_bytes(payload_records)
    digest = hashlib.sha256()
    digest.update(PAYLOAD_TREE_DOMAIN)
    digest.update(policy_bytes)
    digest.update(records_bytes)
    return {
        "entry_count": len(payload_records),
        "domain": PAYLOAD_TREE_DOMAIN[:-1].decode("ascii"),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "sha256": digest.hexdigest(),
        "total_file_bytes": total_file_bytes,
    }


@functools.lru_cache(maxsize=1)
def _legal_quarantine_policy() -> dict[str, object]:
    content = _read_regular_path_bounded(
        LEGAL_POLICY_PATH,
        "archive legal-quarantine policy",
        MAX_LEGAL_POLICY_BYTES,
    )
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackagingError(f"archive legal-quarantine policy is invalid: {error}") from error
    if _canonical_json_bytes(value) != content or not isinstance(value, dict):
        raise PackagingError("archive legal-quarantine policy is not canonical JSON")
    if set(value) != {
        "forbidden_text",
        "format_version",
        "required_files",
        "restricted_patterns",
        "thumbnail_provider_sha256",
    }:
        raise PackagingError("archive legal-quarantine policy fields are invalid")
    if type(value["format_version"]) is not int or value["format_version"] != LEGAL_POLICY_FORMAT_VERSION:
        raise PackagingError("archive legal-quarantine policy version is unsupported")

    forbidden_text = value["forbidden_text"]
    if (
        not isinstance(forbidden_text, list)
        or not forbidden_text
        or any(not isinstance(item, str) or not item or not item.isascii() for item in forbidden_text)
        or len(set(forbidden_text)) != len(forbidden_text)
    ):
        raise PackagingError("archive forbidden-text policy is invalid")

    restricted = value["restricted_patterns"]
    if not isinstance(restricted, list) or len(restricted) != 32:
        raise PackagingError("archive quarantine must contain exactly 32 restricted patterns")
    restricted_paths: set[str] = set()
    restricted_identities: set[tuple[str, int]] = set()
    for record in restricted:
        if not isinstance(record, dict) or set(record) != {"sha256", "size", "source_path"}:
            raise PackagingError("archive restricted-pattern record is invalid")
        source_path = record["source_path"]
        digest = record["sha256"]
        size = record["size"]
        if (
            not isinstance(source_path, str)
            or not source_path
            or source_path in restricted_paths
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or type(size) is not int
            or size <= 0
            or (digest, size) in restricted_identities
        ):
            raise PackagingError("archive restricted-pattern identity is invalid or duplicated")
        restricted_paths.add(source_path)
        restricted_identities.add((digest, size))

    thumbnail_digest = value["thumbnail_provider_sha256"]
    if not isinstance(thumbnail_digest, str) or SHA256_RE.fullmatch(thumbnail_digest) is None:
        raise PackagingError("archive thumbnail-provider identity is invalid")

    required = value["required_files"]
    if not isinstance(required, list) or len(required) != 3:
        raise PackagingError("archive required legal inventory is invalid")
    required_paths: set[str] = set()
    for record in required:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise PackagingError("archive required legal-file record is invalid")
        path = record["path"]
        digest = record["sha256"]
        size = record["size"]
        if (
            not isinstance(path, str)
            or path in required_paths
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or type(size) is not int
            or size <= 0
        ):
            raise PackagingError("archive required legal-file identity is invalid or duplicated")
        _validate_relative_path(path)
        required_paths.add(path)
    return value


class _NormalizedLegalTextScanner:
    def __init__(self, forbidden_text: Sequence[str]) -> None:
        self._forbidden = {
            fragment: fragment.encode("ascii").lower() for fragment in forbidden_text
        }
        self._tail = b""
        self._pending_space = False
        self.matches: set[str] = set()
        self.restricted_metadata = False

    def feed(self, values: bytes) -> None:
        normalized = bytearray()
        for value in values:
            if value in b" \t\r\n\v\f":
                self._pending_space = True
                continue
            if self._pending_space:
                normalized.append(0x20)
                self._pending_space = False
            normalized.append(value + 32 if 65 <= value <= 90 else value)
        combined = self._tail + bytes(normalized)
        for name, pattern in self._forbidden.items():
            if pattern in combined:
                self.matches.add(name)
        if LEGAL_ARR_METADATA.search(combined):
            self.restricted_metadata = True
        self._tail = combined[-LEGAL_TEXT_OVERLAP_BYTES:]

    def finish(self) -> None:
        self.feed(b"\x00")


def _legal_alias_key(relative_path: str) -> str:
    if "\\" in relative_path:
        raise PackagingError(f"archive path uses a cross-platform alias separator: {relative_path}")
    normalized_components: list[str] = []
    for component in PurePosixPath(relative_path).parts:
        normalized = unicodedata.normalize("NFKC", component).casefold().rstrip(" .")
        if not normalized or ":" in normalized:
            raise PackagingError(f"archive path has an unsafe cross-platform alias: {relative_path}")
        normalized_components.append(normalized)
    return "/".join(normalized_components)


def _parse_legal_lfs_pointer(prefix: bytes, size: int, relative_path: str) -> tuple[str, int] | None:
    if size <= MAX_LEGAL_LFS_POINTER_BYTES:
        content = prefix[:size]
        match = LEGAL_LFS_POINTER.fullmatch(content)
        if match is not None:
            return match.group(1).decode("ascii"), int(match.group(2))
    else:
        content = prefix
    first_line = content.split(b"\n", 1)[0]
    pointer_shaped = (
        first_line.startswith(b"version https://git-lfs.github.com/spec/")
        or b"git-lfs.github.com/spec/" in content
        or (content.startswith(b"oid sha256:") and b"\nsize " in content)
    )
    if pointer_shaped:
        raise PackagingError(f"malformed or oversized Git LFS pointer in payload: {relative_path}")
    return None


def _inspect_legal_regular_file(
    entry: Entry,
    forbidden_text: Sequence[str],
) -> tuple[set[str], bool, tuple[str, int] | None]:
    if entry.size > MAX_LEGAL_SCAN_FILE_BYTES:
        raise PackagingError(
            f"payload file exceeds legal inspection limit: {entry.relative_path} "
            f"({entry.size} > {MAX_LEGAL_SCAN_FILE_BYTES})"
        )
    raw_scanner = _NormalizedLegalTextScanner(forbidden_text)
    wide_scanners = {
        width: tuple(_NormalizedLegalTextScanner(forbidden_text) for _ in range(width))
        for width in (2, 4)
    }
    prefix = bytearray()
    digest = hashlib.sha256()
    total = 0
    stream, _ = _open_regular_file(entry)
    with stream:
        while chunk := stream.read(LEGAL_SCAN_CHUNK_BYTES):
            if len(chunk) > LEGAL_SCAN_CHUNK_BYTES:
                raise PackagingError(f"oversized legal scan read: {entry.relative_path}")
            if len(prefix) < MAX_LEGAL_LFS_POINTER_BYTES + 1:
                remaining = MAX_LEGAL_LFS_POINTER_BYTES + 1 - len(prefix)
                prefix.extend(chunk[:remaining])
            digest.update(chunk)
            raw_scanner.feed(chunk)
            for width, lane_scanners in wide_scanners.items():
                for lane, scanner in enumerate(lane_scanners):
                    first = (lane - total) % width
                    scanner.feed(chunk[first::width])
            total += len(chunk)
            if total > entry.size:
                raise PackagingError(f"payload file grew during legal inspection: {entry.relative_path}")
        if Snapshot.from_stat(os.fstat(stream.fileno())) != entry.snapshot:
            raise PackagingError(f"payload file changed during legal inspection: {entry.relative_path}")
    if total != entry.size or digest.hexdigest() != entry.sha256:
        raise PackagingError(f"payload file identity changed during legal inspection: {entry.relative_path}")
    scanners = (
        raw_scanner,
        *(scanner for lane_scanners in wide_scanners.values() for scanner in lane_scanners),
    )
    for scanner in scanners:
        scanner.finish()
    return (
        set().union(*(scanner.matches for scanner in scanners)),
        any(scanner.restricted_metadata for scanner in scanners),
        _parse_legal_lfs_pointer(bytes(prefix), total, entry.relative_path),
    )


def _verify_legal_quarantine(payload_root: Path, entries: Sequence[Entry]) -> None:
    policy = _legal_quarantine_policy()
    restricted_records = policy["restricted_patterns"]
    assert isinstance(restricted_records, list)
    restricted = {
        (str(record["sha256"]), int(record["size"])): str(record["source_path"])
        for record in restricted_records
    }
    restricted_hashes = {digest for digest, _ in restricted}
    thumbnail_digest = str(policy["thumbnail_provider_sha256"])
    forbidden_text = policy["forbidden_text"]
    assert isinstance(forbidden_text, list)

    by_path: dict[str, Entry] = {}
    aliases: dict[str, str] = {}
    for entry in entries:
        if entry.relative_path in by_path:
            raise PackagingError(f"duplicate payload path during legal inspection: {entry.relative_path}")
        alias = _legal_alias_key(entry.relative_path)
        previous = aliases.get(alias)
        if previous is not None:
            raise PackagingError(
                f"cross-platform payload path alias collision: {previous} and {entry.relative_path}"
            )
        aliases[alias] = entry.relative_path
        by_path[entry.relative_path] = entry

        path_text = unicodedata.normalize("NFKC", entry.relative_path).casefold()
        for fragment in forbidden_text:
            if fragment.casefold() in path_text:
                raise PackagingError(
                    f"forbidden thumbnail-provider identity in payload path: {entry.relative_path}"
                )
        if entry.kind == "symlink":
            target = entry.link_target or ""
            target_text = unicodedata.normalize("NFKC", target).casefold()
            for fragment in forbidden_text:
                if fragment.casefold() in target_text:
                    raise PackagingError(
                        f"forbidden thumbnail-provider identity in symlink target: {entry.relative_path}"
                    )
            continue
        if entry.kind != "file":
            continue

        identity = (entry.sha256 or "", entry.size)
        restricted_source = restricted.get(identity)
        if restricted_source is not None:
            raise PackagingError(
                f"restricted material pattern identity in payload: {entry.relative_path} "
                f"(matches {restricted_source})"
            )
        if entry.sha256 == thumbnail_digest:
            raise PackagingError(
                f"quarantined thumbnail-provider binary identity in payload: {entry.relative_path}"
            )
        text_matches, restricted_metadata, pointer = _inspect_legal_regular_file(
            entry,
            [str(fragment) for fragment in forbidden_text],
        )
        if text_matches:
            raise PackagingError(
                f"forbidden thumbnail-provider text in payload {entry.relative_path}: "
                + ", ".join(sorted(text_matches))
            )
        if restricted_metadata:
            raise PackagingError(
                f"redistribution permission is not established by payload metadata: {entry.relative_path}"
            )
        if pointer is not None:
            pointer_digest, pointer_size = pointer
            if pointer_digest == thumbnail_digest or pointer_digest in restricted_hashes:
                raise PackagingError(
                    f"payload Git LFS pointer references a quarantined identity: "
                    f"{entry.relative_path} (sha256={pointer_digest}, size={pointer_size})"
                )

    required_records = policy["required_files"]
    assert isinstance(required_records, list)
    for expected in required_records:
        assert isinstance(expected, dict)
        path = str(expected["path"])
        entry = by_path.get(path)
        if (
            entry is None
            or entry.kind != "file"
            or entry.mode != 0o644
            or entry.size != expected["size"]
            or entry.sha256 != expected["sha256"]
        ):
            raise PackagingError(f"required shipped legal file is missing or differs: {path}")


def _validate_identity_against_records(
    payload: dict[str, object],
    records: Sequence[SourceRecord | Entry],
    version: str,
    architecture: str,
    prefix: str,
) -> None:
    if (
        payload["version"] != version
        or payload["architecture"] != architecture
        or payload["install_prefix"] != prefix
    ):
        raise PackagingError("signed executable identity does not match package coordinates")
    by_path = _records_by_path(records)
    if _payload_tree_commitment(records) != payload["payload_tree"]:
        raise PackagingError("signed payload-tree commitment does not match the staged payload")
    executables = payload["executables"]
    assert isinstance(executables, dict)
    for role, expected_path in CANONICAL_EXECUTABLES.items():
        expected = executables[role]
        assert isinstance(expected, dict)
        record = by_path.get(expected_path)
        if record is None or record.kind != "file" or record.mode != 0o755:
            raise PackagingError(f"signed {role} executable is missing or not executable: {expected_path}")
        if record.size != expected["size"] or record.sha256 != expected["sha256"]:
            raise PackagingError(f"signed {role} executable bytes do not match the staged payload")
        compatibility_path = COMPATIBILITY_EXECUTABLES[role]
        compatibility = by_path.get(compatibility_path)
        if (
            compatibility is None
            or compatibility.kind != "symlink"
            or compatibility.mode != 0o777
            or compatibility.link_target != PurePosixPath(expected_path).name
        ):
            raise PackagingError(
                f"signed {role} compatibility executable is missing or differs: {compatibility_path}"
            )


def _validate_expected_identity_coordinates(
    payload: dict[str, object],
    version: str,
    architecture: str,
    prefix: str,
    source_revision: str,
    dependency_lock_sha256: str,
) -> None:
    if SOURCE_REVISION_RE.fullmatch(source_revision) is None:
        raise PackagingError("expected source revision is invalid")
    if SHA256_RE.fullmatch(dependency_lock_sha256) is None:
        raise PackagingError("expected dependency lock SHA-256 is invalid")
    lock = payload["dependency_lock"]
    assert isinstance(lock, dict)
    if (
        payload["version"] != version
        or payload["architecture"] != architecture
        or payload["install_prefix"] != prefix
        or payload["source_revision"] != source_revision
        or lock["sha256"] != dependency_lock_sha256
    ):
        raise PackagingError("signed identity does not match expected package/source/lock coordinates")


def _inject_identity(snapshot_path: Path, identity_content: bytes, epoch: int) -> None:
    destination = snapshot_path / IDENTITY_RELATIVE_PATH
    if destination.exists() or destination.is_symlink():
        raise PackagingError(f"staged payload already contains reserved identity path: {IDENTITY_RELATIVE_PATH}")
    current = destination.parent
    if current.is_symlink() or not current.is_dir():
        raise PackagingError("staged payload must contain the canonical share/openfusion directory")
    current.chmod(0o755)
    destination.write_bytes(identity_content)
    destination.chmod(0o444)
    os.utime(destination, (epoch, epoch))
    current.chmod(0o555)
    os.utime(current, (epoch, epoch))


def create_identity(
    destdir_value: str | Path,
    prefix_value: str,
    version_value: str,
    architecture_value: str,
    release_channel: str,
    dependency_lock_value: str | Path,
    build_provenance_value: str | Path,
    cmake_cache_value: str | Path,
    signing_key_value: str | Path,
    output_value: str | Path,
    openssl_value: str | None = None,
) -> Path:
    """Create a signed offline identity without executing staged binaries."""

    version = _validate_version(version_value)
    architecture = _validate_architecture(architecture_value)
    prefix = _validate_prefix(prefix_value)
    destdir = _canonical_directory(destdir_value, "DESTDIR")
    openssl = _find_openssl(openssl_value)
    lock_content = _read_regular_path_bounded(
        dependency_lock_value, "dependency lock", MAX_MANIFEST_BYTES
    )
    lock_digest = hashlib.sha256(lock_content).hexdigest()
    provenance = _parse_build_provenance(
        _read_regular_path_bounded(
            build_provenance_value, "build provenance", MAX_PROVENANCE_BYTES
        )
    )
    cmake_cache_digest = _sha256_regular_path_bounded(
        cmake_cache_value, "CMake cache", MAX_MANIFEST_BYTES
    )
    openssl_digest = openssl.sha256
    openssl_version = _run_openssl([openssl, "version"], "version query").decode(
        "utf-8", errors="strict"
    ).strip()
    if (
        provenance["dependency_lock_sha256"] != lock_digest
        or provenance["version"] != version
        or provenance["cmake_cache_sha256"] != cmake_cache_digest
        or provenance["openssl_sha256"] != openssl_digest
        or provenance["openssl_version"] != openssl_version
    ):
        raise PackagingError("build provenance does not match version/lock/CMake/OpenSSL inputs")
    destdir_descriptor = _open_directory(destdir, "DESTDIR")
    source_descriptor: int | None = None
    try:
        source_descriptor = _open_prefix_at(destdir_descriptor, prefix)
        scan = _scan_source_tree(source_descriptor, None, int(provenance["source_date_epoch"]), architecture)
        _validate_payload_elf(
            _scan_tree(_descriptor_path(source_descriptor)), architecture
        )
        if IDENTITY_RELATIVE_PATH in _records_by_path(scan.records):
            raise PackagingError(f"staged payload already contains reserved identity path: {IDENTITY_RELATIVE_PATH}")
        by_path = _records_by_path(scan.records)
        executable_records: dict[str, dict[str, object]] = {}
        for role, relative_path in CANONICAL_EXECUTABLES.items():
            record = by_path.get(relative_path)
            if (
                record is None
                or record.kind != "file"
                or record.mode != 0o755
                or record.elf_identity is None
                or not record.sha256
                or record.size <= 0
            ):
                raise PackagingError(f"canonical {role} executable is missing or invalid: {relative_path}")
            executable_records[role] = {
                "compatibility_path": COMPATIBILITY_EXECUTABLES[role],
                "path": relative_path,
                "sha256": record.sha256,
                "size": record.size,
            }
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        os.close(destdir_descriptor)
    payload: dict[str, object] = {
        "architecture": architecture,
        "build_provenance": provenance,
        "dependency_lock": {"path": "pixi.lock", "sha256": lock_digest},
        "executables": executable_records,
        "format_version": IDENTITY_FORMAT_VERSION,
        "install_prefix": str(prefix),
        "platform": "linux",
        "product": "OpenFusion",
        "payload_tree": _payload_tree_commitment(scan.records),
        "release_channel": release_channel,
        "source_date_epoch": provenance["source_date_epoch"],
        "source_revision": provenance["source_revision"],
        "version": version,
    }
    _validate_identity_against_records(
        payload,
        scan.records,
        version,
        architecture,
        str(prefix),
    )
    envelope = _sign_identity_payload(payload, signing_key_value, openssl)
    return _write_new_regular_path(
        output_value, "signed executable identity", _identity_envelope_bytes(envelope)
    )


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
    prefix: str,
    identity_content: bytes,
    identity_envelope: dict[str, object],
    identity_payload: dict[str, object],
) -> tuple[Path, dict[str, object], SourceScan]:
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
        _validate_identity_against_records(
            identity_payload, copied.records, version, architecture, prefix
        )
        _inject_identity(_descriptor_path(private_descriptor, "snapshot"), identity_content, epoch)
        os.fsync(snapshot_descriptor)
    finally:
        os.close(snapshot_descriptor)
    return _descriptor_path(private_descriptor, "snapshot"), identity_envelope, copied


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
        if entry.relative_path in CANONICAL_EXECUTABLES.values():
            marker_found = False
            overlap = b""
            with entry.source_path.open("rb") as stream:
                while data := stream.read(READ_SIZE):
                    candidate = overlap + data
                    if ORIGIN_RUNPATH_MARKER in candidate:
                        marker_found = True
                        break
                    overlap = candidate[-len(ORIGIN_RUNPATH_MARKER) :]
            if not marker_found:
                raise PackagingError(
                    "canonical entrypoint lacks packaged-library RUNPATH: "
                    f"{entry.relative_path}"
                )


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
    product_identity: dict[str, object],
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
    manifest_bytes: bytes,
    trusted_public_key_value: str | Path,
    openssl: Path,
    expected_key_sha256: str,
    expected_release_channel: str,
    expected_version: str,
    expected_architecture: str,
    expected_prefix: str,
    expected_source_revision: str,
    expected_dependency_lock_sha256: str,
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
    identity_payload = _verify_identity_envelope(
        product_identity,
        trusted_public_key_value,
        openssl,
        expected_key_sha256,
        expected_release_channel,
    )
    architecture = manifest["architecture"]
    if not isinstance(architecture, str):
        raise PackagingError("manifest architecture must be a string")
    _validate_architecture(architecture)
    version = manifest["version"]
    if not isinstance(version, str):
        raise PackagingError("manifest version must be a string")
    _validate_version(version)
    prefix = manifest["install_prefix"]
    if not isinstance(prefix, str):
        raise PackagingError("manifest install prefix must be a string")
    _validate_prefix(prefix)
    _validate_expected_identity_coordinates(
        identity_payload,
        expected_version,
        expected_architecture,
        expected_prefix,
        expected_source_revision,
        expected_dependency_lock_sha256,
    )
    if version != expected_version or architecture != expected_architecture or prefix != expected_prefix:
        raise PackagingError("manifest does not match expected package coordinates")
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
    if identity_payload["source_date_epoch"] != epoch:
        raise PackagingError("manifest SOURCE_DATE_EPOCH does not match signed executable identity")
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
    manifest_records: list[Entry] = []
    for record in records:
        assert isinstance(record, dict)
        manifest_records.append(
            Entry(
                relative_path=str(record["path"]),
                source_path=Path("/manifest"),
                kind=str(record["type"]),
                mode=int(record["mode"]),
                size=int(record.get("size", 0)),
                sha256=str(record["sha256"]) if record["type"] == "file" else None,
                link_target=str(record["target"]) if record["type"] == "symlink" else None,
                snapshot=Snapshot(0, 0, 0, 0, 0, 0, 0),
            )
        )
    _validate_identity_against_records(identity_payload, manifest_records, version, architecture, prefix)
    identity_record = next(
        (record for record in records if record["path"] == IDENTITY_RELATIVE_PATH),
        None,
    )
    identity_content = _identity_envelope_bytes(product_identity)
    if (
        identity_record is None
        or identity_record.get("type") != "file"
        or identity_record.get("mode") != 0o644
        or identity_record.get("size") != len(identity_content)
        or identity_record.get("sha256") != hashlib.sha256(identity_content).hexdigest()
    ):
        raise PackagingError("manifest does not contain the canonical signed executable identity")
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
        _verify_legal_quarantine(payload_root, extracted_entries)
        identity_path = payload_root / IDENTITY_RELATIVE_PATH
        if identity_path.read_bytes() != _identity_envelope_bytes(manifest["product_identity"]):
            raise PackagingError("extracted signed executable identity does not match manifest")
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
    trusted_public_key_value: str | Path,
    openssl: Path,
    expected_key_sha256: str,
    expected_release_channel: str,
    expected_version: str,
    expected_architecture: str,
    expected_prefix: str,
    expected_source_revision: str,
    expected_dependency_lock_sha256: str,
) -> dict[str, object]:
    manifest = _parse_manifest(
        manifest_bytes,
        trusted_public_key_value,
        openssl,
        expected_key_sha256,
        expected_release_channel,
        expected_version,
        expected_architecture,
        expected_prefix,
        expected_source_revision,
        expected_dependency_lock_sha256,
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
    identity_value: str | Path,
    trusted_public_key_value: str | Path,
    expected_key_sha256: str,
    expected_release_channel: str,
    expected_source_revision: str,
    expected_dependency_lock_sha256: str,
    zstd_value: str | None = None,
    openssl_value: str | None = None,
    *,
    staging_is_quiescent: bool = False,
    output_is_exclusive: bool = False,
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
    openssl = _find_openssl(openssl_value)
    identity_content = _read_regular_path_bounded(
        identity_value, "signed executable identity", MAX_IDENTITY_BYTES
    )
    identity_envelope, identity_payload = _parse_identity_document(
        identity_content,
        trusted_public_key_value,
        openssl,
        expected_key_sha256,
        expected_release_channel,
    )
    if identity_payload["source_date_epoch"] != epoch:
        raise PackagingError("SOURCE_DATE_EPOCH does not match signed executable identity")
    _validate_expected_identity_coordinates(
        identity_payload,
        version,
        architecture,
        str(prefix),
        expected_source_revision,
        expected_dependency_lock_sha256,
    )

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
                str(prefix),
                identity_content,
                identity_envelope,
                identity_payload,
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
                trusted_public_key_value,
                openssl,
                expected_key_sha256,
                expected_release_channel,
                version,
                architecture,
                str(prefix),
                expected_source_revision,
                expected_dependency_lock_sha256,
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
    trusted_public_key_value: str | Path,
    expected_key_sha256: str,
    expected_release_channel: str,
    expected_version: str,
    expected_architecture: str,
    expected_prefix: str,
    expected_source_revision: str,
    expected_dependency_lock_sha256: str,
    zstd_value: str | None = None,
    openssl_value: str | None = None,
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
    openssl = _find_openssl(openssl_value)
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
                trusted_public_key_value,
                openssl,
                expected_key_sha256,
                expected_release_channel,
                expected_version,
                expected_architecture,
                expected_prefix,
                expected_source_revision,
                expected_dependency_lock_sha256,
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
                trusted_public_key_value,
                openssl,
                expected_key_sha256,
                expected_release_channel,
                expected_version,
                expected_architecture,
                expected_prefix,
                expected_source_revision,
                expected_dependency_lock_sha256,
            )
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    identity = subparsers.add_parser(
        "create-identity",
        help="create a signed offline identity for staged GUI/CLI executables",
    )
    identity.add_argument("--destdir", required=True, help="canonical absolute DESTDIR")
    identity.add_argument("--prefix", required=True, help="exact absolute POSIX install prefix")
    identity.add_argument("--version", required=True, help="semantic OpenFusion version")
    identity.add_argument(
        "--architecture", required=True, choices=sorted(SUPPORTED_ARCHITECTURES)
    )
    identity.add_argument(
        "--release-channel", required=True, choices=("development", "production")
    )
    identity.add_argument("--dependency-lock", required=True, help="canonical absolute pixi.lock path")
    identity.add_argument("--build-provenance", required=True, help="canonical build provenance JSON")
    identity.add_argument("--cmake-cache", required=True, help="canonical CMakeCache.txt path")
    identity.add_argument("--signing-key", required=True, help="canonical Ed25519 private-key path")
    identity.add_argument("--output", required=True, help="new canonical identity JSON path")
    identity.add_argument("--openssl", help="openssl executable; defaults to PATH lookup")

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
    build.add_argument("--identity", required=True, help="signed executable identity JSON")
    build.add_argument("--trusted-public-key", required=True, help="trusted Ed25519 public key")
    build.add_argument("--expected-key-sha256", required=True, help="expected trusted Ed25519 key fingerprint")
    build.add_argument(
        "--expected-release-channel", required=True, choices=("development", "production")
    )
    build.add_argument("--expected-source-revision", required=True)
    build.add_argument("--expected-lock-sha256", required=True)
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
    build.add_argument("--openssl", help="openssl executable; defaults to PATH lookup")

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
    verify.add_argument("--trusted-public-key", required=True, help="trusted Ed25519 public key")
    verify.add_argument("--expected-key-sha256", required=True, help="expected trusted Ed25519 key fingerprint")
    verify.add_argument(
        "--expected-release-channel", required=True, choices=("development", "production")
    )
    verify.add_argument("--expected-version", required=True)
    verify.add_argument(
        "--expected-architecture", required=True, choices=sorted(SUPPORTED_ARCHITECTURES)
    )
    verify.add_argument("--expected-prefix", required=True)
    verify.add_argument("--expected-source-revision", required=True)
    verify.add_argument("--expected-lock-sha256", required=True)
    verify.add_argument("--zstd", help="zstd executable; defaults to PATH lookup")
    verify.add_argument("--openssl", help="openssl executable; defaults to PATH lookup")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        if args.command == "create-identity":
            identity = create_identity(
                args.destdir,
                args.prefix,
                args.version,
                args.architecture,
                args.release_channel,
                args.dependency_lock,
                args.build_provenance,
                args.cmake_cache,
                args.signing_key,
                args.output,
                args.openssl,
            )
            print(identity)
        elif args.command == "build":
            artifact, manifest, checksum = build_package(
                args.destdir,
                args.prefix,
                args.version,
                args.architecture,
                args.output_dir,
                _source_date_epoch(),
                args.identity,
                args.trusted_public_key,
                args.expected_key_sha256,
                args.expected_release_channel,
                args.expected_source_revision,
                args.expected_lock_sha256,
                args.zstd,
                args.openssl,
                staging_is_quiescent=args.staging_is_quiescent,
                output_is_exclusive=args.output_is_exclusive,
            )
            print(artifact)
            print(manifest)
            print(checksum)
        else:
            verify_package(
                args.archive,
                args.manifest,
                args.checksum,
                args.trusted_public_key,
                args.expected_key_sha256,
                args.expected_release_channel,
                args.expected_version,
                args.expected_architecture,
                args.expected_prefix,
                args.expected_source_revision,
                args.expected_lock_sha256,
                args.zstd,
                args.openssl,
            )
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
