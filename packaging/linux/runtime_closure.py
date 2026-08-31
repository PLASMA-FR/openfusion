#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bundle and verify the locked Linux runtime without executing payload code."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import contextlib
from dataclasses import dataclass, replace
import functools
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import struct
import sys
import unicodedata
from typing import Iterable, Sequence
from urllib.parse import urlsplit


FORMAT_VERSION = 1
MANIFEST_RELATIVE_PATH = "share/openfusion/runtime-closure.json"
MAX_ELF_BYTES = (1 << 33) - 1
MAX_DYNAMIC_BYTES = 16 * 1024 * 1024
MAX_STRING_TABLE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_METADATA_TOTAL_BYTES = 256 * 1024 * 1024
MAX_LOCK_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024 * 1024
MAX_FILES = 250_000
COPY_CHUNK_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
LICENSE_PROVENANCE_PATH = Path(__file__).resolve().with_name(
    "runtime_license_provenance.json"
)
MAX_LICENSE_PROVENANCE_BYTES = 1024 * 1024

# Only the dynamic loader and the glibc ABI are delegated to the host. Compiler,
# graphics, X11, Qt, Python, OpenCascade, and every other library are bundled.
_GLIBC_ABI = (
    "libBrokenLocale.so.1",
    "libanl.so.1",
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
    "libutil.so.1",
)
ARCHITECTURES = {
    "aarch64": {
        "interpreters": ("/lib/ld-linux-aarch64.so.1",),
        "machine": 183,
        "subdir": "linux-aarch64",
        "system_abi": tuple(sorted(_GLIBC_ABI + ("ld-linux-aarch64.so.1",))),
    },
    "x86_64": {
        "interpreters": ("/lib64/ld-linux-x86-64.so.2",),
        "machine": 62,
        "subdir": "linux-64",
        "system_abi": tuple(sorted(_GLIBC_ABI + ("ld-linux-x86-64.so.2",))),
    },
}
RUNTIME_PREFIXES = (
    "lib/ossl-modules/",
    "lib/qt6/plugins/",
    "ssl/",
)
GENERATED_PROVENANCE = "openfusion-runtime-closure-v1"


class ClosureError(RuntimeError):
    """Raised when a stage cannot be proven self-contained."""


@dataclass(frozen=True)
class ElfInfo:
    relative_path: str
    machine: int
    needed: tuple[str, ...]
    soname: str | None
    runpath: tuple[str, ...]
    rpath: tuple[str, ...]
    interpreter: str | None
    dynamic: bool

    def manifest_record(self) -> dict[str, object]:
        return {
            "interpreter": self.interpreter,
            "needed": list(self.needed),
            "path": self.relative_path,
            "rpath": list(self.rpath),
            "runpath": list(self.runpath),
            "soname": self.soname,
        }


@dataclass(frozen=True)
class ClosureReport:
    elf_count: int
    dynamic_elf_count: int
    issues: tuple[str, ...]
    elf: tuple[ElfInfo, ...]


@dataclass(frozen=True)
class PackageRecord:
    name: str
    version: str
    build: str
    subdir: str
    url: str
    sha256: str
    license: str | None
    depends: tuple[str, ...]
    files: tuple[str, ...]

    def manifest_record(self) -> dict[str, str]:
        if not self.license:
            raise ClosureError(
                f"selected runtime package lacks license provenance: {self.name}"
            )
        return {
            "build": self.build,
            "license": self.license,
            "name": self.name,
            "sha256": self.sha256,
            "subdir": self.subdir,
            "url": self.url,
            "version": self.version,
        }

    def selection_manifest_record(self) -> dict[str, object]:
        record: dict[str, object] = self.manifest_record()
        record["depends"] = list(self.depends)
        record["files"] = list(self.files)
        return record


@dataclass(frozen=True)
class LockedPackage:
    url: str
    sha256: str
    license: str | None


@functools.lru_cache(maxsize=1)
def _license_provenance() -> tuple[dict[str, tuple[str, str]], tuple[tuple[str, bytes], ...]]:
    content = _read_bounded(
        LICENSE_PROVENANCE_PATH,
        MAX_LICENSE_PROVENANCE_BYTES,
        "runtime license provenance policy",
    )
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ClosureError("runtime license provenance policy is invalid JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "evidence",
        "format_version",
        "packages",
    } or value["format_version"] != 1:
        raise ClosureError("runtime license provenance policy has invalid fields")
    evidence = value["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {
        "feedstock_revision",
        "feedstock_url",
        "files",
        "license",
    }:
        raise ClosureError("runtime license evidence has invalid fields")
    if (
        evidence["license"] != "Apache-2.0"
        or not re.fullmatch(r"[0-9a-f]{40}", evidence["feedstock_revision"])
        or evidence["feedstock_url"]
        != "https://github.com/conda-forge/openvino-feedstock"
        or not isinstance(evidence["files"], list)
    ):
        raise ClosureError("runtime license evidence coordinates are invalid")
    evidence_files = []
    seen_paths = set()
    for record in evidence["files"]:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise ClosureError("runtime license evidence file record is invalid")
        relative = _relative_path(record["path"])
        if relative in seen_paths or not SHA256_RE.fullmatch(record["sha256"]):
            raise ClosureError("runtime license evidence file identity is invalid")
        if not isinstance(record["size"], int) or isinstance(record["size"], bool):
            raise ClosureError("runtime license evidence file size is invalid")
        path = LICENSE_PROVENANCE_PATH.parent.joinpath(*PurePosixPath(relative).parts)
        file_content = _read_bounded(path, 16 * 1024 * 1024, "runtime license evidence")
        if (
            len(file_content) != record["size"]
            or hashlib.sha256(file_content).hexdigest() != record["sha256"]
        ):
            raise ClosureError(f"runtime license evidence identity mismatch: {relative}")
        evidence_files.append((relative, file_content))
        seen_paths.add(relative)
    packages = value["packages"]
    if not isinstance(packages, list):
        raise ClosureError("runtime license package provenance is invalid")
    package_map = {}
    for record in packages:
        if not isinstance(record, dict) or set(record) != {"sha256", "url"}:
            raise ClosureError("runtime license package record is invalid")
        if (
            not isinstance(record["url"], str)
            or not SHA256_RE.fullmatch(record["sha256"])
            or record["url"] in package_map
        ):
            raise ClosureError("runtime license package identity is invalid")
        package_map[record["url"]] = (record["sha256"], evidence["license"])
    return package_map, tuple(evidence_files)


