#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fail-closed security primitives for the OpenFusion Windows bundle."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import functools
import hashlib
import importlib.util
import json
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tarfile
import tempfile
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile

import yaml


AMD64_PE_MACHINE = 0x8664
MAX_PE_BYTES = 512 * 1024**2
READ_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
LEGAL_POLICY_PATH = Path(__file__).resolve().parents[1] / "linux" / "legal_quarantine.json"
LEGAL_VERIFIER_PATH = LEGAL_POLICY_PATH.with_name("create_deterministic_tarball.py")
INVALID_WINDOWS_CHARACTERS = frozenset('<>:"/\\|?*')
DOS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
SYSTEM_DLL_ALLOWLIST = frozenset(
    {
        "advapi32.dll", "avrt.dll", "bcrypt.dll", "bcryptprimitives.dll",
        "cabinet.dll", "cfgmgr32.dll", "comctl32.dll", "comdlg32.dll",
        "crypt32.dll", "cryptbase.dll", "cryptsp.dll", "cryptui.dll",
        "d2d1.dll", "d3d11.dll", "d3d12.dll", "dbgcore.dll", "dbghelp.dll",
        "d3d9.dll", "dcomp.dll", "dhcpcsvc.dll", "dnsapi.dll", "dsound.dll",
        "dwmapi.dll", "dwrite.dll", "dxgi.dll",
        "gdi32.dll", "glu32.dll", "hid.dll", "imagehlp.dll", "imm32.dll",
        "iphlpapi.dll", "kernel32.dll", "kernelbase.dll", "mpr.dll",
        "mf.dll", "mfplat.dll", "mfreadwrite.dll", "mfuuid.dll", "msasn1.dll",
        "msimg32.dll", "msvcrt.dll", "mswsock.dll", "ncrypt.dll", "netapi32.dll",
        "normaliz.dll", "nsi.dll", "ntdll.dll", "ole32.dll", "oleacc.dll", "opengl32.dll",
        "oleaut32.dll", "olepro32.dll", "pdh.dll", "powrprof.dll", "profapi.dll",
        "propsys.dll", "psapi.dll", "rasapi32.dll",
        "rpcrt4.dll", "secur32.dll", "setupapi.dll", "shell32.dll",
        "shcore.dll", "shlwapi.dll", "strmiids.dll", "urlmon.dll", "user32.dll",
        "userenv.dll", "usp10.dll", "uxtheme.dll", "version.dll", "vfw32.dll",
        "wevtapi.dll", "windowscodecs.dll", "winhttp.dll", "wininet.dll",
        "winmm.dll", "winspool.drv", "wintrust.dll", "wldap32.dll", "wlanapi.dll",
        "ws2_32.dll", "wtsapi32.dll",
    }
)
API_SET_NAME = re.compile(r"(?:api|ext)-ms-(?:win|onecore)-[a-z0-9-]+\.dll\Z")
MANIFEST_FIELDS = frozenset(
    {
        "api_set_contract", "architecture", "archive_root", "artifact", "canonical_entrypoints",
        "entries", "format_version", "legal_policy_sha256", "pe_dependencies",
        "pixi_lock_sha256", "platform", "relocation", "runtime_packages",
        "source_date_epoch", "source_revision", "system_dll_policy_sha256",
        "unsigned_development_artifact", "version",
    }
)
RELOCATION = {
    "openssl_conf": "ssl/openssl.cnf",
    "python_home": "bin",
    "python_path_file": "bin/python311._pth",
    "qt_conf": "bin/qt6.conf",
    "qt_plugins": "plugins",
}


class SecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Owner:
    identity: str
    name: str
    version: str
    build: str
    subdir: str
    url: str
    package_sha256: str
    package_size: int


@dataclass(frozen=True)
class OwnedFile:
    owner: Owner
    expected_identities: tuple[tuple[str, int], ...]
    path_type: str
    archive_path: Path | None = None
    source_sha256: str | None = None
    source_size: int | None = None
    prefix_placeholder: str | None = None
    file_mode: str | None = None
    conda_prefix: Path | None = None


@dataclass(frozen=True)
class LockInventory:
    packages: dict[str, tuple[str, int]]
    active_windows_urls: frozenset[str]