@dataclass(frozen=True)
class CopyPlan:
    destination: str
    source: Path
    source_relative_path: str
    package: PackageRecord
    kind: str
    link_target: str | None
    elf_info: ElfInfo | None


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _canonical_directory(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ClosureError(f"{label} must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ClosureError(f"{label} cannot be resolved: {error}") from error
    if resolved != path or not resolved.is_dir():
        raise ClosureError(f"{label} must be a canonical directory")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ClosureError("runtime path is empty or contains NUL")
    if unicodedata.normalize("NFC", value) != value:
        raise ClosureError(f"runtime path is not NFC-normalized: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or ".." in path.parts:
        raise ClosureError(f"unsafe runtime path: {value!r}")
    if len(value.encode("utf-8")) > 4095:
        raise ClosureError(f"runtime path is too long: {value!r}")
    return value


def _alias_key(value: str) -> str:
    return "/".join(
        unicodedata.normalize("NFKC", part).casefold().rstrip(" .")
        for part in PurePosixPath(value).parts
    )


def _read_bounded(path: Path, maximum: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ClosureError(f"cannot open {label}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise ClosureError(f"{label} is not a bounded regular file")
        chunks = []
        total = 0
        while total < metadata.st_size:
            data = os.pread(
                descriptor,
                min(COPY_CHUNK_BYTES, metadata.st_size - total),
                total,
            )
            if not data:
                raise ClosureError(f"{label} ended before its declared size")
            chunks.append(data)
            total += len(data)
        if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(metadata):
            raise ClosureError(f"{label} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_anchored_bounded(
    root_descriptor: int, relative: str, maximum: int, label: str
) -> bytes:
    descriptor, _resolved = _open_anchored_regular(root_descriptor, relative)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_size > maximum:
            raise ClosureError(f"{label} exceeds its size limit")
        chunks = []
        total = 0
        while total < metadata.st_size:
            data = os.pread(
                descriptor,
                min(COPY_CHUNK_BYTES, metadata.st_size - total),
                total,
            )
            if not data:
                raise ClosureError(f"{label} ended before its declared size")
            chunks.append(data)
            total += len(data)
        if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(metadata):
            raise ClosureError(f"{label} changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _hash_regular(path: Path | int) -> tuple[int, str]:
    if isinstance(path, int):
        descriptor = os.dup(path)
        label = f"descriptor {path}"
    else:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ClosureError(f"cannot open regular runtime file {path}: {error}") from error
        label = str(path)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ELF_BYTES:
            raise ClosureError(f"runtime file is not a bounded regular file: {label}")
        digest = hashlib.sha256()
        total = 0
        while True:
            data = os.pread(descriptor, min(COPY_CHUNK_BYTES, before.st_size - total), total)
            if not data:
                break
            total += len(data)
            digest.update(data)
        after = os.fstat(descriptor)
        if total != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ClosureError(f"runtime file changed while being hashed: {label}")
        return total, digest.hexdigest()
    finally:
        os.close(descriptor)


def _pread_exact(descriptor: int, size: int, offset: int, label: str) -> bytes:
    data = os.pread(descriptor, size, offset)
    if len(data) != size:
        raise ClosureError(f"truncated ELF structure in {label}")
    return data


def _snapshot_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _require_unchanged(descriptor: int, before: os.stat_result, label: str) -> None:
    if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(before):
        raise ClosureError(f"ELF changed while being inspected: {label}")


def parse_elf(path: Path | int, relative_path: str | None = None) -> ElfInfo | None:
    """Parse ELF64 dynamic metadata with bounded descriptor reads."""

    label = relative_path or str(path)
    if isinstance(path, int):
        descriptor = os.dup(path)
    else:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ClosureError(f"cannot open ELF candidate {label}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_ELF_BYTES:
            raise ClosureError(f"ELF candidate is not a bounded regular file: {label}")
        if metadata.st_size < 4:
            _require_unchanged(descriptor, metadata, label)
            return None
        magic = _pread_exact(descriptor, 4, 0, label)
        if magic != b"\x7fELF":
            _require_unchanged(descriptor, metadata, label)
            return None
        if metadata.st_size < 64:
            raise ClosureError(f"truncated ELF header in {label}")
        header = _pread_exact(descriptor, 64, 0, label)
        if header[4:7] != b"\x02\x01\x01":
            raise ClosureError(f"only little-endian ELF64 is supported: {label}")
        machine = struct.unpack_from("<H", header, 18)[0]
        program_offset = struct.unpack_from("<Q", header, 32)[0]
        program_entry_size = struct.unpack_from("<H", header, 54)[0]
        program_count = struct.unpack_from("<H", header, 56)[0]
        if program_count == 0:
            result = ElfInfo(label, machine, (), None, (), (), None, False)
            _require_unchanged(descriptor, metadata, label)
            return result
        if program_count > 4096 or not 56 <= program_entry_size <= 256:
            raise ClosureError(f"invalid ELF program-header table in {label}")
        table_size = program_count * program_entry_size
        if program_offset > metadata.st_size or table_size > metadata.st_size - program_offset:
            raise ClosureError(f"ELF program-header table escapes file: {label}")

        loads: list[tuple[int, int, int, int]] = []
        dynamic_segment: tuple[int, int] | None = None
        interpreter_segment: tuple[int, int] | None = None
        for index in range(program_count):
            raw = _pread_exact(
                descriptor,
                program_entry_size,
                program_offset + index * program_entry_size,
                label,
            )
            segment_type, _flags, offset, virtual, _physical, file_size, _memory, _align = (
                struct.unpack_from("<IIQQQQQQ", raw)
            )
            if offset > metadata.st_size or file_size > metadata.st_size - offset:
                raise ClosureError(f"ELF segment escapes file: {label}")
            if segment_type == 1:
                loads.append((virtual, file_size, offset, file_size))
            elif segment_type == 2:
                if dynamic_segment is not None:
                    raise ClosureError(f"multiple ELF dynamic segments: {label}")
                dynamic_segment = (offset, file_size)
            elif segment_type == 3:
                if interpreter_segment is not None or file_size > 4096:
                    raise ClosureError(f"invalid ELF interpreter segment: {label}")
                interpreter_segment = (offset, file_size)

        interpreter = None
        if interpreter_segment is not None:
            content = _pread_exact(descriptor, interpreter_segment[1], interpreter_segment[0], label)
            if not content.endswith(b"\x00") or b"\x00" in content[:-1]:
                raise ClosureError(f"malformed ELF interpreter: {label}")
            try:
                interpreter = content[:-1].decode("ascii")
            except UnicodeDecodeError as error:
                raise ClosureError(f"non-ASCII ELF interpreter: {label}") from error

        if dynamic_segment is None:
            result = ElfInfo(label, machine, (), None, (), (), interpreter, False)
            _require_unchanged(descriptor, metadata, label)
            return result
        dynamic_offset, dynamic_size = dynamic_segment
        if dynamic_size > MAX_DYNAMIC_BYTES or dynamic_size % 16:
            raise ClosureError(f"invalid bounded ELF dynamic segment: {label}")
        dynamic = _pread_exact(descriptor, dynamic_size, dynamic_offset, label)
        tags: dict[int, list[int]] = defaultdict(list)
        terminated = False
        for offset in range(0, len(dynamic), 16):
            tag, value = struct.unpack_from("<qQ", dynamic, offset)
            if tag == 0:
                terminated = True
                break
            tags[tag].append(value)
        if not terminated:
            raise ClosureError(f"unterminated ELF dynamic segment: {label}")

        string_tags = tags.get(1, []) + tags.get(14, []) + tags.get(15, []) + tags.get(29, [])
        strings = b""
        if string_tags:
            if len(tags.get(5, [])) != 1 or len(tags.get(10, [])) != 1:
                raise ClosureError(f"ambiguous ELF dynamic string table: {label}")
            string_virtual = tags[5][0]
            string_size = tags[10][0]
            if string_size > MAX_STRING_TABLE_BYTES:
                raise ClosureError(f"ELF dynamic string table exceeds limit: {label}")
            string_offset = None
            for virtual, file_size, file_offset, _ in loads:
                relative_string_offset = string_virtual - virtual
                if 0 <= relative_string_offset < file_size:
                    candidate = file_offset + relative_string_offset
                    if string_size <= file_size - relative_string_offset:
                        string_offset = candidate
                        break
            if string_offset is None:
                raise ClosureError(f"ELF dynamic string table is unmapped: {label}")
            strings = _pread_exact(descriptor, string_size, string_offset, label)

        def dynamic_string(offset: int) -> str:
            if offset >= len(strings):
                raise ClosureError(f"ELF dynamic string offset escapes table: {label}")
            end = strings.find(b"\x00", offset)
            if end < 0:
                raise ClosureError(f"unterminated ELF dynamic string: {label}")
            try:
                return strings[offset:end].decode("ascii")
            except UnicodeDecodeError as error:
                raise ClosureError(f"non-ASCII ELF dynamic string: {label}") from error

        if len(tags.get(14, [])) > 1 or len(tags.get(15, [])) > 1 or len(tags.get(29, [])) > 1:
            raise ClosureError(f"duplicate ELF SONAME/RPATH/RUNPATH tag: {label}")
        needed = tuple(dynamic_string(value) for value in tags.get(1, []))
        soname = dynamic_string(tags[14][0]) if tags.get(14) else None
        rpath = tuple(dynamic_string(tags[15][0]).split(":")) if tags.get(15) else ()
        runpath = tuple(dynamic_string(tags[29][0]).split(":")) if tags.get(29) else ()
        result = ElfInfo(label, machine, needed, soname, runpath, rpath, interpreter, True)
        _require_unchanged(descriptor, metadata, label)
        return result
    finally:
        os.close(descriptor)


def _convert_rpath_tag_to_runpath(descriptor: int, label: str) -> None:
    before = os.fstat(descriptor)
    header = _pread_exact(descriptor, 64, 0, label)
    if header[:7] != b"\x7fELF\x02\x01\x01":
        raise ClosureError(f"cannot normalize non-ELF runtime file: {label}")
    program_offset = struct.unpack_from("<Q", header, 32)[0]
    program_entry_size = struct.unpack_from("<H", header, 54)[0]
    program_count = struct.unpack_from("<H", header, 56)[0]
    if program_count > 4096 or not 56 <= program_entry_size <= 256:
        raise ClosureError(f"invalid ELF program headers during RUNPATH normalization: {label}")
    dynamic_segment = None
    for index in range(program_count):
        raw = _pread_exact(
            descriptor,
            program_entry_size,
            program_offset + index * program_entry_size,
            label,
        )
        segment_type, _flags, offset, _virtual, _physical, file_size, _memory, _align = (
            struct.unpack_from("<IIQQQQQQ", raw)
        )
        if segment_type == 2:
            if dynamic_segment is not None:
                raise ClosureError(f"multiple ELF dynamic segments during normalization: {label}")
            dynamic_segment = (offset, file_size)
    if dynamic_segment is None or dynamic_segment[1] > MAX_DYNAMIC_BYTES or dynamic_segment[1] % 16:
        raise ClosureError(f"invalid ELF dynamic segment during normalization: {label}")
    rpath_offsets = []
    runpath_offsets = []
    terminated = False
    for relative_offset in range(0, dynamic_segment[1], 16):
        entry_offset = dynamic_segment[0] + relative_offset
        tag = struct.unpack("<q", _pread_exact(descriptor, 8, entry_offset, label))[0]
        if tag == 0:
            terminated = True
            break
        if tag == 15:
            rpath_offsets.append(entry_offset)
        elif tag == 29:
            runpath_offsets.append(entry_offset)
    if not terminated or len(rpath_offsets) != 1 or runpath_offsets:
        raise ClosureError(f"ambiguous DT_RPATH conversion is forbidden: {label}")
    if os.pwrite(descriptor, struct.pack("<q", 29), rpath_offsets[0]) != 8:
        raise ClosureError(f"short write during RUNPATH normalization: {label}")
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ClosureError(f"ELF identity changed during RUNPATH normalization: {label}")


def _expected_central_runpath(relative_path: str) -> str:
    parent = PurePosixPath(_relative_path(relative_path)).parent.as_posix()
    relative = posixpath.relpath("lib", parent)
    return "$ORIGIN" if relative == "." else f"$ORIGIN/{relative}"


def _normalized_needed_info(info: ElfInfo) -> ElfInfo:
    normalized = []
    for needed in info.needed:
        if "/" not in needed:
            normalized.append(needed)
            continue
        path = PurePosixPath(needed)
        if not path.is_absolute() or path.name in ("", ".", ".."):
            raise ClosureError(
                f"unsafe path-qualified DT_NEEDED in {info.relative_path}: {needed}"
            )
        normalized.append(path.name)
    return replace(info, needed=tuple(normalized))


def _pwrite_patch(
    descriptor: int,
    offset: int,
    content: bytes,
    patches: list[tuple[int, bytes]] | None,
    label: str,
) -> None:
    original = _pread_exact(descriptor, len(content), offset, label)
    if patches is not None:
        patches.append((offset, original))
    if os.pwrite(descriptor, content, offset) != len(content):
        raise ClosureError(f"short ELF patch write: {label}")


def _normalize_needed_descriptor(
    descriptor: int,
    label: str,
    original: ElfInfo,
    patches: list[tuple[int, bytes]] | None = None,
) -> bool:
    if not any("/" in value for value in original.needed):
        return False
    before = os.fstat(descriptor)
    header = _pread_exact(descriptor, 64, 0, label)
    program_offset = struct.unpack_from("<Q", header, 32)[0]
    program_entry_size = struct.unpack_from("<H", header, 54)[0]
    program_count = struct.unpack_from("<H", header, 56)[0]
    if program_count > 4096 or not 56 <= program_entry_size <= 256:
        raise ClosureError(f"invalid ELF headers during DT_NEEDED normalization: {label}")
    dynamic_segment = None
    loads = []
    for index in range(program_count):
        raw = _pread_exact(
            descriptor,
            program_entry_size,
            program_offset + index * program_entry_size,
            label,
        )
        segment_type, _flags, offset, virtual, _physical, file_size, _memory, _align = (
            struct.unpack_from("<IIQQQQQQ", raw)
        )
        if segment_type == 1:
            loads.append((virtual, file_size, offset))
        elif segment_type == 2:
            if dynamic_segment is not None:
                raise ClosureError(f"multiple dynamic segments during DT_NEEDED normalization: {label}")
            dynamic_segment = (offset, file_size)
    if dynamic_segment is None or dynamic_segment[1] > MAX_DYNAMIC_BYTES or dynamic_segment[1] % 16:
        raise ClosureError(f"invalid dynamic segment during DT_NEEDED normalization: {label}")
    needed_entries = []
    string_tables = []
    string_sizes = []
    terminated = False
    for relative_offset in range(0, dynamic_segment[1], 16):
        entry_offset = dynamic_segment[0] + relative_offset
        tag, value = struct.unpack(
            "<qQ", _pread_exact(descriptor, 16, entry_offset, label)
        )
        if tag == 0:
            terminated = True
            break
        if tag == 1:
            needed_entries.append((entry_offset, value))
        elif tag == 5:
            string_tables.append(value)
        elif tag == 10:
            string_sizes.append(value)
    if (
        not terminated
        or len(needed_entries) != len(original.needed)
        or len(string_tables) != 1
        or len(string_sizes) != 1
        or string_sizes[0] > MAX_STRING_TABLE_BYTES
    ):
        raise ClosureError(f"ambiguous DT_NEEDED normalization is forbidden: {label}")
    string_table_offset = None
    for virtual, file_size, file_offset in loads:
        relative_string_offset = string_tables[0] - virtual
        if (
            0 <= relative_string_offset < file_size
            and string_sizes[0] <= file_size - relative_string_offset
        ):
            string_table_offset = file_offset + relative_string_offset
            break
    if string_table_offset is None:
        raise ClosureError(f"DT_NEEDED string table is unmapped: {label}")
    changed = False
    for (entry_offset, string_offset), expected_value in zip(
        needed_entries, original.needed, strict=True
    ):
        if string_offset >= string_sizes[0]:
            raise ClosureError(f"DT_NEEDED string offset escapes table: {label}")
        maximum = string_sizes[0] - string_offset
        data = os.pread(descriptor, maximum, string_table_offset + string_offset)
        terminator = data.find(b"\x00")
        if terminator < 0:
            raise ClosureError(f"unterminated DT_NEEDED string: {label}")
        try:
            actual_value = data[:terminator].decode("ascii")
        except UnicodeDecodeError as error:
            raise ClosureError(f"non-ASCII DT_NEEDED string: {label}") from error
        if actual_value != expected_value:
            raise ClosureError(f"DT_NEEDED changed before normalization: {label}")
        if "/" not in actual_value:
            continue
        basename_offset = actual_value.rfind("/") + 1
        new_string_offset = string_offset + basename_offset
        _pwrite_patch(
            descriptor,
            entry_offset + 8,
            struct.pack("<Q", new_string_offset),
            patches,
            label,
        )
        changed = True
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ClosureError(f"ELF identity changed during DT_NEEDED normalization: {label}")
    return changed


def _normalize_runpath_descriptor(
    descriptor: int,
    label: str,
    expected: str,
    patches: list[tuple[int, bytes]] | None = None,
) -> bool:
    before = os.fstat(descriptor)
    header = _pread_exact(descriptor, 64, 0, label)
    if header[:7] != b"\x7fELF\x02\x01\x01":
        raise ClosureError(f"cannot normalize non-ELF runtime file: {label}")
    program_offset = struct.unpack_from("<Q", header, 32)[0]
    program_entry_size = struct.unpack_from("<H", header, 54)[0]
    program_count = struct.unpack_from("<H", header, 56)[0]
    if program_count > 4096 or not 56 <= program_entry_size <= 256:
        raise ClosureError(f"invalid ELF program headers during RUNPATH normalization: {label}")
    dynamic_segment = None
    loads = []
    for index in range(program_count):
        raw = _pread_exact(
            descriptor,
            program_entry_size,
            program_offset + index * program_entry_size,
            label,
        )
        segment_type, _flags, offset, virtual, _physical, file_size, _memory, _align = (
            struct.unpack_from("<IIQQQQQQ", raw)
        )
        if segment_type == 1:
            loads.append((virtual, file_size, offset))
        elif segment_type == 2:
            if dynamic_segment is not None:
                raise ClosureError(f"multiple ELF dynamic segments during normalization: {label}")
            dynamic_segment = (offset, file_size)
    if dynamic_segment is None or dynamic_segment[1] > MAX_DYNAMIC_BYTES or dynamic_segment[1] % 16:
        raise ClosureError(f"invalid ELF dynamic segment during normalization: {label}")
    path_entries = []
    string_tables = []
    string_sizes = []
    terminated = False
    for relative_offset in range(0, dynamic_segment[1], 16):
        entry_offset = dynamic_segment[0] + relative_offset
        tag, value = struct.unpack(
            "<qQ", _pread_exact(descriptor, 16, entry_offset, label)
        )
        if tag == 0:
            terminated = True
            break
        if tag in (15, 29):
            path_entries.append((tag, entry_offset, value))
        elif tag == 5:
            string_tables.append(value)
        elif tag == 10:
            string_sizes.append(value)
    if (
        not terminated
        or len(path_entries) != 1
        or len(string_tables) != 1
        or len(string_sizes) != 1
        or string_sizes[0] > MAX_STRING_TABLE_BYTES
    ):
        raise ClosureError(f"ambiguous ELF RUNPATH normalization is forbidden: {label}")
    path_tag, tag_offset, path_string_offset = path_entries[0]
    string_table_offset = None
    for virtual, file_size, file_offset in loads:
        relative_string_offset = string_tables[0] - virtual
        if (
            0 <= relative_string_offset < file_size
            and string_sizes[0] <= file_size - relative_string_offset
        ):
            string_table_offset = file_offset + relative_string_offset
            break
    if string_table_offset is None or path_string_offset >= string_sizes[0]:
        raise ClosureError(f"ELF RUNPATH string table is unmapped: {label}")
    maximum = string_sizes[0] - path_string_offset
    current_bytes = os.pread(
        descriptor,
        maximum,
        string_table_offset + path_string_offset,
    )
    terminator = current_bytes.find(b"\x00")
    if terminator < 0:
        raise ClosureError(f"unterminated ELF RUNPATH string: {label}")
    try:
        current = current_bytes[:terminator].decode("ascii")
    except UnicodeDecodeError as error:
        raise ClosureError(f"non-ASCII ELF RUNPATH string: {label}") from error
    if len(expected) > len(current):
        raise ClosureError(
            f"ELF RUNPATH slot is too short for central-lib path: {label}"
        )
    padding = len(current) - len(expected)
    normalized = expected + "/." * (padding // 2) + ("/" if padding % 2 else "")
    if len(normalized) != len(current):
        raise ClosureError(f"could not preserve ELF RUNPATH string size: {label}")
    changed = normalized != current or path_tag == 15
    if normalized != current:
        encoded = normalized.encode("ascii")
        _pwrite_patch(
            descriptor,
            string_table_offset + path_string_offset,
            encoded,
            patches,
            label,
        )
    if path_tag == 15:
        _pwrite_patch(
            descriptor,
            tag_offset,
            struct.pack("<q", 29),
            patches,
            label,
        )
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ClosureError(f"ELF identity changed during RUNPATH normalization: {label}")
    return changed


def _normalize_relative_parts(parts: Iterable[str], label: str) -> list[str]:
    normalized: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized:
                raise ClosureError(f"{label} escapes its anchored root")
            normalized.pop()
        else:
            normalized.append(part)
    if not normalized:
        raise ClosureError(f"{label} does not name a regular file")
    return normalized


def _open_anchored_regular(
    root_descriptor: int, relative: str, *, writable: bool = False
) -> tuple[int, str]:
    pending = list(PurePosixPath(_relative_path(relative)).parts)
    hops = 0
    while True:
        current = os.dup(root_descriptor)
        resolved: list[str] = []
        restart = False
        try:
            for index, part in enumerate(pending):
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
                remaining = pending[index + 1 :]
                if stat.S_ISLNK(metadata.st_mode):
                    hops += 1
                    if hops > 40:
                        raise ClosureError(f"anchored symlink resolution exceeds limit: {relative}")
                    target = os.readlink(part, dir_fd=current)
                    if os.path.isabs(target):
                        raise ClosureError(f"anchored runtime symlink is absolute: {relative}")
                    pending = _normalize_relative_parts(
                        [*resolved, *PurePosixPath(target).parts, *remaining],
                        f"runtime symlink {relative}",
                    )
                    restart = True
                    break
                if remaining:
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise ClosureError(f"runtime path traverses non-directory: {relative}")
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=current,
                    )
                    os.close(current)
                    current = child
                    resolved.append(part)
                    continue
                if not stat.S_ISREG(metadata.st_mode):
                    raise ClosureError(f"anchored runtime source is not regular: {relative}")
                descriptor = os.open(
                    part,
                    (os.O_RDWR if writable else os.O_RDONLY)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=current,
                )
                if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(metadata):
                    os.close(descriptor)
                    raise ClosureError(f"runtime path was replaced during open: {relative}")
                return descriptor, "/".join([*resolved, part])
        finally:
            os.close(current)
        if not restart:
            raise ClosureError(f"could not resolve anchored runtime path: {relative}")


def _anchored_lstat(
    root_descriptor: int, relative: str
) -> tuple[os.stat_result, str | None]:
    parts = PurePosixPath(_relative_path(relative)).parts
    current = os.dup(root_descriptor)
    try:
        for part in parts[:-1]:
            metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ClosureError(
                    f"runtime path parent is not an anchored directory: {relative}"
                )
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            os.close(current)
            current = child
        metadata = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
        target = None
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(parts[-1], dir_fd=current)
            after = os.stat(parts[-1], dir_fd=current, follow_symlinks=False)
            if _snapshot_identity(after) != _snapshot_identity(metadata):
                raise ClosureError(f"runtime symlink changed while inspected: {relative}")
        return metadata, target
    finally:
        os.close(current)


@contextlib.contextmanager
def _held_root(root: Path, *, require_unchanged: bool = True):
    descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    before = os.fstat(descriptor)
    try:
        yield descriptor
        if require_unchanged and _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(before):
            raise ClosureError(f"anchored runtime root changed during inspection: {root}")
    finally:
        os.close(descriptor)


def _walk_regular_files(root: Path) -> Iterable[tuple[str, Path]]:
    count = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names.sort(key=lambda value: os.fsencode(value))
        file_names.sort(key=lambda value: os.fsencode(value))
        base = Path(directory)
        for name in file_names:
            path = base / name
            if path.is_symlink():
                continue
            relative = _relative_path(path.relative_to(root).as_posix())
            count += 1
            if count > MAX_FILES:
                raise ClosureError("runtime file count exceeds policy limit")
            yield relative, path


def _scan_elf(root: Path, architecture: str) -> tuple[dict[str, ElfInfo], dict[str, str]]:
    if architecture not in ARCHITECTURES:
        raise ClosureError(f"unsupported Linux architecture: {architecture!r}")
    expected_machine = int(ARCHITECTURES[architecture]["machine"])
    infos: dict[str, ElfInfo] = {}
    digests: dict[str, str] = {}
    entry_count = 0

    def scan_directory(descriptor: int, prefix: str) -> None:
        nonlocal entry_count
        before = os.fstat(descriptor)
        names = os.listdir(descriptor)
        names.sort(key=os.fsencode)
        for name in names:
            entry_count += 1
            if entry_count > MAX_FILES:
                raise ClosureError("runtime file count exceeds policy limit")
            relative = _relative_path(f"{prefix}/{name}" if prefix else name)
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    scan_directory(child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    if _snapshot_identity(os.fstat(child)) != _snapshot_identity(metadata):
                        raise ClosureError(f"runtime ELF path changed during open: {relative}")
                    info = parse_elf(child, relative)
                    if info is None:
                        continue
                    if info.machine != expected_machine:
                        raise ClosureError(
                            f"ELF architecture mismatch for {relative}: "
                            f"{info.machine} != {expected_machine}"
                        )
                    infos[relative] = info
                    digests[relative] = _hash_regular(child)[1]
                finally:
                    os.close(child)
            elif not stat.S_ISLNK(metadata.st_mode):
                raise ClosureError(f"special file in runtime prefix: {relative}")
        if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(before):
            raise ClosureError(f"runtime directory changed during ELF scan: {prefix or '.'}")

    with _held_root(root) as root_descriptor:
        scan_directory(root_descriptor, "")
    return infos, digests


def _origin_directories(root: Path, info: ElfInfo) -> tuple[Path, ...]:
    if info.rpath:
        raise ClosureError(f"legacy DT_RPATH is forbidden: {info.relative_path}")
    directories: list[Path] = []
    origin = root / PurePosixPath(info.relative_path).parent
    for component in info.runpath:
        if not component:
            raise ClosureError(f"empty RUNPATH component: {info.relative_path}")
        marker = None
        for candidate in ("$ORIGIN", "${ORIGIN}"):
            if component == candidate or component.startswith(candidate + "/"):
                marker = candidate
                break
        if marker is None or "$" in component[len(marker) :]:
            raise ClosureError(
                f"RUNPATH is not package-relative in {info.relative_path}: {component}"
            )
        suffix = component[len(marker) :].lstrip("/")
        candidate_path = (origin / suffix).resolve(strict=False)
        if not _is_within(candidate_path, root):
            raise ClosureError(
                f"RUNPATH escapes packaged prefix in {info.relative_path}: {component}"
            )
        directories.append(candidate_path)
    return tuple(directories)


def _reserved_system_shadow_issues(
    root: Path, architecture: str
) -> set[str]:
    reserved = {
        unicodedata.normalize("NFKC", value).casefold(): value
        for value in ARCHITECTURES[architecture]["system_abi"]
    }
    issues: set[str] = set()

    def check_name(relative: str, name: str, context: str) -> None:
        normalized = unicodedata.normalize("NFKC", name).casefold()
        if normalized in reserved:
            issues.add(
                f"payload {context} shadows approved system ABI "
                f"{reserved[normalized]}: {relative}"
            )

    def scan_directory(descriptor: int, prefix: str) -> None:
        before = os.fstat(descriptor)
        names = os.listdir(descriptor)
        names.sort(key=os.fsencode)
        for name in names:
            relative = _relative_path(f"{prefix}/{name}" if prefix else name)
            check_name(relative, name, "entry basename")
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    scan_directory(child, relative)
                finally:
                    os.close(child)
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(name, dir_fd=descriptor)
                target_parts = PurePosixPath(target).parts
                if os.path.isabs(target):
                    normalized_parts = [part for part in target_parts if part != "/"]
                else:
                    try:
                        normalized_parts = _normalize_relative_parts(
                            [
                                *PurePosixPath(relative).parent.parts,
                                *target_parts,
                            ],
                            f"payload symlink {relative}",
                        )
                    except ClosureError:
                        normalized_parts = list(target_parts)
                if normalized_parts:
                    check_name(
                        relative,
                        normalized_parts[-1],
                        "symlink target",
                    )
        if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(before):
            raise ClosureError(
                f"runtime directory changed during system shadow scan: {prefix or '.'}"
            )

    with _held_root(root) as root_descriptor:
        scan_directory(root_descriptor, "")
    return issues


def audit_runtime_closure(root_value: str | Path, architecture: str) -> ClosureReport:
    root = _canonical_directory(root_value, "staged prefix")
    infos, digests = _scan_elf(root, architecture)
    system_abi = set(ARCHITECTURES[architecture]["system_abi"])
    issues = _reserved_system_shadow_issues(root, architecture)

    definitions: dict[str, list[str]] = defaultdict(list)
    for relative, info in infos.items():
        definitions[PurePosixPath(relative).name].append(relative)
        if info.soname:
            definitions[info.soname].append(relative)
    for name, paths in definitions.items():
        normalized_name = unicodedata.normalize("NFKC", name).casefold()
        reserved_names = {
            unicodedata.normalize("NFKC", value).casefold()
            for value in system_abi
        }
        if normalized_name in reserved_names:
            issues.add(
                f"packaged ELF shadows approved system ABI {name}: "
                + ", ".join(sorted(set(paths)))
            )
        central_paths = [
            path
            for path in paths
            if PurePosixPath(path).parent == PurePosixPath("lib")
        ]
        collision_paths = central_paths if central_paths else paths[:1]
        identities = {digests[path] for path in collision_paths}
        if len(identities) > 1:
            issues.add(
                f"conflicting central ELF definitions for {name}: "
                f"{', '.join(sorted(set(collision_paths)))}"
            )

    allowed_interpreters = set(ARCHITECTURES[architecture]["interpreters"])
    for relative, info in infos.items():
        if info.interpreter and info.interpreter not in allowed_interpreters:
            issues.add(f"unapproved ELF interpreter in {relative}: {info.interpreter}")
        try:
            search_directories = _origin_directories(root, info)
        except ClosureError as error:
            issues.add(str(error))
            search_directories = ()
        if info.dynamic and info.needed:
            central_library = (root / "lib").resolve(strict=False)
            if central_library not in search_directories:
                issues.add(
                    f"RUNPATH does not resolve to central package lib in {relative}"
                )
            for directory in search_directories:
                if directory != central_library:
                    issues.add(
                        f"RUNPATH resolves outside central package lib in {relative}: "
                        f"{directory.relative_to(root)}"
                    )
        for needed in info.needed:
            if (
                not needed
                or PurePosixPath(needed).name != needed
                or not needed.isascii()
            ):
                issues.add(f"unsafe DT_NEEDED in {relative}: {needed!r}")
                continue
            if needed in system_abi:
                continue
            resolved = False
            for directory in search_directories:
                candidate = directory / needed
                if not os.path.lexists(candidate):
                    continue
                try:
                    target = candidate.resolve(strict=True)
                except OSError:
                    continue
                if not _is_within(target, root) or not target.is_file():
                    issues.add(f"dependency path escapes packaged prefix: {relative} -> {needed}")
                    resolved = True
                    break
                target_info = parse_elf(target, target.relative_to(root).as_posix())
                if target_info is None:
                    issues.add(f"dependency is not ELF: {relative} -> {needed}")
                resolved = True
                break
            if not resolved:
                issues.add(f"unresolved dependency: {relative} -> {needed}")

    ordered_infos = tuple(infos[path] for path in sorted(infos, key=lambda p: p.encode("utf-8")))
    return ClosureReport(
        len(ordered_infos),
        sum(info.dynamic for info in ordered_infos),
        tuple(sorted(issues)),
        ordered_infos,
    )


def _raise_report(report: ClosureReport) -> None:
    if not report.issues:
        return
    shown = report.issues[:200]
    detail = "\n".join(f"- {issue}" for issue in shown)
    if len(report.issues) > len(shown):
        detail += f"\n- ... {len(report.issues) - len(shown)} more issue(s)"
    raise ClosureError(f"Linux runtime closure verification failed:\n{detail}")


def _validate_manifest_file(
    root: Path, root_descriptor: int, record: object
) -> str:
    if not isinstance(record, dict) or record.get("type") not in ("file", "symlink"):
        raise ClosureError("runtime manifest file record has invalid fields")
    if record["type"] == "file":
        expected_fields = {
            "mode",
            "needed_normalized",
            "package",
            "path",
            "runpath_normalized",
            "sha256",
            "size",
            "source_sha256",
            "source_path",
            "type",
        }
    else:
        expected_fields = {
            "package",
            "path",
            "source_path",
            "target",
            "type",
        }
    if set(record) != expected_fields:
        raise ClosureError("runtime manifest file record has invalid fields")
    relative = _relative_path(record["path"])
    _relative_path(record["source_path"])
    package = record["package"]
    if not isinstance(package, dict) or set(package) != {
        "build",
        "license",
        "name",
        "sha256",
        "subdir",
        "url",
        "version",
    }:
        raise ClosureError(f"runtime package provenance is invalid: {relative}")
    if any(not isinstance(package[key], str) or not package[key] for key in package):
        raise ClosureError(f"runtime package provenance is empty: {relative}")
    if not SHA256_RE.fullmatch(package["sha256"]):
        raise ClosureError(f"runtime package SHA-256 is invalid: {relative}")
    if record["type"] == "symlink":
        target = record["target"]
        if not isinstance(target, str) or not target or os.path.isabs(target):
            raise ClosureError(f"runtime manifest symlink target is invalid: {relative}")
        _normalize_relative_parts(
            [*PurePosixPath(relative).parent.parts, *PurePosixPath(target).parts],
            f"runtime manifest symlink {relative}",
        )
        metadata, actual_target = _anchored_lstat(root_descriptor, relative)
        if not stat.S_ISLNK(metadata.st_mode) or actual_target != target:
            raise ClosureError(f"runtime manifest symlink mismatch: {relative}")
    else:
        if not isinstance(record["size"], int) or isinstance(record["size"], bool):
            raise ClosureError(f"runtime manifest size is invalid: {relative}")
        if record["mode"] not in (0o644, 0o755) or not SHA256_RE.fullmatch(
            record["sha256"]
        ):
            raise ClosureError(f"runtime manifest identity is invalid: {relative}")
        if (
            not isinstance(record["runpath_normalized"], bool)
            or not isinstance(record["needed_normalized"], bool)
            or not SHA256_RE.fullmatch(record["source_sha256"])
            or (
                (
                    record["runpath_normalized"]
                    or record["needed_normalized"]
                )
                and record["source_sha256"] == record["sha256"]
            )
            or (
                not record["runpath_normalized"]
                and not record["needed_normalized"]
                and record["source_sha256"] != record["sha256"]
            )
        ):
            raise ClosureError(
                f"runtime source/transformation identity is invalid: {relative}"
            )
        try:
            descriptor, _resolved = _open_anchored_regular(root_descriptor, relative)
        except OSError as error:
            raise ClosureError(f"runtime manifest file is missing: {relative}") from error
        try:
            metadata = os.fstat(descriptor)
            size, digest = _hash_regular(descriptor)
            if size != record["size"] or digest != record["sha256"]:
                raise ClosureError(f"runtime manifest file identity mismatch: {relative}")
            if stat.S_IMODE(metadata.st_mode) != record["mode"]:
                raise ClosureError(f"runtime manifest file mode mismatch: {relative}")
        finally:
            os.close(descriptor)
    return relative


def _managed_tree_entries(root: Path, roots: Sequence[str]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    aliases: dict[str, str] = {}
    entry_count = 0

    def append_record(relative: str, record: dict[str, object]) -> None:
        nonlocal entry_count
        entry_count += 1
        if entry_count > MAX_FILES:
            raise ClosureError("managed runtime entry count exceeds policy limit")
        relative = _relative_path(relative)
        record["path"] = relative
        alias = _alias_key(relative)
        if alias in aliases and aliases[alias] != relative:
            raise ClosureError(f"managed runtime path alias collision: {relative}")
        aliases[alias] = relative
        records.append(record)

    def scan_directory(descriptor: int, relative: str) -> None:
        before = os.fstat(descriptor)
        append_record(
            relative,
            {
                "mode": stat.S_IMODE(before.st_mode),
                "type": "directory",
            },
        )
        names = os.listdir(descriptor)
        names.sort(key=os.fsencode)
        if len(names) > MAX_FILES:
            raise ClosureError(f"managed runtime directory is too large: {relative}")
        for name in names:
            if not isinstance(name, str) or name in ("", ".", "..") or "/" in name:
                raise ClosureError(f"invalid managed runtime directory entry: {relative}")
            child_relative = f"{relative}/{name}"
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    scan_directory(child, child_relative)
                finally:
                    os.close(child)
            elif stat.S_ISREG(metadata.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
                try:
                    if _snapshot_identity(os.fstat(child)) != _snapshot_identity(metadata):
                        raise ClosureError(
                            f"managed runtime path changed during open: {child_relative}"
                        )
                    size, digest = _hash_regular(child)
                finally:
                    os.close(child)
                append_record(
                    child_relative,
                    {
                        "mode": stat.S_IMODE(metadata.st_mode),
                        "sha256": digest,
                        "size": size,
                        "type": "file",
                    },
                )
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(name, dir_fd=descriptor)
                if os.path.isabs(target):
                    raise ClosureError(
                        f"absolute managed runtime symlink: {child_relative}"
                    )
                append_record(
                    child_relative,
                    {"target": target, "type": "symlink"},
                )
            else:
                raise ClosureError(
                    f"special file in managed runtime tree: {child_relative}"
                )
        if _snapshot_identity(os.fstat(descriptor)) != _snapshot_identity(before):
            raise ClosureError(f"managed runtime directory changed: {relative}")

    with _held_root(root) as root_descriptor:
        for managed_root in roots:
            managed_root = _relative_path(managed_root)
            current = os.dup(root_descriptor)
            try:
                for part in PurePosixPath(managed_root).parts:
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=current,
                    )
                    os.close(current)
                    current = child
                scan_directory(current, managed_root)
            finally:
                os.close(current)
    records.sort(key=lambda record: str(record["path"]).encode("utf-8"))
    return records


def verify_runtime_closure(
    root_value: str | Path,
    architecture: str,
    *,
    allow_static_without_manifest: bool = False,
    expected_dependency_lock_sha256: str | None = None,
) -> ClosureReport:
    root = _canonical_directory(root_value, "staged prefix")
    report = audit_runtime_closure(root, architecture)
    _raise_report(report)
    manifest_path = root.joinpath(*PurePosixPath(MANIFEST_RELATIVE_PATH).parts)
    if report.dynamic_elf_count == 0 and allow_static_without_manifest and not manifest_path.exists():
        return report
    with _held_root(root) as root_descriptor:
        content = _read_anchored_bounded(
            root_descriptor,
            MANIFEST_RELATIVE_PATH,
            MAX_MANIFEST_BYTES,
            "runtime closure manifest",
        )
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ClosureError("runtime closure manifest is not canonical JSON") from error
    if _canonical_json(manifest) != content or not isinstance(manifest, dict):
        raise ClosureError("runtime closure manifest is not canonical")
    if set(manifest) != {
        "architecture",
        "dependency_lock_sha256",
        "elf",
        "files",
        "format_version",
        "managed_entries",
        "managed_roots",
        "python_prefix",
        "selected_packages",
        "stage_transformations",
        "system_abi",
    }:
        raise ClosureError("runtime closure manifest has invalid fields")
    if manifest["format_version"] != FORMAT_VERSION or manifest["architecture"] != architecture:
        raise ClosureError("runtime closure manifest coordinates do not match payload")
    if not isinstance(manifest["dependency_lock_sha256"], str) or not SHA256_RE.fullmatch(
        manifest["dependency_lock_sha256"]
    ):
        raise ClosureError("runtime closure manifest lock identity is invalid")
    if expected_dependency_lock_sha256 is not None and (
        not SHA256_RE.fullmatch(expected_dependency_lock_sha256)
        or manifest["dependency_lock_sha256"] != expected_dependency_lock_sha256
    ):
        raise ClosureError(
            "runtime closure dependency lock does not match signed executable identity"
        )
    if manifest["system_abi"] != list(ARCHITECTURES[architecture]["system_abi"]):
        raise ClosureError("runtime closure system ABI allowlist is not canonical")
    expected_elf = [info.manifest_record() for info in report.elf]
    if manifest["elf"] != expected_elf:
        raise ClosureError("runtime closure ELF graph does not match payload")
    transformations = manifest["stage_transformations"]
    if not isinstance(transformations, list):
        raise ClosureError("staged ELF transformation inventory is invalid")
    transformation_paths = []
    with _held_root(root) as root_descriptor:
        for record in transformations:
            if not isinstance(record, dict) or set(record) != {
                "needed_normalized",
                "path",
                "runpath_normalized",
                "sha256",
                "source_sha256",
            }:
                raise ClosureError("staged ELF transformation record is invalid")
            relative = _relative_path(record["path"])
            if (
                not isinstance(record["needed_normalized"], bool)
                or not isinstance(record["runpath_normalized"], bool)
                or not (
                    record["needed_normalized"] or record["runpath_normalized"]
                )
                or not SHA256_RE.fullmatch(record["sha256"])
                or not SHA256_RE.fullmatch(record["source_sha256"])
                or record["sha256"] == record["source_sha256"]
            ):
                raise ClosureError(
                    f"staged ELF transformation identity is invalid: {relative}"
                )
            descriptor, _resolved = _open_anchored_regular(
                root_descriptor, relative
            )
            try:
                if _hash_regular(descriptor)[1] != record["sha256"]:
                    raise ClosureError(
                        f"staged ELF transformation digest mismatch: {relative}"
                    )
            finally:
                os.close(descriptor)
            transformation_paths.append(relative)
    if (
        transformation_paths
        != sorted(transformation_paths, key=lambda value: value.encode("utf-8"))
        or len(transformation_paths) != len(set(transformation_paths))
        or not set(transformation_paths).issubset(
            {info.relative_path for info in report.elf}
        )
    ):
        raise ClosureError("staged ELF transformations are not unique and sorted")
    if not isinstance(manifest["files"], list):
        raise ClosureError("runtime closure file inventory is invalid")
    with _held_root(root) as root_descriptor:
        paths = [
            _validate_manifest_file(root, root_descriptor, record)
            for record in manifest["files"]
        ]
    if paths != sorted(paths, key=lambda value: value.encode("utf-8")) or len(paths) != len(set(paths)):
        raise ClosureError("runtime closure file inventory is not unique and sorted")
    selected_packages = manifest["selected_packages"]
    if not isinstance(selected_packages, list):
        raise ClosureError("runtime closure selected-package inventory is invalid")
    package_records = []
    for package in selected_packages:
        if not isinstance(package, dict) or set(package) != {
            "build",
            "depends",
            "files",
            "license",
            "name",
            "sha256",
            "subdir",
            "url",
            "version",
        }:
            raise ClosureError("runtime closure selected-package record is invalid")
        scalar_keys = (
            "build",
            "license",
            "name",
            "sha256",
            "subdir",
            "url",
            "version",
        )
        if any(not isinstance(package[key], str) or not package[key] for key in scalar_keys):
            raise ClosureError("runtime closure selected-package provenance is empty")
        if (
            not isinstance(package["depends"], list)
            or any(not isinstance(value, str) or not value for value in package["depends"])
            or not isinstance(package["files"], list)
            or any(not isinstance(value, str) for value in package["files"])
        ):
            raise ClosureError("runtime closure selected-package inventory is invalid")
        package["files"] = [_relative_path(value) for value in package["files"]]
        if not SHA256_RE.fullmatch(package["sha256"]):
            raise ClosureError("runtime closure selected-package SHA-256 is invalid")
        package_records.append(package)
    if package_records != sorted(
        package_records,
        key=lambda package: (
            package["name"],
            package["version"],
            package["build"],
            package["subdir"],
        ),
    ) or len({package["name"] for package in package_records}) != len(package_records):
        raise ClosureError("runtime closure selected packages are not unique and sorted")
    file_packages = {
        (record["package"]["name"], record["package"]["sha256"])
        for record in manifest["files"]
    }
    selected_identities = {
        (package["name"], package["sha256"]) for package in package_records
    }
    if not file_packages.issubset(selected_identities):
        raise ClosureError("runtime file provenance is absent from selected packages")
    selected_names = {package["name"] for package in package_records}
    expected_owners: dict[str, str] = {}
    for package in package_records:
        for relative in package["files"]:
            if relative in expected_owners:
                raise ClosureError(
                    f"selected packages claim the same runtime path: {relative}"
                )
            expected_owners[relative] = package["name"]
        for specification in package["depends"]:
            name = specification.split(maxsplit=1)[0]
            if not name.startswith("__") and name not in selected_names:
                raise ClosureError(
                    f"selected package dependency closure is incomplete: "
                    f"{package['name']} -> {name}"
                )
    actual_owners = {
        record["source_path"]: record["package"]["name"]
        for record in manifest["files"]
    }
    if actual_owners != expected_owners:
        raise ClosureError("selected package file ownership is not exhaustive")
    python_prefix = manifest["python_prefix"]
    if not isinstance(python_prefix, str) or not re.fullmatch(r"lib/python3\.[0-9]+", python_prefix):
        raise ClosureError("runtime closure Python prefix is invalid")
    required = {
        f"{python_prefix}/encodings/__init__.py",
        "lib/qt6/plugins/platforms/libqxcb.so",
    }
    file_types = {record["path"]: record["type"] for record in manifest["files"]}
    missing_runtime = sorted(
        relative for relative in required if file_types.get(relative) != "file"
    )
    if missing_runtime:
        raise ClosureError(
            "runtime closure omits required Python/Qt runtime files: "
            + ", ".join(missing_runtime)
        )
    managed_roots = manifest["managed_roots"]
    if (
        not isinstance(managed_roots, list)
        or any(not isinstance(value, str) for value in managed_roots)
        or managed_roots != sorted(set(managed_roots), key=lambda value: value.encode("utf-8"))
    ):
        raise ClosureError("managed runtime roots are not unique and sorted")
    managed_entries = _managed_tree_entries(root, managed_roots)
    if manifest["managed_entries"] != managed_entries:
        raise ClosureError("managed runtime tree contains unmanifested or changed entries")
    return report


def _source_file(prefix: Path, relative: str) -> Path:
    with _held_root(prefix) as root_descriptor:
        try:
            descriptor, resolved_relative = _open_anchored_regular(
                root_descriptor, relative
            )
        except OSError as error:
            raise ClosureError(f"locked runtime source is missing: {relative}") from error
        try:
            _hash_regular(descriptor)
        finally:
            os.close(descriptor)
    return prefix.joinpath(*PurePosixPath(resolved_relative).parts)


def _inspect_source(
    prefix: Path, relative: str, destination: str
) -> tuple[Path, ElfInfo | None, str, str | None]:
    with _held_root(prefix) as root_descriptor:
        metadata, target = _anchored_lstat(root_descriptor, relative)
        if stat.S_ISLNK(metadata.st_mode):
            assert target is not None
            if os.path.isabs(target):
                raise ClosureError(f"locked runtime symlink is absolute: {relative}")
            _normalize_relative_parts(
                [
                    *PurePosixPath(relative).parent.parts,
                    *PurePosixPath(target).parts,
                ],
                f"locked runtime symlink {relative}",
            )
            return prefix.joinpath(*PurePosixPath(relative).parts), None, "symlink", target
        if not stat.S_ISREG(metadata.st_mode):
            raise ClosureError(f"locked package entry is not file or symlink: {relative}")
        descriptor, resolved_relative = _open_anchored_regular(
            root_descriptor, relative
        )
        try:
            info = parse_elf(descriptor, destination)
            _hash_regular(descriptor)
        finally:
            os.close(descriptor)
    return (
        prefix.joinpath(*PurePosixPath(resolved_relative).parts),
        info,
        "file",
        None,
    )


def _yaml_scalar(value: str, label: str) -> str | None:
    value = value.strip()
    if value in ("", "null", "~"):
        return None
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ClosureError(f"invalid quoted YAML scalar for {label}") from error
        if not isinstance(decoded, str):
            raise ClosureError(f"non-string YAML scalar for {label}")
        return decoded
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ClosureError(f"invalid quoted YAML scalar for {label}")
        return value[1:-1].replace("''", "'")
    if " #" in value or value[0] in "[{&*!|>@`":
        raise ClosureError(f"unsupported YAML scalar for {label}")
    return value


def _parse_pixi_lock(content: bytes) -> dict[str, LockedPackage]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ClosureError("pixi.lock is not UTF-8") from error
    lines = text.splitlines()
    if "version: 6" not in lines:
        raise ClosureError("unsupported pixi.lock format version")
    try:
        start = lines.index("packages:") + 1
    except ValueError as error:
        raise ClosureError("pixi.lock has no top-level packages index") from error
    result: dict[str, LockedPackage] = {}
    current_url: str | None = None
    current_sha256: str | None = None
    current_license: str | None = None

    def finish() -> None:
        nonlocal current_url, current_sha256, current_license
        if current_url is not None:
            if current_sha256 is None or not SHA256_RE.fullmatch(current_sha256):
                raise ClosureError(f"locked conda package lacks SHA-256: {current_url}")
            record = LockedPackage(current_url, current_sha256, current_license)
            previous = result.get(current_url)
            if previous is not None and previous != record:
                raise ClosureError(f"conflicting pixi.lock package records: {current_url}")
            result[current_url] = record
        current_url = None
        current_sha256 = None
        current_license = None

    for line in lines[start:]:
        if line.startswith("- "):
            finish()
            if line.startswith("- conda: "):
                scalar = _yaml_scalar(line[len("- conda: ") :], "conda URL")
                if not scalar:
                    raise ClosureError("pixi.lock contains an empty conda URL")
                current_url = scalar
            continue
        if line and not line.startswith(" "):
            finish()
            break
        if current_url is None:
            continue
        if line.startswith("  sha256: "):
            scalar = _yaml_scalar(line[len("  sha256: ") :], "package SHA-256")
            if current_sha256 is not None or scalar is None:
                raise ClosureError(f"duplicate/empty package SHA-256: {current_url}")
            current_sha256 = scalar
        elif line.startswith("  license: "):
            if current_license is not None:
                raise ClosureError(f"duplicate package license: {current_url}")
            current_license = _yaml_scalar(
                line[len("  license: ") :], "package license"
            )
    else:
        finish()
    if not result:
        raise ClosureError("pixi.lock contains no conda package records")
    return result


def _bind_package_url(value: dict[str, object], url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ClosureError(f"locked package URL is not canonical HTTPS: {url}")
    components = PurePosixPath(parsed.path).parts
    if len(components) < 2 or components[-2] != value["subdir"]:
        raise ClosureError(f"locked package URL subdir mismatch: {url}")
    expected_stem = f"{value['name']}-{value['version']}-{value['build']}"
    if components[-1] not in (expected_stem + ".conda", expected_stem + ".tar.bz2"):
        raise ClosureError(f"locked package URL coordinates mismatch: {url}")


def _load_packages(
    prefix: Path, lock_path: Path, architecture: str
) -> tuple[dict[str, PackageRecord], dict[str, PackageRecord], str]:
    lock = _read_bounded(lock_path, MAX_LOCK_BYTES, "pixi dependency lock")
    lock_digest = hashlib.sha256(lock).hexdigest()
    locked_packages = _parse_pixi_lock(lock)
    license_overrides, _license_files = _license_provenance()
    owners: dict[str, PackageRecord] = {}
    packages_by_name: dict[str, PackageRecord] = {}
    expected_subdir = str(ARCHITECTURES[architecture]["subdir"])
    with _held_root(prefix) as root_descriptor:
        metadata_descriptor = os.open(
            "conda-meta",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        metadata_snapshot = os.fstat(metadata_descriptor)
        try:
            metadata_names = sorted(
                (
                    name
                    for name in os.listdir(metadata_descriptor)
                    if isinstance(name, str) and name.endswith(".json")
                ),
                key=os.fsencode,
            )
        finally:
            os.close(metadata_descriptor)
        package_contents = []
        metadata_total = 0
        for metadata_name in metadata_names:
            content = _read_anchored_bounded(
                root_descriptor,
                f"conda-meta/{metadata_name}",
                MAX_METADATA_BYTES,
                "conda package metadata",
            )
            metadata_total += len(content)
            if metadata_total > MAX_METADATA_TOTAL_BYTES:
                raise ClosureError("aggregate conda metadata exceeds policy limit")
            package_contents.append((metadata_name, content))
        reopened_metadata = os.open(
            "conda-meta",
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_descriptor,
        )
        try:
            if _snapshot_identity(os.fstat(reopened_metadata)) != _snapshot_identity(
                metadata_snapshot
            ):
                raise ClosureError("conda-meta changed during inventory")
        finally:
            os.close(reopened_metadata)
    for metadata_name, content in package_contents:
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ClosureError(f"invalid conda package metadata: {metadata_name}") from error
        if not isinstance(value, dict):
            raise ClosureError(f"invalid conda package metadata: {metadata_name}")
        fields = ("name", "version", "build", "subdir", "url", "sha256")
        if any(not isinstance(value.get(key), str) or not value[key] for key in fields):
            raise ClosureError(f"incomplete package provenance: {metadata_name}")
        if value["subdir"] not in ("noarch", expected_subdir):
            continue
        if not SHA256_RE.fullmatch(value["sha256"]):
            raise ClosureError(f"invalid package SHA-256: {metadata_name}")
        locked = locked_packages.get(value["url"])
        if locked is None or locked.sha256 != value["sha256"]:
            raise ClosureError(f"installed package is absent from pixi.lock: {value['name']}")
        _bind_package_url(value, value["url"])
        files_value = value.get("files")
        if not isinstance(files_value, list) or any(not isinstance(item, str) for item in files_value):
            raise ClosureError(f"invalid package file inventory: {metadata_name}")
        files = tuple(_relative_path(item) for item in files_value)
        depends_value = value.get("depends", [])
        if not isinstance(depends_value, list) or any(
            not isinstance(item, str) or not item for item in depends_value
        ):
            raise ClosureError(f"invalid package dependency inventory: {metadata_name}")
        license_value = value.get("license") or locked.license
        override = license_overrides.get(value["url"])
        if override is not None:
            if override[0] != value["sha256"]:
                raise ClosureError(
                    f"license provenance package SHA-256 mismatch: {value['name']}"
                )
            if license_value is None:
                license_value = override[1]
            elif license_value != override[1]:
                raise ClosureError(
                    f"conflicting license provenance: {value['name']}"
                )
        if license_value is not None and (
            not isinstance(license_value, str) or not license_value
        ):
            raise ClosureError(f"invalid package license: {metadata_name}")
        package = PackageRecord(
            value["name"],
            value["version"],
            value["build"],
            value["subdir"],
            value["url"],
            value["sha256"],
            license_value,
            tuple(depends_value),
            files,
        )
        previous_package = packages_by_name.get(package.name)
        if previous_package is not None and previous_package != package:
            raise ClosureError(f"multiple installed records for package: {package.name}")
        packages_by_name[package.name] = package
        for relative in files:
            if relative in owners:
                raise ClosureError(f"multiple locked packages own runtime path: {relative}")
            owners[relative] = package
    if not owners:
        raise ClosureError("locked Pixi prefix has no usable package inventory")
    return owners, packages_by_name, lock_digest


def _candidate_index(
    prefix: Path, owners: dict[str, PackageRecord], architecture: str
) -> dict[str, list[tuple[str, Path, PackageRecord, ElfInfo, str]]]:
    result: dict[str, list[tuple[str, Path, PackageRecord, ElfInfo, str]]] = defaultdict(list)
    machine = int(ARCHITECTURES[architecture]["machine"])
    with _held_root(prefix) as root_descriptor:
        for relative in sorted(owners, key=lambda value: value.encode("utf-8")):
            if not relative.startswith("lib/"):
                continue
            try:
                descriptor, resolved_relative = _open_anchored_regular(
                    root_descriptor, relative
                )
            except (ClosureError, OSError):
                continue
            try:
                info = parse_elf(descriptor, relative)
                if info is None or info.machine != machine:
                    continue
                digest = _hash_regular(descriptor)[1]
            finally:
                os.close(descriptor)
            source = prefix.joinpath(*PurePosixPath(resolved_relative).parts)
            record = (relative, source, owners[relative], info, digest)
            result[PurePosixPath(relative).name].append(record)
            if info.soname:
                result[info.soname].append(record)
    return result


def _choose_candidate(
    name: str,
    candidates: dict[str, list[tuple[str, Path, PackageRecord, ElfInfo, str]]],
) -> tuple[str, Path, PackageRecord, ElfInfo, str]:
    values = candidates.get(name, [])
    if not values:
        raise ClosureError(f"locked Pixi prefix cannot resolve dependency: {name}")
    central_values = [
        value
        for value in values
        if PurePosixPath(value[0]).parent == PurePosixPath("lib")
        and PurePosixPath(value[0]).name == name
    ]
    if central_values:
        values = central_values
    if len({value[4] for value in values}) != 1:
        paths = ", ".join(sorted({value[0] for value in values}))
        raise ClosureError(f"locked dependency collision for {name}: {paths}")
    return min(values, key=lambda value: (PurePosixPath(value[0]).name != name, value[0].encode("utf-8")))


def _ensure_parent(root: Path, relative: str, created_directories: list[Path]) -> Path:
    destination = root.joinpath(*PurePosixPath(relative).parts)
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current /= part
        if os.path.lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise ClosureError(f"runtime destination parent is unsafe: {relative}")
        else:
            current.mkdir(mode=0o755)
            created_directories.append(current)
    return destination


def _open_destination_parent(
    root: Path,
    root_descriptor: int,
    relative: str,
    created_directories: list[Path],
) -> tuple[int, str, Path]:
    parts = PurePosixPath(_relative_path(relative)).parts
    current = os.dup(root_descriptor)
    current_path = root
    try:
        for part in parts[:-1]:
            try:
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(part, 0o755, dir_fd=current)
                current_path = current_path / part
                created_directories.append(current_path)
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            else:
                current_path = current_path / part
            if not stat.S_ISDIR(metadata.st_mode):
                raise ClosureError(f"runtime destination parent is unsafe: {relative}")
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            os.close(current)
            current = child
        return current, parts[-1], root.joinpath(*parts)
    except BaseException:
        os.close(current)
        raise


def _write_anchored_file(
    root: Path,
    root_descriptor: int,
    relative: str,
    content: bytes,
    epoch: int,
    created_files: list[Path],
    created_directories: list[Path],
) -> Path:
    parent, name, destination = _open_destination_parent(
        root, root_descriptor, relative, created_directories
    )
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=parent,
        )
    finally:
        os.close(parent)
    created_files.append(destination)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ClosureError(f"could not write runtime file: {relative}")
            view = view[written:]
        os.fchmod(descriptor, 0o644)
        os.utime(descriptor, (epoch, epoch))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def _restore_stage_patches(
    stage: Path,
    backups: Sequence[tuple[str, tuple[tuple[int, bytes], ...], int, int]],
) -> None:
    if not backups:
        return
    with _held_root(stage, require_unchanged=False) as root_descriptor:
        for relative, patches, atime_ns, mtime_ns in reversed(backups):
            descriptor, _resolved = _open_anchored_regular(
                root_descriptor, relative, writable=True
            )
            try:
                for offset, content in reversed(patches):
                    if os.pwrite(descriptor, content, offset) != len(content):
                        raise ClosureError(
                            f"could not restore staged ELF patch: {relative}"
                        )
                os.utime(descriptor, ns=(atime_ns, mtime_ns))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _normalize_staged_elf(
    stage: Path, architecture: str, epoch: int
) -> tuple[
    list[dict[str, object]],
    list[tuple[str, tuple[tuple[int, bytes], ...], int, int]],
]:
    infos, _digests = _scan_elf(stage, architecture)
    records: list[dict[str, object]] = []
    backups: list[tuple[str, tuple[tuple[int, bytes], ...], int, int]] = []
    try:
        with _held_root(stage, require_unchanged=False) as root_descriptor:
            for relative in sorted(infos, key=lambda value: value.encode("utf-8")):
                info = infos[relative]
                if not info.dynamic:
                    continue
                if info.needed and not (info.rpath or info.runpath):
                    raise ClosureError(
                        f"staged ELF has no normalizable runtime path: {relative}"
                    )
                descriptor, _resolved = _open_anchored_regular(
                    root_descriptor, relative, writable=True
                )
                patches: list[tuple[int, bytes]] = []
                metadata = None
                try:
                    metadata = os.fstat(descriptor)
                    source_sha256 = _hash_regular(descriptor)[1]
                    needed_normalized = _normalize_needed_descriptor(
                        descriptor, relative, info, patches
                    )
                    runpath_normalized = False
                    if info.rpath or info.runpath:
                        runpath_normalized = _normalize_runpath_descriptor(
                            descriptor,
                            relative,
                            _expected_central_runpath(relative),
                            patches,
                        )
                    converted = parse_elf(descriptor, relative)
                    expected_needed = _normalized_needed_info(info).needed
                    central_library = (stage / "lib").resolve(strict=False)
                    if (
                        converted is None
                        or converted.needed != expected_needed
                        or converted.rpath
                        or (
                            converted.needed
                            and (
                                central_library
                                not in _origin_directories(stage, converted)
                                or any(
                                    directory != central_library
                                    for directory in _origin_directories(
                                        stage, converted
                                    )
                                )
                            )
                        )
                    ):
                        raise ClosureError(
                            f"staged ELF normalization did not verify: {relative}"
                        )
                    if patches:
                        destination_sha256 = _hash_regular(descriptor)[1]
                        os.utime(descriptor, (epoch, epoch))
                        os.fsync(descriptor)
                        backups.append(
                            (
                                relative,
                                tuple(patches),
                                metadata.st_atime_ns,
                                metadata.st_mtime_ns,
                            )
                        )
                        records.append(
                            {
                                "needed_normalized": needed_normalized,
                                "path": relative,
                                "runpath_normalized": runpath_normalized,
                                "sha256": destination_sha256,
                                "source_sha256": source_sha256,
                            }
                        )
                except BaseException:
                    for offset, content in reversed(patches):
                        os.pwrite(descriptor, content, offset)
                    if metadata is not None:
                        os.utime(
                            descriptor,
                            ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
                        )
                    os.fsync(descriptor)
                    raise
                finally:
                    os.close(descriptor)
        return records, backups
    except BaseException:
        _restore_stage_patches(stage, backups)
        raise


def _copy_plan(
    root: Path,
    destination_root_descriptor: int,
    source_root_descriptor: int,
    plan: CopyPlan,
    epoch: int,
    created_files: list[Path],
    created_directories: list[Path],
) -> dict[str, object]:
    parent_descriptor, destination_name, destination = _open_destination_parent(
        root, destination_root_descriptor, plan.destination, created_directories
    )
    if plan.kind == "symlink":
        try:
            source_metadata, source_target = _anchored_lstat(
                source_root_descriptor, plan.source_relative_path
            )
            if (
                not stat.S_ISLNK(source_metadata.st_mode)
                or source_target != plan.link_target
                or source_target is None
            ):
                raise ClosureError(
                    f"runtime symlink changed before copy: {plan.source_relative_path}"
                )
            os.symlink(source_target, destination_name, dir_fd=parent_descriptor)
            created_files.append(destination)
            os.utime(
                destination_name,
                (epoch, epoch),
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        finally:
            os.close(parent_descriptor)
        return {
            "package": plan.package.manifest_record(),
            "path": plan.destination,
            "source_path": plan.source_relative_path,
            "target": plan.link_target,
            "type": "symlink",
        }
    if plan.kind != "file":
        os.close(parent_descriptor)
        raise ClosureError(f"unsupported runtime copy-plan type: {plan.kind}")
    try:
        source_descriptor, _resolved_source = _open_anchored_regular(
            source_root_descriptor, plan.source_relative_path
        )
    except BaseException:
        os.close(parent_descriptor)
        raise
    try:
        source_metadata = os.fstat(source_descriptor)
        if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_size > MAX_ELF_BYTES:
            raise ClosureError(f"runtime source is not a bounded regular file: {plan.source}")
        mode = 0o755 if source_metadata.st_mode & 0o111 else 0o644
        try:
            destination_descriptor = os.open(
                destination_name,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=parent_descriptor,
            )
        finally:
            os.close(parent_descriptor)
        created_files.append(destination)
        digest = hashlib.sha256()
        total = 0
        try:
            while True:
                data = os.read(source_descriptor, COPY_CHUNK_BYTES)
                if not data:
                    break
                total += len(data)
                digest.update(data)
                view = memoryview(data)
                while view:
                    written = os.write(destination_descriptor, view)
                    if written <= 0:
                        raise ClosureError(
                            f"could not write runtime destination: {plan.destination}"
                        )
                    view = view[written:]
            os.fchmod(destination_descriptor, mode)
            os.fsync(destination_descriptor)
            source_digest = digest.hexdigest()
            needed_normalized = False
            runpath_normalized = False
            if plan.elf_info is not None:
                needed_normalized = _normalize_needed_descriptor(
                    destination_descriptor,
                    plan.destination,
                    plan.elf_info,
                )
            if plan.elf_info is not None and (
                plan.elf_info.rpath or plan.elf_info.runpath
            ):
                central_library = (root / "lib").resolve(strict=False)
                expected_runpath = _expected_central_runpath(plan.destination)
                runpath_normalized = _normalize_runpath_descriptor(
                    destination_descriptor,
                    plan.destination,
                    expected_runpath,
                )
                converted = parse_elf(destination_descriptor, plan.destination)
                if (
                    converted is None
                    or converted.needed
                    != _normalized_needed_info(plan.elf_info).needed
                    or converted.rpath
                    or central_library
                    not in _origin_directories(root, converted)
                    or any(
                        directory != central_library
                        for directory in _origin_directories(root, converted)
                    )
                ):
                    raise ClosureError(
                        f"RUNPATH normalization did not verify: {plan.destination}"
                    )
            destination_size, destination_digest = _hash_regular(
                destination_descriptor
            )
            os.utime(destination_descriptor, (epoch, epoch))
            os.fsync(destination_descriptor)
        finally:
            os.close(destination_descriptor)
        if total != source_metadata.st_size or _snapshot_identity(
            os.fstat(source_descriptor)
        ) != _snapshot_identity(source_metadata):
            raise ClosureError(f"runtime source changed while being copied: {plan.source}")
        return {
            "mode": mode,
            "needed_normalized": needed_normalized,
            "package": plan.package.manifest_record(),
            "path": plan.destination,
            "runpath_normalized": runpath_normalized,
            "sha256": destination_digest,
            "size": destination_size,
            "source_sha256": source_digest,
            "source_path": plan.source_relative_path,
            "type": "file",
        }
    finally:
        os.close(source_descriptor)


def bundle_runtime(
    stage_value: str | Path,
    pixi_prefix_value: str | Path,
    lock_value: str | Path,
    architecture: str,
    epoch: int,
) -> Path:
    if architecture not in ARCHITECTURES:
        raise ClosureError(f"unsupported Linux architecture: {architecture!r}")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or not 0 <= epoch < (1 << 34):
        raise ClosureError("SOURCE_DATE_EPOCH is invalid")
    stage = _canonical_directory(stage_value, "staged prefix")
    pixi_prefix = _canonical_directory(pixi_prefix_value, "locked Pixi prefix")
    lock_path = Path(lock_value)
    if not lock_path.is_absolute() or lock_path.resolve(strict=True) != lock_path:
        raise ClosureError("pixi.lock must be a canonical absolute path")
    owners, packages_by_name, lock_digest = _load_packages(
        pixi_prefix, lock_path, architecture
    )

    python_package = packages_by_name.get("python")
    if python_package is None:
        raise ClosureError("locked prefix must contain exactly one Python runtime")
    match = re.match(r"(3\.[0-9]+)", python_package.version)
    if match is None:
        raise ClosureError("locked Python runtime version is unsupported")
    python_prefix = f"lib/python{match.group(1)}"
    required_sources = {
        f"{python_prefix}/encodings/__init__.py",
        "lib/qt6/plugins/platforms/libqxcb.so",
    }

    plans: dict[str, CopyPlan] = {}
    aliases: dict[str, str] = {}
    queue: deque[ElfInfo] = deque()
    selected_package_names: set[str] = set()
    system_abi = set(ARCHITECTURES[architecture]["system_abi"])

    def add_plan(destination: str, source_relative: str, package: PackageRecord) -> ElfInfo | None:
        destination = _relative_path(destination)
        alias = _alias_key(destination)
        existing = plans.get(destination)
        if existing is not None:
            if (
                existing.source_relative_path != source_relative
                or existing.package != package
            ):
                raise ClosureError(f"runtime destination collision: {destination}")
            existing_info = _inspect_source(
                pixi_prefix, source_relative, destination
            )[1]
            return (
                _normalized_needed_info(existing_info)
                if existing_info is not None
                else None
            )
        if alias in aliases and aliases[alias] != destination:
            alias_plan = plans[aliases[alias]]
            if alias_plan.package != package:
                raise ClosureError(
                    f"cross-package runtime destination alias collision: {destination}"
                )
        source, info, kind, link_target = _inspect_source(
            pixi_prefix, source_relative, destination
        )
        plan = CopyPlan(
            destination,
            source,
            source_relative,
            package,
            kind,
            link_target,
            info,
        )
        plans[destination] = plan
        aliases[alias] = destination
        if info is not None and info.machine != int(ARCHITECTURES[architecture]["machine"]):
            raise ClosureError(f"runtime source architecture mismatch: {source_relative}")
        if info is not None and (
            PurePosixPath(destination).name in system_abi
            or info.soname in system_abi
        ):
            raise ClosureError(
                f"selected package attempts to bundle system ABI: {destination}"
            )
        return _normalized_needed_info(info) if info is not None else None

    def dependency_name(specification: str) -> str | None:
        name = specification.split(maxsplit=1)[0]
        if name.startswith("__"):
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ClosureError(f"unsupported locked dependency specification: {specification}")
        return name

    def select_package(initial: PackageRecord) -> None:
        pending = deque([initial])
        while pending:
            package = pending.popleft()
            if package.name in selected_package_names:
                continue
            if not package.license:
                raise ClosureError(
                    f"selected runtime package lacks license provenance: {package.name}"
                )
            selected_package_names.add(package.name)
            for relative in sorted(package.files, key=lambda value: value.encode("utf-8")):
                if owners.get(relative) != package:
                    raise ClosureError(
                        f"selected package does not exclusively own file: {relative}"
                    )
                info = add_plan(relative, relative, package)
                if info is not None:
                    queue.append(info)
            for specification in package.depends:
                name = dependency_name(specification)
                if name is None:
                    continue
                dependency = packages_by_name.get(name)
                if dependency is None:
                    raise ClosureError(
                        f"selected package dependency is not installed: {package.name} -> {name}"
                    )
                pending.append(dependency)

    select_package(python_package)
    qt_package = packages_by_name.get("qt6-main")
    if qt_package is None:
        raise ClosureError("locked prefix does not contain qt6-main")
    select_package(qt_package)
    if not required_sources.issubset(plans):
        raise ClosureError(
            "locked package closure omits required Python/Qt runtime files: "
            + ", ".join(sorted(required_sources - set(plans)))
        )

    stage_infos, _ = _scan_elf(stage, architecture)
    queue.extend(_normalized_needed_info(info) for info in stage_infos.values())
    stage_library_keys: set[str] = set()
    for relative, info in stage_infos.items():
        if PurePosixPath(relative).parent == PurePosixPath("lib"):
            stage_library_keys.add(PurePosixPath(relative).name)
            if info.soname:
                stage_library_keys.add(info.soname)

    candidates = _candidate_index(pixi_prefix, owners, architecture)
    planned_libraries: set[str] = set()
    while queue:
        consumer = queue.popleft()
        for needed in consumer.needed:
            if needed in system_abi or needed in stage_library_keys or needed in planned_libraries:
                continue
            source_relative, _source, package, info, _digest = _choose_candidate(needed, candidates)
            select_package(package)
            destination = f"lib/{needed}"
            copied_info = add_plan(destination, source_relative, package)
            effective_info = copied_info or _normalized_needed_info(info)
            queue.append(
                replace(
                    effective_info,
                    relative_path=destination,
                )
            )
            planned_libraries.add(needed)
            if effective_info.soname:
                planned_libraries.add(effective_info.soname)

    generated = {
        "bin/qt.conf": b"[Paths]\nPrefix=..\nLibraries=lib\nPlugins=lib/qt6/plugins\n",
        "pyvenv.cfg": (
            f"include-system-site-packages = false\nversion = {python_package.version}\n"
        ).encode("ascii"),
    }
    license_overrides, license_evidence_files = _license_provenance()
    if any(
        packages_by_name[name].url in license_overrides
        for name in selected_package_names
    ):
        for relative, content in license_evidence_files:
            assert relative.startswith("licenses/")
            generated[f"share/licenses/conda/{relative[len('licenses/') : ]}"] = content
    for relative in generated:
        alias = _alias_key(relative)
        if relative in plans or (alias in aliases and aliases[alias] != relative):
            raise ClosureError(f"generated runtime destination collision: {relative}")
        aliases[alias] = relative

    manifest_path = stage.joinpath(*PurePosixPath(MANIFEST_RELATIVE_PATH).parts)
    all_destinations = set(plans) | set(generated) | {MANIFEST_RELATIVE_PATH}
    for relative in all_destinations:
        if os.path.lexists(stage.joinpath(*PurePosixPath(relative).parts)):
            raise ClosureError(f"runtime destination already exists: {relative}")

    created_files: list[Path] = []
    created_directories: list[Path] = []
    stage_backups: list[
        tuple[str, tuple[tuple[int, bytes], ...], int, int]
    ] = []
    try:
        stage_transformations, stage_backups = _normalize_staged_elf(
            stage, architecture, epoch
        )
        with _held_root(pixi_prefix) as source_root_descriptor, _held_root(
            stage, require_unchanged=False
        ) as destination_root_descriptor:
            records = [
                _copy_plan(
                    stage,
                    destination_root_descriptor,
                    source_root_descriptor,
                    plans[relative],
                    epoch,
                    created_files,
                    created_directories,
                )
                for relative in sorted(plans, key=lambda value: value.encode("utf-8"))
            ]
            for relative in sorted(generated, key=lambda value: value.encode("utf-8")):
                _write_anchored_file(
                    stage,
                    destination_root_descriptor,
                    relative,
                    generated[relative],
                    epoch,
                    created_files,
                    created_directories,
                )

        report = audit_runtime_closure(stage, architecture)
        _raise_report(report)
        managed_root_candidates = (
            python_prefix,
            "lib/ossl-modules",
            "lib/qt6",
            "share/qt6",
            "share/licenses/conda",
            "ssl",
        )
        managed_roots = sorted(
            {
                root
                for root in managed_root_candidates
                if any(
                    relative == root or relative.startswith(root + "/")
                    for relative in set(plans) | set(generated)
                )
            },
            key=lambda value: value.encode("utf-8"),
        )
        manifest = {
            "architecture": architecture,
            "dependency_lock_sha256": lock_digest,
            "elf": [info.manifest_record() for info in report.elf],
            "files": records,
            "format_version": FORMAT_VERSION,
            "managed_entries": _managed_tree_entries(stage, managed_roots),
            "managed_roots": managed_roots,
            "python_prefix": python_prefix,
            "selected_packages": [
                packages_by_name[name].selection_manifest_record()
                for name in sorted(selected_package_names)
            ],
            "stage_transformations": stage_transformations,
            "system_abi": list(ARCHITECTURES[architecture]["system_abi"]),
        }
        manifest_content = _canonical_json(manifest)
        if len(manifest_content) > MAX_MANIFEST_BYTES:
            raise ClosureError("runtime closure manifest exceeds policy limit")
        with _held_root(stage, require_unchanged=False) as destination_root_descriptor:
            _write_anchored_file(
                stage,
                destination_root_descriptor,
                MANIFEST_RELATIVE_PATH,
                manifest_content,
                epoch,
                created_files,
                created_directories,
            )
        verify_runtime_closure(
            stage,
            architecture,
            expected_dependency_lock_sha256=lock_digest,
        )
        return manifest_path
    except BaseException:
        for path in reversed(created_files):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for path in reversed(created_directories):
            try:
                path.rmdir()
            except OSError:
                pass
        _restore_stage_patches(stage, stage_backups)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bundle = subparsers.add_parser("bundle", help="copy the locked runtime into a stage")
    bundle.add_argument("--stage-prefix", required=True)
    bundle.add_argument("--pixi-prefix", required=True)
    bundle.add_argument("--dependency-lock", required=True)
    bundle.add_argument("--architecture", required=True, choices=sorted(ARCHITECTURES))
    bundle.add_argument("--source-date-epoch", required=True, type=int)
    verify = subparsers.add_parser("verify", help="verify a bundled staged prefix")
    verify.add_argument("--stage-prefix", required=True)
    verify.add_argument("--architecture", required=True, choices=sorted(ARCHITECTURES))
    audit = subparsers.add_parser("audit", help="report closure issues without a manifest")
    audit.add_argument("--stage-prefix", required=True)
    audit.add_argument("--architecture", required=True, choices=sorted(ARCHITECTURES))
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    try:
        if args.command == "bundle":
            path = bundle_runtime(
                args.stage_prefix,
                args.pixi_prefix,
                args.dependency_lock,
                args.architecture,
                args.source_date_epoch,
            )
            print(path)
        elif args.command == "verify":
            report = verify_runtime_closure(args.stage_prefix, args.architecture)
            print(f"verified {report.elf_count} ELF files")
        else:
            report = audit_runtime_closure(args.stage_prefix, args.architecture)
            print(
                _canonical_json(
                    {
                        "dynamic_elf_count": report.dynamic_elf_count,
                        "elf_count": report.elf_count,
                        "issues": list(report.issues),
                    }
                ).decode("utf-8"),
                end="",
            )
            return 1 if report.issues else 0
    except (ClosureError, MemoryError, OSError, OverflowError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