@dataclass(frozen=True)
class PeInfo:
    imports: tuple[str, ...]
    delay_imports: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(READ_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def windows_alias_key(path: PurePosixPath) -> str:
    normalized_parts: list[str] = []
    for original in path.parts:
        normalized = unicodedata.normalize("NFKC", original)
        if (
            not normalized
            or normalized[-1] in " ."
            or any(ord(character) < 32 or character in INVALID_WINDOWS_CHARACTERS for character in normalized)
        ):
            raise SecurityError(f"unsafe Windows path component: {original!r}")
        folded = normalized.casefold()
        if folded.split(".", 1)[0] in DOS_DEVICES:
            raise SecurityError(f"reserved Windows DOS device path: {original!r}")
        normalized_parts.append(folded)
    return "/".join(normalized_parts)


def safe_relative(value: str | PurePosixPath, label: str, *, metadata: bool = False) -> PurePosixPath:
    text = str(value)
    if metadata:
        text = text.replace("\\", "/")
    elif "\\" in text:
        raise SecurityError(f"{label} uses a Windows alias separator: {value!r}")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or path == PurePosixPath(".") or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise SecurityError(f"unsafe {label}: {value!r}")
    windows_alias_key(path)
    return path


def is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    junction = getattr(path, "is_junction", None)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & 0x400) or bool(
        callable(junction) and junction()
    )


def reject_reparse_chain(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            if is_reparse(current):
                raise SecurityError(f"reparse points and junctions are forbidden: {current}")


def anchored(path: Path, root: Path, label: str) -> Path:
    try:
        root_absolute = Path(os.path.abspath(root))
        path_absolute = Path(os.path.abspath(path))
        path_absolute.relative_to(root_absolute)
        reject_reparse_chain(root_absolute)
        reject_reparse_chain(path_absolute)
        resolved_root = root_absolute.resolve(strict=True)
        resolved = path_absolute.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise SecurityError(f"{label} escapes or is missing below {root}: {path}") from error
    return resolved


def validated_package_url(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or any(character in value for character in "\r\n"):
        raise SecurityError(f"{label} is not a canonical URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.query or parsed.fragment
        or not parsed.path.endswith((".conda", ".tar.bz2"))
    ):
        raise SecurityError(f"{label} contains credentials, query state, or an unsafe origin: {value}")
    return value


def parse_lock(lock_file: Path) -> LockInventory:
    try:
        value = yaml.safe_load(lock_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SecurityError("Pixi lock is not valid YAML") from error
    if not isinstance(value, dict) or set(value) != {"version", "environments", "packages"}:
        raise SecurityError("Pixi lock has an unexpected top-level structure")
    packages = value.get("packages")
    if type(value.get("version")) is not int or not isinstance(packages, list):
        raise SecurityError("Pixi lock has invalid version or package records")
    result: dict[str, tuple[str, int]] = {}
    for record in packages:
        if not isinstance(record, dict) or "conda" not in record:
            continue
        url = validated_package_url(record["conda"], "locked Conda URL")
        digest = record.get("sha256")
        size = record.get("size")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest.lower()) is None:
            raise SecurityError(f"locked Conda package lacks SHA-256: {url}")
        if type(size) is not int or size <= 0:
            raise SecurityError(f"locked Conda package lacks a positive size: {url}")
        identity = (digest.lower(), size)
        previous = result.setdefault(url, identity)
        if previous != identity:
            raise SecurityError(f"lock contains conflicting identities for {url}")
    if not result:
        raise SecurityError("Pixi lock did not contain hashed Conda package records")
    environments = value["environments"]
    if not isinstance(environments, dict) or set(environments) != {"default"}:
        raise SecurityError("Pixi lock must contain exactly the default environment")
    default = environments["default"]
    if not isinstance(default, dict) or not isinstance(default.get("packages"), dict):
        raise SecurityError("Pixi lock default environment has no platform package map")
    windows_records = default["packages"].get("win-64")
    if not isinstance(windows_records, list) or not windows_records:
        raise SecurityError("Pixi lock default environment has no win-64 package closure")
    active_urls: set[str] = set()
    for record in windows_records:
        if not isinstance(record, dict):
            raise SecurityError("Pixi win-64 environment package record is invalid")
        if "conda" not in record:
            continue
        url = validated_package_url(record["conda"], "active locked Conda URL")
        if url not in result or url in active_urls:
            raise SecurityError(f"Pixi active package reference is missing or duplicated: {url}")
        active_urls.add(url)
    if not active_urls:
        raise SecurityError("Pixi win-64 environment has no Conda packages")
    return LockInventory(result, frozenset(active_urls))


def archive_cache_path(cache: Path, url: str, digest: str) -> Path:
    suffix = ".tar.bz2" if url.endswith(".tar.bz2") else ".conda"
    return cache / f"{digest}{suffix}"


def _authenticate_archive(path: Path, expected_digest: str, expected_size: int) -> None:
    reject_reparse_chain(path)
    if not path.is_file() or path.stat().st_size != expected_size:
        raise SecurityError(f"cached Conda archive is missing or has wrong size: {path}")
    if sha256_file(path) != expected_digest:
        raise SecurityError(f"cached Conda archive hash differs from pixi.lock: {path}")


def fetch_archives(inventory: LockInventory, cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    reject_reparse_chain(cache)

    def fetch(url: str) -> str:
        digest, size = inventory.packages[url]
        destination = archive_cache_path(cache, url, digest)
        if destination.exists() or destination.is_symlink():
            _authenticate_archive(destination, digest, size)
            return destination.name
        temporary_handle = tempfile.NamedTemporaryFile(
            prefix=".openfusion-conda-", suffix=".download", dir=cache, delete=False
        )
        temporary = Path(temporary_handle.name)
        calculated = hashlib.sha256()
        total = 0
        try:
            with temporary_handle, urlopen(
                Request(url, headers={"User-Agent": "OpenFusion locked Windows packager/1"}),
                timeout=120,
            ) as response:
                while chunk := response.read(READ_BYTES):
                    total += len(chunk)
                    if total > size:
                        raise SecurityError(f"Conda archive download exceeded locked size: {url}")
                    calculated.update(chunk)
                    temporary_handle.write(chunk)
            if total != size or calculated.hexdigest() != digest:
                raise SecurityError(f"downloaded Conda archive differs from pixi.lock: {url}")
            os.link(temporary, destination)
            _authenticate_archive(destination, digest, size)
            return destination.name
        finally:
            temporary.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="openfusion-conda") as executor:
        for name in executor.map(fetch, sorted(inventory.active_windows_urls)):
            print(f"authenticated Conda archive: {name}", flush=True)


def _normalized_tar_name(value: str) -> str:
    while value.startswith("./"):
        value = value[2:]
    return safe_relative(value, "Conda archive member").as_posix()


def _read_tar_members(archive: tarfile.TarFile, wanted: set[str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for member in archive:
        name = _normalized_tar_name(member.name)
        if name not in wanted:
            continue
        if not member.isfile() or member.size > 64 * 1024**2:
            raise SecurityError(f"invalid required Conda archive member: {name}")
        stream = archive.extractfile(member)
        if stream is None:
            raise SecurityError(f"cannot read Conda archive member: {name}")
        contents = stream.read(member.size + 1)
        if len(contents) != member.size:
            raise SecurityError(f"truncated Conda archive member: {name}")
        if name in result:
            raise SecurityError(f"duplicate Conda archive member: {name}")
        result[name] = contents
    return result


def _conda_component(archive_path: Path, prefix: str) -> bytes:
    with zipfile.ZipFile(archive_path, "r") as archive:
        matches = [
            info for info in archive.infolist()
            if info.filename.startswith(prefix + "-") and info.filename.endswith(".tar.zst")
        ]
        if len(matches) != 1 or matches[0].file_size > archive_path.stat().st_size * 2:
            raise SecurityError(f"invalid .conda {prefix} component: {archive_path}")
        return archive.read(matches[0])


def _archive_members(archive_path: Path, wanted: set[str], *, payload: bool) -> dict[str, bytes]:
    if archive_path.name.endswith(".tar.bz2"):
        with tarfile.open(archive_path, "r:bz2") as archive:
            return _read_tar_members(archive, wanted)
    try:
        import zstandard
    except ImportError as error:
        raise SecurityError("zstandard is required to authenticate .conda packages") from error
    component = _conda_component(archive_path, "pkg" if payload else "info")
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(component)) as reader:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            return _read_tar_members(archive, wanted)


def _archive_info(archive_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    values = _archive_members(
        archive_path, {"info/index.json", "info/paths.json"}, payload=False
    )
    if set(values) != {"info/index.json", "info/paths.json"}:
        raise SecurityError(f"Conda archive lacks immutable index/paths inventory: {archive_path}")
    try:
        index = json.loads(values["info/index.json"].decode("utf-8"))
        paths = json.loads(values["info/paths.json"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SecurityError(f"Conda archive has invalid immutable metadata: {archive_path}") from error
    if not isinstance(index, dict) or not isinstance(paths, dict):
        raise SecurityError(f"Conda archive metadata is not an object: {archive_path}")
    return index, paths


def _relocated_identities(
    original: bytes, placeholder: str, file_mode: str, prefix: Path
) -> tuple[tuple[str, int], ...]:
    encoded_placeholder = placeholder.encode("utf-8")
    if encoded_placeholder not in original:
        raise SecurityError("Conda prefix placeholder is absent from authenticated payload")
    replacements = {str(prefix).encode("utf-8"), prefix.as_posix().encode("utf-8")}
    transformed = []
    for replacement in replacements:
        if file_mode == "binary":
            if len(replacement) > len(encoded_placeholder):
                raise SecurityError("active Conda prefix exceeds binary placeholder capacity")
            replacement = replacement + b"\0" * (len(encoded_placeholder) - len(replacement))
        elif file_mode != "text":
            raise SecurityError(f"unsupported Conda prefix file mode: {file_mode!r}")
        contents = original.replace(encoded_placeholder, replacement)
        transformed.append((hashlib.sha256(contents).hexdigest(), len(contents)))
    return tuple(sorted(set(transformed)))


def _metadata_url(record: dict[str, object]) -> str:
    if isinstance(record.get("url"), str) and record["url"]:
        return validated_package_url(record["url"], "active Conda package URL")
    values = (record.get("channel"), record.get("subdir"), record.get("fn"))
    if all(isinstance(value, str) and value for value in values):
        return validated_package_url(
            f"{str(values[0]).rstrip('/')}/{values[1]}/{values[2]}",
            "active Conda package URL",
        )
    raise SecurityError("Conda package metadata has no canonical URL")


def load_conda_ownership(
    conda_prefix: Path, locked: LockInventory, package_cache: Path
) -> tuple[dict[PurePosixPath, tuple[OwnedFile, ...]], dict[str, Owner]]:
    metadata_root = anchored(conda_prefix / "conda-meta", conda_prefix, "Conda metadata")
    metadata_records = sorted(metadata_root.glob("*.json"), key=lambda path: path.name.casefold())
    if not metadata_records:
        raise SecurityError("active Conda prefix has no package metadata")
    active_metadata_urls: set[str] = set()
    for metadata_path in metadata_records:
        reject_reparse_chain(metadata_path)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SecurityError(f"invalid active Conda metadata locator: {metadata_path}") from error
        if not isinstance(metadata, dict):
            raise SecurityError(f"invalid active Conda metadata locator: {metadata_path}")
        url = _metadata_url(metadata)
        if url in active_metadata_urls:
            raise SecurityError(f"duplicate active Conda package locator: {url}")
        active_metadata_urls.add(url)
    if active_metadata_urls != set(locked.active_windows_urls):
        missing = sorted(set(locked.active_windows_urls) - active_metadata_urls)
        extra = sorted(active_metadata_urls - set(locked.active_windows_urls))
        raise SecurityError(
            f"active Conda package set differs from locked win-64 closure; missing={missing}, extra={extra}"
        )
    reject_reparse_chain(package_cache)
    owned: dict[PurePosixPath, tuple[OwnedFile, ...]] = {}
    packages: dict[str, Owner] = {}
    for url in sorted(locked.active_windows_urls):
        package_sha256, package_size = locked.packages[url]
        archive_path = archive_cache_path(package_cache, url, package_sha256)
        _authenticate_archive(archive_path, package_sha256, package_size)
        record, paths_data = _archive_info(archive_path)
        fields = [record.get(key) for key in ("name", "version", "build", "subdir")]
        if not all(isinstance(value, str) and value for value in fields):
            raise SecurityError(f"incomplete immutable Conda package identity: {archive_path}")
        name, version, build, subdir = (str(value) for value in fields)
        if subdir not in {"win-64", "noarch"}:
            raise SecurityError(f"non-Windows package in active prefix: {name} ({subdir})")
        identity = f"{name}-{version}-{build}"
        owner = Owner(identity, name, version, build, subdir, url, package_sha256, package_size)
        previous_owner = packages.setdefault(identity, owner)
        if previous_owner != owner:
            raise SecurityError(f"duplicate Conda package identity: {identity}")
        if paths_data.get("paths_version") != 1 or not isinstance(paths_data.get("paths"), list):
            raise SecurityError(f"invalid immutable Conda paths inventory: {identity}")
        specifications = []
        package_paths: set[PurePosixPath] = set()
        for path_record in paths_data["paths"]:
            if not isinstance(path_record, dict) or not isinstance(path_record.get("_path"), str):
                raise SecurityError(f"invalid immutable Conda path record: {identity}")
            relative = safe_relative(path_record["_path"], "immutable Conda path", metadata=True)
            if relative in package_paths:
                raise SecurityError(
                    f"immutable Conda inventory duplicates a path: {identity}/{relative}"
                )
            package_paths.add(relative)
            path_type = path_record.get("path_type")
            digest = path_record.get("sha256")
            size = path_record.get("size_in_bytes")
            if path_type == "directory":
                continue
            if path_type not in {"hardlink", "softlink"}:
                raise SecurityError(f"invalid immutable Conda path type: {identity}/{relative}")
            if not isinstance(digest, str) or SHA256_RE.fullmatch(digest.lower()) is None:
                raise SecurityError(f"immutable Conda path lacks SHA-256: {identity}/{relative}")
            if type(size) is not int or size < 0:
                raise SecurityError(f"immutable Conda path lacks size: {identity}/{relative}")
            placeholder = path_record.get("prefix_placeholder")
            file_mode = path_record.get("file_mode")
            if placeholder is not None:
                if not isinstance(placeholder, str) or not placeholder or file_mode not in {"text", "binary"}:
                    raise SecurityError(f"invalid immutable prefix relocation: {identity}/{relative}")
            specifications.append((relative, str(path_type), digest.lower(), size, placeholder, file_mode))
        for relative, path_type, digest, size, placeholder, file_mode in specifications:
            if placeholder is None:
                identities = ((digest, size),)
                item = OwnedFile(owner, identities, path_type)
            else:
                item = OwnedFile(
                    owner,
                    (),
                    path_type,
                    archive_path=archive_path,
                    source_sha256=digest,
                    source_size=size,
                    prefix_placeholder=str(placeholder),
                    file_mode=str(file_mode),
                    conda_prefix=conda_prefix.resolve(strict=True),
                )
            previous = owned.get(relative, ())
            if item in previous:
                raise SecurityError(
                    f"immutable Conda inventory duplicates a path: {identity}/{relative}"
                )
            owned[relative] = (*previous, item)
    return owned, packages


def resolve_owned_file(
    path: Path,
    candidates: tuple[OwnedFile, ...],
    relative: PurePosixPath,
    *,
    required_owner: str | None = None,
) -> OwnedFile:
    identity = (sha256_file(path), path.stat().st_size)
    matches = []
    relocation_errors = []
    for candidate in candidates:
        if candidate.path_type != "hardlink":
            continue
        identities = candidate.expected_identities
        if not identities:
            try:
                if (
                    candidate.archive_path is None
                    or candidate.source_sha256 is None
                    or candidate.source_size is None
                    or candidate.prefix_placeholder is None
                    or candidate.file_mode is None
                    or candidate.conda_prefix is None
                ):
                    raise SecurityError("incomplete immutable prefix-relocation record")
                originals = _archive_members(
                    candidate.archive_path, {relative.as_posix()}, payload=True
                )
                if set(originals) != {relative.as_posix()}:
                    raise SecurityError("authenticated package payload lacks selected prefix file")
                original = originals[relative.as_posix()]
                if (
                    len(original) != candidate.source_size
                    or hashlib.sha256(original).hexdigest() != candidate.source_sha256
                ):
                    raise SecurityError("authenticated prefix file differs from paths.json")
                identities = _relocated_identities(
                    original,
                    candidate.prefix_placeholder,
                    candidate.file_mode,
                    candidate.conda_prefix,
                )
            except SecurityError as error:
                relocation_errors.append(f"{candidate.owner.identity}: {error}")
                continue
        if identity in identities:
            matches.append(candidate)
    if relocation_errors:
        raise SecurityError(
            f"selected runtime prefix relocation could not be authenticated: {relative}: "
            + "; ".join(relocation_errors)
        )
    if not matches:
        raise SecurityError(f"installed Conda file identity changed: {relative}")
    if len(matches) != 1:
        owners = ", ".join(sorted(candidate.owner.identity for candidate in matches))
        raise SecurityError(f"selected runtime has ambiguous authenticated owners: {relative}: {owners}")
    selected = matches[0]
    if required_owner is not None and selected.owner.name != required_owner:
        raise SecurityError(
            f"selected runtime owner is not {required_owner}: {relative}: {selected.owner.identity}"
        )
    return selected


def _u16(contents: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 2 > len(contents):
        raise SecurityError(f"truncated PE structure in {label}")
    return struct.unpack_from("<H", contents, offset)[0]


def _u32(contents: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset + 4 > len(contents):
        raise SecurityError(f"truncated PE structure in {label}")
    return struct.unpack_from("<I", contents, offset)[0]


def parse_pe(contents: bytes, label: str) -> PeInfo:
    if len(contents) > MAX_PE_BYTES:
        raise SecurityError(f"PE exceeds inspection limit: {label}")
    if len(contents) < 0x40 or contents[:2] != b"MZ":
        raise SecurityError(f"native payload lacks a DOS header: {label}")
    pe = _u32(contents, 0x3C, label)
    if pe + 24 > len(contents) or contents[pe:pe + 4] != b"PE\0\0":
        raise SecurityError(f"native payload lacks a PE header: {label}")
    if _u16(contents, pe + 4, label) != AMD64_PE_MACHINE:
        raise SecurityError(f"native payload is not x86-64 PE: {label}")
    section_count = _u16(contents, pe + 6, label)
    optional_size = _u16(contents, pe + 20, label)
    optional = pe + 24
    if optional_size < 112 or optional + optional_size > len(contents):
        raise SecurityError(f"invalid PE optional header: {label}")
    if _u16(contents, optional, label) != 0x20B:
        raise SecurityError(f"native payload is not PE32+: {label}")
    image_base = struct.unpack_from("<Q", contents, optional + 24)[0]
    size_of_headers = _u32(contents, optional + 60, label)
    directory_count = min(_u32(contents, optional + 108, label), 16)
    section_offset = optional + optional_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if offset + 40 > len(contents):
            raise SecurityError(f"truncated PE section table: {label}")
        sections.append(
            (
                _u32(contents, offset + 12, label), _u32(contents, offset + 8, label),
                _u32(contents, offset + 20, label), _u32(contents, offset + 16, label),
            )
        )

    def rva_offset(rva: int, size: int) -> int:
        if rva < size_of_headers and rva + size <= min(size_of_headers, len(contents)):
            return rva
        for virtual_address, virtual_size, raw_offset, raw_size in sections:
            if virtual_address <= rva and rva + size <= virtual_address + max(virtual_size, raw_size):
                delta = rva - virtual_address
                if delta + size <= raw_size and raw_offset + delta + size <= len(contents):
                    return raw_offset + delta
        raise SecurityError(f"PE RVA is not backed by file data in {label}: 0x{rva:x}")

    def c_string(rva: int) -> str:
        offset = rva_offset(rva, 1)
        end = contents.find(b"\0", offset, min(len(contents), offset + 512))
        if end < 0:
            raise SecurityError(f"unterminated PE import name: {label}")
        try:
            name = contents[offset:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise SecurityError(f"non-ASCII PE import name: {label}") from error
        relative = safe_relative(name, "PE import name")
        if len(relative.parts) != 1 or relative.suffix.casefold() not in {".dll", ".drv"}:
            raise SecurityError(f"unsafe PE import name in {label}: {name!r}")
        return name.casefold()

    def directory(index: int) -> tuple[int, int]:
        if index >= directory_count:
            return 0, 0
        offset = optional + 112 + index * 8
        if offset + 8 > optional + optional_size:
            raise SecurityError(f"truncated PE data directory: {label}")
        return _u32(contents, offset, label), _u32(contents, offset + 4, label)

    def descriptor_names(index: int, width: int, name_field: int, delay: bool) -> tuple[str, ...]:
        rva, size = directory(index)
        if not rva and not size:
            return ()
        if not rva or size < width:
            raise SecurityError(f"invalid PE {'delay-' if delay else ''}import directory: {label}")
        base = rva_offset(rva, min(size, width))
        names: set[str] = set()
        terminated = False
        for item in range(min(size // width + 1, 4096)):
            offset = base + item * width
            if offset + width > len(contents):
                break
            values = struct.unpack_from("<" + "I" * (width // 4), contents, offset)
            if values == (0,) * (width // 4):
                terminated = True
                break
            name_rva = values[name_field]
            if delay and not (values[0] & 1):
                if name_rva < image_base or name_rva - image_base > 0xFFFFFFFF:
                    raise SecurityError(f"invalid VA-based delay import in {label}")
                name_rva -= image_base
            names.add(c_string(name_rva))
        if not terminated:
            raise SecurityError(f"unterminated PE {'delay-' if delay else ''}import directory: {label}")
        return tuple(sorted(names))

    return PeInfo(
        descriptor_names(1, 20, 3, False),
        descriptor_names(13, 32, 1, True),
    )


def system_policy_sha256() -> str:
    return hashlib.sha256(
        canonical_json({"exact_system32": sorted(SYSTEM_DLL_ALLOWLIST)})
    ).hexdigest()


@functools.lru_cache(maxsize=1)
def api_set_contract() -> tuple[frozenset[str], dict[str, object]]:
    if os.name != "nt":
        contracts = frozenset({"api-ms-win-core-file-l1-1-0.dll"})
        return contracts, {
            "contract_version": "non-windows-test-v1",
            "contracts_sha256": hashlib.sha256(canonical_json(sorted(contracts))).hexdigest(),
            "schema_path": None,
            "schema_sha256": None,
        }
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        raise SecurityError("SystemRoot is unavailable while loading ApiSet schema")
    schema_path = Path(system_root) / "System32" / "ApiSetSchema.dll"
    if not schema_path.is_file() or is_reparse(schema_path):
        raise SecurityError("ApiSetSchema.dll is not a regular System32 file")
    contents = schema_path.read_bytes()
    if len(contents) < 0x40 or contents[:2] != b"MZ":
        raise SecurityError("ApiSetSchema.dll has no PE header")
    pe = _u32(contents, 0x3C, "ApiSetSchema.dll")
    if pe + 24 > len(contents) or contents[pe:pe + 4] != b"PE\0\0":
        raise SecurityError("ApiSetSchema.dll has an invalid PE header")
    section_count = _u16(contents, pe + 6, "ApiSetSchema.dll")
    optional_size = _u16(contents, pe + 20, "ApiSetSchema.dll")
    section_offset = pe + 24 + optional_size
    namespace = None
    for index in range(section_count):
        offset = section_offset + index * 40
        if offset + 40 > len(contents):
            raise SecurityError("ApiSetSchema.dll section table is truncated")
        name = contents[offset:offset + 8].rstrip(b"\0")
        if name == b".apiset":
            raw_size = _u32(contents, offset + 16, "ApiSetSchema.dll")
            raw_offset = _u32(contents, offset + 20, "ApiSetSchema.dll")
            if raw_offset + raw_size > len(contents):
                raise SecurityError("ApiSet schema section escapes its PE file")
            namespace = contents[raw_offset:raw_offset + raw_size]
            break
    if namespace is None or len(namespace) < 28:
        raise SecurityError("ApiSetSchema.dll has no bounded .apiset namespace")
    version, size, _, count, entry_offset, _, _ = struct.unpack_from("<IIIIIII", namespace, 0)
    if version != 6 or size < 28 or size > len(namespace) or count > 10000:
        raise SecurityError("unsupported or invalid ApiSet namespace version")
    contracts: set[str] = set()
    for index in range(count):
        offset = entry_offset + index * 24
        if offset + 24 > size:
            raise SecurityError("ApiSet namespace entry table is truncated")
        _, name_offset, name_length, _, _, _ = struct.unpack_from("<IIIIII", namespace, offset)
        if name_length == 0 or name_length % 2 or name_offset + name_length > size:
            raise SecurityError("ApiSet namespace contains an invalid contract name")
        try:
            name = namespace[name_offset:name_offset + name_length].decode("utf-16le").casefold() + ".dll"
        except UnicodeDecodeError as error:
            raise SecurityError("ApiSet namespace contract is not UTF-16") from error
        if API_SET_NAME.fullmatch(name) is None or name in contracts:
            raise SecurityError(f"ApiSet namespace contract is unsafe or duplicated: {name}")
        contracts.add(name)
    if not contracts:
        raise SecurityError("ApiSet namespace contains no contracts")
    frozen = frozenset(contracts)
    evidence = {
        "contract_version": version,
        "contracts_sha256": hashlib.sha256(canonical_json(sorted(frozen))).hexdigest(),
        "schema_path": "%SystemRoot%/System32/ApiSetSchema.dll",
        "schema_sha256": hashlib.sha256(contents).hexdigest(),
    }
    return frozen, evidence


def pe_evidence(
    contents_by_path: dict[PurePosixPath, bytes], api_contracts: frozenset[str] | None = None
) -> list[dict[str, object]]:
    if api_contracts is None:
        api_contracts = api_set_contract()[0]
    for path in contents_by_path:
        name = path.name.casefold()
        if (name in SYSTEM_DLL_ALLOWLIST and name != "opengl32.dll") or API_SET_NAME.fullmatch(name):
            raise SecurityError(f"payload shadows a System32 or ApiSet dependency: {path}")
    bin_names = {
        path.name.casefold(): path for path in contents_by_path
        if path.parent == PurePosixPath("bin") and path.suffix.casefold() in {".dll", ".pyd", ".exe"}
    }
    evidence: list[dict[str, object]] = []
    for path in sorted(contents_by_path, key=lambda value: value.as_posix().encode("utf-8")):
        info = parse_pe(contents_by_path[path], path.as_posix())
        for dependency in (*info.imports, *info.delay_imports):
            if dependency in bin_names:
                continue
            if dependency in api_contracts:
                continue
            if dependency not in SYSTEM_DLL_ALLOWLIST:
                raise SecurityError(f"unresolved PE dependency from {path}: {dependency}")
            if os.name == "nt":
                system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
                if not system_root:
                    raise SecurityError("SystemRoot is unavailable while resolving PE imports")
                candidate = Path(system_root) / "System32" / dependency
                if not candidate.is_file() or is_reparse(candidate):
                    raise SecurityError(
                        f"allowlisted PE dependency is not a regular System32 file: {dependency}"
                    )
        evidence.append(
            {"delay_imports": list(info.delay_imports), "imports": list(info.imports), "path": path.as_posix()}
        )
    return evidence


@functools.lru_cache(maxsize=1)
def _legal_module():
    spec = importlib.util.spec_from_file_location("openfusion_authoritative_legal", LEGAL_VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise SecurityError("cannot load authoritative legal quarantine verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def legal_policy_sha256() -> str:
    return sha256_file(LEGAL_POLICY_PATH)


def verify_legal_archive(archive_path: Path, archive_root: str) -> None:
    module = _legal_module()
    try:
        with tempfile.TemporaryDirectory(prefix="openfusion-legal-") as temporary:
            root = Path(temporary)
            entries = []
            with zipfile.ZipFile(archive_path, "r") as archive:
                for info in archive.infolist():
                    prefix = f"{archive_root}/"
                    if not info.filename.startswith(prefix) or info.is_dir():
                        raise SecurityError(f"unsafe legal scan archive member: {info.filename}")
                    relative = safe_relative(info.filename[len(prefix):], "legal scan member")
                    destination = root.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, READ_BYTES)
                    metadata = destination.stat()
                    entries.append(
                        module.Entry(
                            relative.as_posix(), destination, "file", 0o644,
                            metadata.st_size, sha256_file(destination), None,
                            module.Snapshot.from_stat(metadata),
                        )
                    )
            module._verify_legal_quarantine(root, entries)
    except module.PackagingError as error:
        raise SecurityError(f"authoritative legal quarantine rejected payload: {error}") from error


def validate_manifest_schema(manifest: object) -> None:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise SecurityError("portable manifest schema is not exact")
    if manifest.get("canonical_entrypoints") != ["bin/OpenFusion.exe", "bin/OpenFusionCmd.exe"]:
        raise SecurityError("portable canonical entrypoint schema is invalid")
    if manifest.get("relocation") != RELOCATION:
        raise SecurityError("portable relocation schema is invalid")
    api_contract = manifest.get("api_set_contract")
    if not isinstance(api_contract, dict) or set(api_contract) != {
        "contract_version", "contracts_sha256", "schema_path", "schema_sha256"
    }:
        raise SecurityError("portable ApiSet contract evidence is invalid")
    if not isinstance(api_contract.get("contracts_sha256"), str) or SHA256_RE.fullmatch(
        api_contract["contracts_sha256"]
    ) is None:
        raise SecurityError("portable ApiSet contract-set hash is invalid")
    if api_contract["schema_sha256"] is not None and (
        not isinstance(api_contract["schema_sha256"], str)
        or SHA256_RE.fullmatch(api_contract["schema_sha256"]) is None
    ):
        raise SecurityError("portable ApiSet schema hash is invalid")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SecurityError("portable manifest has no entries")
    paths = []
    for record in entries:
        if not isinstance(record, dict) or set(record) != {"origin", "path", "sha256", "size"}:
            raise SecurityError("portable manifest entry schema is invalid")
        if (
            not isinstance(record["origin"], str) or not record["origin"]
            or not isinstance(record["path"], str)
            or not isinstance(record["sha256"], str)
            or SHA256_RE.fullmatch(record["sha256"]) is None
            or type(record["size"]) is not int or record["size"] < 0
        ):
            raise SecurityError("portable manifest entry values are invalid")
        paths.append(record["path"])
    if paths != sorted(paths, key=lambda value: value.encode("utf-8")):
        raise SecurityError("portable manifest entries are not canonically ordered")
    packages = manifest.get("runtime_packages")
    if not isinstance(packages, list) or not packages:
        raise SecurityError("portable manifest has no runtime packages")
    order = []
    for record in packages:
        if not isinstance(record, dict) or set(record) != {
            "build", "name", "package_sha256", "package_size", "subdir", "url", "version"
        }:
            raise SecurityError("portable runtime package schema is invalid")
        if any(not isinstance(record[field], str) or not record[field] for field in (
            "build", "name", "package_sha256", "subdir", "url", "version"
        )):
            raise SecurityError("portable runtime package values are invalid")
        validated_package_url(record["url"], "manifest runtime package URL")
        if not isinstance(record["package_sha256"], str) or SHA256_RE.fullmatch(record["package_sha256"]) is None:
            raise SecurityError("portable runtime package hash is invalid")
        if type(record["package_size"]) is not int or record["package_size"] <= 0:
            raise SecurityError("portable runtime package size is invalid")
        order.append((record["name"], record["version"], record["build"], record["url"]))
    if order != sorted(order):
        raise SecurityError("portable runtime packages are not canonically ordered")
    dependencies = manifest.get("pe_dependencies")
    if not isinstance(dependencies, list):
        raise SecurityError("portable PE dependency schema is invalid")
    dependency_paths = []
    for record in dependencies:
        if not isinstance(record, dict) or set(record) != {"delay_imports", "imports", "path"}:
            raise SecurityError("portable PE dependency record is invalid")
        if not isinstance(record["path"], str):
            raise SecurityError("portable PE dependency path is invalid")
        if not isinstance(record["imports"], list) or record["imports"] != sorted(set(record["imports"])):
            raise SecurityError("portable PE imports are not canonical")
        if not isinstance(record["delay_imports"], list) or record["delay_imports"] != sorted(set(record["delay_imports"])):
            raise SecurityError("portable PE delay imports are not canonical")
        dependency_paths.append(record["path"])
    if dependency_paths != sorted(dependency_paths, key=lambda value: str(value).encode("utf-8")):
        raise SecurityError("portable PE records are not canonically ordered")


def validate_zip_info(archive_path: Path, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> None:
    if archive.comment or info.comment or info.extra:
        raise SecurityError(f"ZIP comments and extra fields are forbidden: {info.filename}")
    expected_flags = 0x800 if not info.filename.isascii() else 0
    if info.flag_bits != expected_flags:
        raise SecurityError(f"ZIP flags are not normalized: {info.filename}")
    with archive_path.open("rb") as source:
        source.seek(info.header_offset)
        header = source.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise SecurityError(f"invalid ZIP local header: {info.filename}")
        flags, compression, name_length, extra_length = struct.unpack_from("<HH16xHH", header, 6)
        encoded_name = source.read(name_length)
        if flags != expected_flags or compression != zipfile.ZIP_DEFLATED or extra_length != 0:
            raise SecurityError(f"ZIP local metadata is not normalized: {info.filename}")
        expected_name = info.filename.encode("utf-8")
        if encoded_name != expected_name:
            raise SecurityError(f"ZIP local filename differs from central directory: {info.filename}")
