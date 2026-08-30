#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 OpenFusion contributors
"""Fail-closed integrity audit and SPDX inventory generator for ``pixi.lock``.

This intentionally parses only the canonical Pixi lock-file version currently
committed by OpenFusion. A lock-format or source-policy change must update this
auditor and its tests in the same review. The generated SPDX document describes
the all-platform source dependency lock; it is not a final runtime-package SBOM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


LOCK_FORMAT_VERSION = 6
EXPECTED_CHANNELS = (
    "https://conda.anaconda.org/freecad/",
    "https://conda.anaconda.org/conda-forge/",
)
EXPECTED_INDEXES = ("https://pypi.org/simple",)
EXPECTED_PLATFORMS = (
    "linux-64",
    "linux-aarch64",
    "osx-64",
    "osx-arm64",
    "win-64",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MD5_RE = re.compile(r"[0-9a-f]{32}")
SOURCE_REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
PACKAGE_START_RE = re.compile(r"^- (conda|pypi): (\S+)$")
FIELD_RE = re.compile(r"^  ([a-z][a-z0-9_]*):(?: (.*))?$")
LIST_ITEM_RE = re.compile(r"^  - (.*)$")
REFERENCE_RE = re.compile(r"^      - (conda|pypi): (\S+)$")
PLATFORM_RE = re.compile(r"^      ([a-z0-9-]+):$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
CONDA_FILENAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+!~-]*")
PYPI_PATH_HASH_RE = re.compile(r"[0-9a-f]{20,128}")
PROJECT_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
WHEEL_NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.]*[A-Za-z0-9])?")
WHEEL_TAG_RE = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")
PEP440_RE = re.compile(
    r"""
    \A v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:[-_.]?(?P<pre_l>a|b|c|rc|alpha|beta|pre|preview)(?P<pre_n>[0-9]+)?)?
    (?:
        -(?P<post_n1>[0-9]+)
        |
        [-_.]?(?P<post_l>post|rev|r)(?P<post_n2>[0-9]+)?
    )?
    (?:[-_.]?(?P<dev_l>dev)(?P<dev_n>[0-9]+)?)?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
YAML_NON_STRING_RE = re.compile(
    r"(?:~|null|true|false|yes|no|on|off)",
    re.IGNORECASE,
)
YAML_INTEGER_RE = re.compile(
    r"[-+]?(?:[0-9][0-9_]*|0b[0-1_]+|0o[0-7_]+|0x[0-9a-f_]+)",
    re.IGNORECASE,
)
YAML_FLOAT_RE = re.compile(
    r"[-+]?(?:(?:[0-9][0-9_]*)?\.[0-9_]+(?:[eE][-+]?[0-9]+)?|"
    r"[0-9][0-9_]*\.(?:[0-9_]*)?(?:[eE][-+]?[0-9]+)?|"
    r"[0-9][0-9_]*[eE][-+]?[0-9]+|\.(?:inf|nan))",
    re.IGNORECASE,
)
YAML_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[Tt ]"
    r"[0-9]{1,2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
    r"(?:[ \t]*(?:[Zz]|[-+][0-9]{1,2}(?::?[0-9]{2})?))?)?"
)
YAML_REFERENCE_RE = re.compile(
    r"^(?:&[A-Za-z0-9_-]+|\*[A-Za-z0-9_-]+|!!?[A-Za-z][^\s]*)"
)
YAML_COMMENT_RE = re.compile(r"(?:^|\s)#")
CONDA_MATCHSPEC_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
    r"(?:(?: *[<>=!~][A-Za-z0-9_.*+!<>=,|:/~-]+)"
    r"|(?: +[A-Za-z0-9_.*+!<>=,|:/~-]+))*"
)
PURL_RE = re.compile(r"pkg:[!-~]+")
TRACK_FEATURE_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
PYPI_REQUIREMENT_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._,-]+\])?(?:[ -~]*)"
)
PEP440_SPECIFIER_RE = re.compile(
    r"(===|~=|==|!=|<=|>=|<|>)([A-Za-z0-9][A-Za-z0-9.!*+_-]*)"
)
METADATA_TEXT_RE = re.compile(r"[ -~]+")
CONDA_CHANNEL_COMPONENTS = frozenset(("freecad", "conda-forge"))
CONDA_SUBDIRECTORIES = frozenset((*EXPECTED_PLATFORMS, "noarch"))
PACKAGE_SCALAR_FIELDS = {
    "conda": frozenset(
        (
            "sha256",
            "md5",
            "build_number",
            "noarch",
            "license",
            "license_family",
            "size",
            "timestamp",
        )
    ),
    "pypi": frozenset(("name", "version", "sha256", "requires_python")),
}
PACKAGE_LIST_FIELDS = {
    "conda": frozenset(("depends", "constrains", "purls", "track_features")),
    "pypi": frozenset(("requires_dist",)),
}
PACKAGE_INTEGER_FIELDS = {
    "conda": frozenset(("build_number", "size", "timestamp")),
    "pypi": frozenset(),
}
CHECKSUM_DISCLOSURE = (
    "Package checksums are unverified assertions copied from pixi.lock; this audit "
    "does not download dependency archives or hash their bytes."
)


class AuditError(ValueError):
    """The dependency lock violates the audited format or source policy."""


@dataclass(frozen=True)
class LockedPackage:
    ecosystem: str
    url: str
    filename: str
    subdirectory: str | None
    wheel_tags: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None
    sha256: str
    name: str
    version: str
    build: str | None
    reported_license: str | None


@dataclass(frozen=True)
class AuditResult:
    lock_sha256: str
    channels: tuple[str, ...]
    indexes: tuple[str, ...]
    platforms: tuple[str, ...]
    platform_references: tuple[tuple[str, tuple[str, ...]], ...]
    reference_count: int
    packages: tuple[LockedPackage, ...]


@dataclass(frozen=True)
class SourceProvenance:
    created: str
    revision: str


def _decode_lock(path: Path) -> tuple[str, str]:
    if path.is_symlink():
        raise AuditError(f"lock file must not be a symbolic link: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuditError(f"cannot read lock file {path}: {exc}") from exc
    if not raw:
        raise AuditError("lock file is empty")
    if b"\x00" in raw:
        raise AuditError("lock file contains a NUL byte")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError("lock file is not valid UTF-8") from exc
    if "\t" in text:
        raise AuditError("lock file contains a tab; canonical Pixi YAML uses spaces")
    return text, hashlib.sha256(raw).hexdigest()


def _parse_header(
    lines: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, list[str]]]:
    if not lines or lines[0] != f"version: {LOCK_FORMAT_VERSION}":
        raise AuditError(
            f"expected canonical Pixi lock format version {LOCK_FORMAT_VERSION}"
        )
    if lines.count("environments:") != 1 or lines.count("  default:") != 1:
        raise AuditError("expected exactly one default Pixi environment")

    channels: list[str] = []
    indexes: list[str] = []
    references: dict[str, list[str]] = {}
    source_section: str | None = None
    platform: str | None = None

    for line in lines:
        if line == "    channels:":
            source_section = "channels"
            platform = None
            continue
        if line == "    indexes:":
            source_section = "indexes"
            platform = None
            continue
        if line == "    packages:":
            source_section = None
            platform = None
            continue

        if source_section == "channels" and line.startswith("    - url: "):
            channels.append(line.removeprefix("    - url: "))
            continue
        if source_section == "indexes" and line.startswith("    - "):
            indexes.append(line.removeprefix("    - "))
            continue

        platform_match = PLATFORM_RE.fullmatch(line)
        if platform_match:
            platform = platform_match.group(1)
            references.setdefault(platform, [])
            continue

        reference_match = REFERENCE_RE.fullmatch(line)
        if reference_match:
            if platform is None:
                raise AuditError("package reference appears outside a platform")
            references[platform].append(reference_match.group(2))

    if tuple(channels) != EXPECTED_CHANNELS:
        raise AuditError(
            "Pixi channels changed from the reviewed allowlist: " + repr(channels)
        )
    if tuple(indexes) != EXPECTED_INDEXES:
        raise AuditError(
            "Python indexes changed from the reviewed allowlist: " + repr(indexes)
        )
    if tuple(references) != EXPECTED_PLATFORMS:
        raise AuditError(
            "Pixi platforms changed from the reviewed matrix: "
            + repr(tuple(references))
        )
    for platform_name, platform_references in references.items():
        if not platform_references:
            raise AuditError(
                f"platform {platform_name} has no locked package references"
            )
        if len(platform_references) != len(set(platform_references)):
            raise AuditError(
                f"platform {platform_name} contains duplicate package references"
            )

    canonical_header = [
        f"version: {LOCK_FORMAT_VERSION}",
        "environments:",
        "  default:",
        "    channels:",
        *(f"    - url: {channel}" for channel in channels),
        "    indexes:",
        *(f"    - {index}" for index in indexes),
        "    packages:",
    ]
    for platform_name, platform_references in references.items():
        canonical_header.append(f"      {platform_name}:")
        canonical_header.extend(
            f"      - {_reference_kind(url)}: {url}" for url in platform_references
        )
    if lines != canonical_header:
        raise AuditError("lock header is not in the reviewed canonical Pixi layout")

    return tuple(channels), tuple(indexes), references


def _reference_kind(url: str) -> str:
    host = urlsplit(url).hostname
    if host == "conda.anaconda.org":
        return "conda"
    if host == "files.pythonhosted.org":
        return "pypi"
    raise AuditError(f"package reference host is not allowlisted: {url}")


def _split_package_url(url: str):
    if CONTROL_RE.search(url) or "\\" in url:
        raise AuditError(
            f"package URL contains a forbidden control or backslash: {url!r}"
        )
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AuditError(f"package URL is malformed: {url!r}") from exc
    if parsed.scheme != "https":
        raise AuditError(f"package does not use HTTPS: {url}")
    if parsed.username or parsed.password:
        raise AuditError(f"package URL contains credentials: {url}")
    if port is not None:
        raise AuditError(f"package URL contains an explicit port: {url}")
    if parsed.query or parsed.fragment:
        raise AuditError(f"package URL contains a query or fragment: {url}")
    return parsed


def _canonical_decoded_path(path: str, url: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", path):
        raise AuditError(f"package URL contains malformed percent encoding: {url}")
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeDecodeError as exc:
        raise AuditError(f"package URL path is not valid UTF-8: {url}") from exc
    if decoded != path:
        raise AuditError(
            f"package URL path must use canonical decoded components, not percent-encoded ones: {url}"
        )
    if CONTROL_RE.search(decoded) or "\\" in decoded:
        raise AuditError(f"package URL path contains a forbidden character: {url!r}")
    return decoded


def _validate_url(ecosystem: str, url: str) -> tuple[str, str | None]:
    parsed = _split_package_url(url)
    path = _canonical_decoded_path(parsed.path, url)

    if ecosystem == "conda":
        if parsed.netloc != "conda.anaconda.org":
            raise AuditError(f"Conda package host is not allowlisted: {url}")
        parts = path.split("/")
        if len(parts) != 4 or parts[0]:
            raise AuditError(
                f"Conda package path must contain exactly channel/subdirectory/archive: {url}"
            )
        channel, subdirectory, filename = parts[1:]
        if channel not in CONDA_CHANNEL_COMPONENTS:
            raise AuditError(f"Conda package channel is not allowlisted: {url}")
        if subdirectory not in CONDA_SUBDIRECTORIES:
            raise AuditError(f"Conda package subdirectory is not allowlisted: {url}")
        if not CONDA_FILENAME_RE.fullmatch(filename):
            raise AuditError(f"Conda package archive name is not canonical: {url}")
        if not filename.endswith((".conda", ".tar.bz2")):
            raise AuditError(f"Conda package has an unexpected archive suffix: {url}")
    elif ecosystem == "pypi":
        if parsed.netloc != "files.pythonhosted.org":
            raise AuditError(f"PyPI package source is not allowlisted: {url}")
        parts = path.split("/")
        if (
            len(parts) != 6
            or parts[0]
            or parts[1] != "packages"
            or not re.fullmatch(r"[0-9a-f]{2}", parts[2])
            or not re.fullmatch(r"[0-9a-f]{2}", parts[3])
            or not PYPI_PATH_HASH_RE.fullmatch(parts[4])
        ):
            raise AuditError(f"PyPI package path is not canonical: {url}")
        filename = parts[5]
        if not filename.endswith((".whl", ".tar.gz", ".zip")):
            raise AuditError(f"PyPI package has an unexpected archive suffix: {url}")
    else:  # pragma: no cover - protected by the record parser
        raise AuditError(f"unsupported package ecosystem: {ecosystem}")
    return filename, subdirectory if ecosystem == "conda" else None


def _conda_identity(filename: str, url: str) -> tuple[str, str, str]:
    for suffix in (".tar.bz2", ".conda"):
        if filename.endswith(suffix):
            stem = filename[: -len(suffix)]
            break
    else:  # pragma: no cover - checked by _validate_url
        raise AuditError(f"cannot identify Conda archive: {url}")
    parts = stem.rsplit("-", 2)
    if len(parts) != 3 or not all(parts):
        raise AuditError(f"cannot derive Conda name/version/build from: {url}")
    return parts[0], parts[1], parts[2]


def _canonical_project_name(name: str, source: str) -> str:
    if not PROJECT_NAME_RE.fullmatch(name):
        raise AuditError(f"invalid Python distribution name in {source}: {name!r}")
    return re.sub(r"[-_.]+", "-", name).lower()


def _pep440_key(version: str, source: str) -> tuple[object, ...]:
    match = PEP440_RE.fullmatch(version)
    if match is None:
        raise AuditError(f"invalid PEP 440 version in {source}: {version!r}")
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre_label = match.group("pre_l")
    if pre_label is None:
        pre = None
    else:
        normalized_pre = {
            "alpha": "a",
            "a": "a",
            "beta": "b",
            "b": "b",
            "c": "rc",
            "pre": "rc",
            "preview": "rc",
            "rc": "rc",
        }[pre_label.lower()]
        pre = (normalized_pre, int(match.group("pre_n") or 0))
    post_number = match.group("post_n1") or match.group("post_n2")
    post = (
        int(post_number or 0)
        if post_number is not None or match.group("post_l") is not None
        else None
    )
    dev = int(match.group("dev_n") or 0) if match.group("dev_l") is not None else None
    local_text = match.group("local")
    local = None
    if local_text is not None:
        local = tuple(
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"[-_.]", local_text)
        )
    return (int(match.group("epoch") or 0), tuple(release), pre, post, dev, local)


def _wheel_tag_component(value: str, label: str, url: str) -> tuple[str, ...]:
    if not WHEEL_TAG_RE.fullmatch(value):
        raise AuditError(f"invalid wheel {label} tag in {url}: {value!r}")
    return tuple(value.split("."))


def _pypi_identity(
    filename: str, name: str, version: str, url: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    locked_name = _canonical_project_name(name, url)
    locked_version = _pep440_key(version, url)
    wheel_tags = None
    if filename.endswith(".whl"):
        components = filename[:-4].split("-")
        if len(components) == 5:
            archive_name, archive_version, python_tag, abi_tag, platform_tag = (
                components
            )
        elif len(components) == 6:
            (
                archive_name,
                archive_version,
                build_tag,
                python_tag,
                abi_tag,
                platform_tag,
            ) = components
            if not re.fullmatch(r"[0-9][A-Za-z0-9_]*", build_tag):
                raise AuditError(f"invalid or ambiguous wheel build tag in {url}")
        else:
            raise AuditError(
                f"wheel filename has ambiguous component boundaries: {url}"
            )
        if not WHEEL_NAME_RE.fullmatch(archive_name):
            raise AuditError(
                f"wheel distribution component is not escaped canonically: {url}"
            )
        wheel_tags = (
            _wheel_tag_component(python_tag, "Python", url),
            _wheel_tag_component(abi_tag, "ABI", url),
            _wheel_tag_component(platform_tag, "platform", url),
        )
    else:
        suffix = ".tar.gz" if filename.endswith(".tar.gz") else ".zip"
        stem = filename[: -len(suffix)]
        if stem.count("-") != 1:
            raise AuditError(
                f"sdist filename has ambiguous component boundaries: {url}"
            )
        archive_name, archive_version = stem.split("-", 1)
        if not archive_name or not archive_version:
            raise AuditError(
                f"sdist filename is missing a distribution or version: {url}"
            )
        if not WHEEL_NAME_RE.fullmatch(archive_name):
            raise AuditError(
                f"sdist distribution component is not escaped canonically: {url}"
            )

    archive_name_key = _canonical_project_name(archive_name, url)
    archive_version_key = _pep440_key(archive_version, url)
    if archive_name_key != locked_name or archive_version_key != locked_version:
        raise AuditError(
            "PyPI archive identity does not match locked name/version metadata: "
            f"{url} declares {name} {version}"
        )
    return wheel_tags


def _wheel_supports_platform(
    wheel_tags: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    platform: str,
    url: str,
) -> None:
    _python_tags, abi_tags, platform_tags = wheel_tags
    if "any" in platform_tags and any(tag != "none" for tag in abi_tags):
        raise AuditError(f"wheel uses platform 'any' with a non-none ABI tag: {url}")

    def matches(tag: str) -> bool:
        if tag == "any":
            return True
        if platform == "win-64":
            return tag == "win_amd64"
        if platform == "linux-64":
            return tag in (
                "linux_x86_64",
                "manylinux1_x86_64",
                "manylinux2010_x86_64",
                "manylinux2014_x86_64",
            ) or bool(
                re.fullmatch(r"(?:manylinux|musllinux)_[0-9]+_[0-9]+_x86_64", tag)
            )
        if platform == "linux-aarch64":
            return tag in (
                "linux_aarch64",
                "manylinux2014_aarch64",
            ) or bool(
                re.fullmatch(r"(?:manylinux|musllinux)_[0-9]+_[0-9]+_aarch64", tag)
            )
        if platform == "osx-64":
            return bool(
                re.fullmatch(
                    r"macosx_[0-9]+_[0-9]+_(?:x86_64|intel|fat64|universal2)", tag
                )
            )
        if platform == "osx-arm64":
            return bool(re.fullmatch(r"macosx_[0-9]+_[0-9]+_(?:arm64|universal2)", tag))
        return False

    if not any(matches(tag) for tag in platform_tags):
        raise AuditError(f"PyPI wheel platform tags do not support {platform}: {url}")


def _finish_package(ecosystem: str, url: str, fields: dict[str, str]) -> LockedPackage:
    filename, subdirectory = _validate_url(ecosystem, url)
    digest = fields.get("sha256", "")
    if not SHA256_RE.fullmatch(digest):
        raise AuditError(f"package is missing a canonical SHA-256 digest: {url}")

    if ecosystem == "conda":
        name, version, build = _conda_identity(filename, url)
        md5 = fields.get("md5")
        if md5 is not None and not MD5_RE.fullmatch(md5):
            raise AuditError(f"Conda package has a noncanonical MD5 field: {url}")
        for numeric_field in ("build_number", "size", "timestamp"):
            value = fields.get(numeric_field)
            if value is not None and not re.fullmatch(r"0|[1-9][0-9]*", value):
                raise AuditError(
                    f"Conda package has a noncanonical {numeric_field} field: {url}"
                )
        noarch = fields.get("noarch")
        if noarch is not None:
            if noarch not in ("generic", "python"):
                raise AuditError(f"Conda package has an invalid noarch type: {url}")
            if subdirectory != "noarch":
                raise AuditError(f"Conda noarch metadata disagrees with its URL: {url}")
        wheel_tags = None
    else:
        name = fields.get("name", "")
        version = fields.get("version", "")
        build = None
        if not name or not version:
            raise AuditError(f"PyPI package is missing name or version metadata: {url}")
        wheel_tags = _pypi_identity(filename, name, version, url)

    reported_license = fields.get("license")
    if reported_license in (None, "", "None"):
        reported_license = None
    return LockedPackage(
        ecosystem=ecosystem,
        url=url,
        filename=filename,
        subdirectory=subdirectory,
        wheel_tags=wheel_tags,
        sha256=digest,
        name=name,
        version=version,
        build=build,
        reported_license=reported_license,
    )


def _parse_packages(lines: list[str]) -> tuple[LockedPackage, ...]:
    packages: list[LockedPackage] = []
    ecosystem: str | None = None
    url = ""
    fields: dict[str, str] = {}
    seen_fields: set[str] = set()
    active_list: str | None = None
    active_list_items = 0

    def close_list() -> None:
        nonlocal active_list, active_list_items
        if active_list is not None and active_list_items == 0:
            raise AuditError(
                f"package list field {active_list!r} must contain entries or use []: {url}"
            )
        active_list = None
        active_list_items = 0

    def finish_current() -> None:
        nonlocal ecosystem, url, fields, seen_fields
        if ecosystem is not None:
            close_list()
            packages.append(_finish_package(ecosystem, url, fields))
        ecosystem = None
        url = ""
        fields = {}
        seen_fields = set()

    for line in lines:
        package_match = PACKAGE_START_RE.fullmatch(line)
        if package_match:
            finish_current()
            ecosystem, url = package_match.groups()
            continue
        if line.startswith("- "):
            raise AuditError(f"unexpected top-level package record: {line}")
        if ecosystem is None:
            raise AuditError(f"content appears before a package record: {line!r}")

        list_item_match = LIST_ITEM_RE.fullmatch(line)
        if list_item_match:
            if active_list is None:
                raise AuditError(f"orphan package list item for {url}: {line}")
            value = list_item_match.group(1)
            _package_list_scalar(active_list, value, url)
            active_list_items += 1
            continue

        field_match = FIELD_RE.fullmatch(line)
        if field_match:
            close_list()
            key, value = field_match.groups()
            allowed_scalars = PACKAGE_SCALAR_FIELDS[ecosystem]
            allowed_lists = PACKAGE_LIST_FIELDS[ecosystem]
            if key not in allowed_scalars and key not in allowed_lists:
                raise AuditError(
                    f"unexpected {key!r} field in {ecosystem} package record: {url}"
                )
            if key in seen_fields:
                raise AuditError(f"duplicate {key!r} field for package {url}")
            seen_fields.add(key)
            if key in allowed_lists:
                if value is None:
                    active_list = key
                elif value != "[]":
                    raise AuditError(
                        f"package list field {key!r} must use a YAML list or []: {url}"
                    )
                continue
            if key in PACKAGE_INTEGER_FIELDS[ecosystem]:
                fields[key] = _integer_scalar(
                    value, f"integer {key!r} for package {url}"
                )
            else:
                fields[key] = _package_scalar(ecosystem, key, value, url)
            continue

        raise AuditError(f"unexpected package record schema for {url}: {line!r}")

    finish_current()
    if not packages:
        raise AuditError("lock file contains no package records")
    return tuple(packages)


def _integer_scalar(value: str | None, context: str) -> str:
    if value is None or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise AuditError(f"invalid canonical non-negative {context}")
    return value


def _string_scalar(value: str | None, context: str) -> str:
    if value is None or not value or value != value.strip() or CONTROL_RE.search(value):
        raise AuditError(f"invalid {context}")
    if value[0] in "'\"":
        raise AuditError(f"unsupported quoted {context}")
    decoded = value
    if (
        value[0] in "-?:[]{},&*!|>%@`"
        or value == "..."
        or ": " in value
        or YAML_COMMENT_RE.search(value)
        or YAML_REFERENCE_RE.search(value)
        or YAML_NON_STRING_RE.fullmatch(value)
        or YAML_INTEGER_RE.fullmatch(value)
        or YAML_FLOAT_RE.fullmatch(value)
        or YAML_TIMESTAMP_RE.fullmatch(value)
    ):
        raise AuditError(f"unsupported non-string YAML form in {context}")
    if not decoded or CONTROL_RE.search(decoded):
        raise AuditError(f"invalid {context}")
    return decoded


def _canonical_yaml_string_scalar(value: str | None, context: str) -> str:
    if value is None or not value or value != value.strip() or CONTROL_RE.search(value):
        raise AuditError(f"invalid {context}")
    if value[0] != "'":
        return _string_scalar(value, context)
    if len(value) < 2 or value[-1] != "'":
        raise AuditError(f"unsupported quoted {context}")
    encoded = value[1:-1]
    pieces: list[str] = []
    index = 0
    while index < len(encoded):
        if encoded[index] != "'":
            pieces.append(encoded[index])
            index += 1
        elif index + 1 < len(encoded) and encoded[index + 1] == "'":
            pieces.append("'")
            index += 2
        else:
            raise AuditError(f"unsupported quoted {context}")
    decoded = "".join(pieces)
    if not decoded or CONTROL_RE.search(decoded):
        raise AuditError(f"invalid {context}")
    return decoded


def _validate_requires_python(value: str, url: str) -> None:
    for specifier in value.split(","):
        match = PEP440_SPECIFIER_RE.fullmatch(specifier)
        if match is None:
            raise AuditError(f"invalid requires_python specifier for {url}: {value!r}")
        operator, version = match.groups()
        if operator == "===":
            continue
        wildcard = version.endswith(".*")
        if wildcard:
            if operator not in ("==", "!="):
                raise AuditError(
                    f"requires_python wildcard uses an invalid operator for {url}: {value!r}"
                )
            version = version[:-2]
        _pep440_key(version, f"requires_python for {url}")


def _package_scalar(ecosystem: str, field: str, value: str | None, url: str) -> str:
    context = f"scalar {field!r} for package {url}"
    decoded = _canonical_yaml_string_scalar(value, context)
    if field == "sha256" and SHA256_RE.fullmatch(decoded) is None:
        raise AuditError(f"invalid canonical {context}")
    if field == "md5" and MD5_RE.fullmatch(decoded) is None:
        raise AuditError(f"invalid canonical {context}")
    if field == "name":
        _canonical_project_name(decoded, url)
    elif field == "version":
        _pep440_key(decoded, url)
    elif field == "requires_python":
        _validate_requires_python(decoded, url)
    elif field == "noarch" and decoded not in ("generic", "python"):
        raise AuditError(f"invalid canonical {context}")
    elif (
        field in ("license", "license_family")
        and METADATA_TEXT_RE.fullmatch(decoded) is None
    ):
        raise AuditError(f"invalid canonical {context}")
    return decoded


def _package_list_scalar(field: str, value: str | None, url: str) -> str:
    context = f"{field!r} list item for package {url}"
    decoded = _string_scalar(value, context)
    grammar = {
        "depends": CONDA_MATCHSPEC_RE,
        "constrains": CONDA_MATCHSPEC_RE,
        "purls": PURL_RE,
        "track_features": TRACK_FEATURE_RE,
        "requires_dist": PYPI_REQUIREMENT_RE,
    }[field]
    if grammar.fullmatch(decoded) is None:
        raise AuditError(f"invalid canonical {context}")
    return decoded


def audit_lock(path: Path) -> AuditResult:
    text, lock_sha256 = _decode_lock(path)
    lines = text.splitlines()
    package_anchors = [index for index, line in enumerate(lines) if line == "packages:"]
    if len(package_anchors) != 1:
        raise AuditError("expected exactly one top-level packages section")
    package_anchor = package_anchors[0]
    channels, indexes, references = _parse_header(lines[:package_anchor])
    packages = _parse_packages(lines[package_anchor + 1 :])

    urls = [package.url for package in packages]
    digests = [package.sha256 for package in packages]
    if len(urls) != len(set(urls)):
        raise AuditError("lock file contains duplicate package URLs")
    if len(digests) != len(set(digests)):
        raise AuditError("lock file contains duplicate package SHA-256 digests")

    referenced_urls = [
        url for platform_urls in references.values() for url in platform_urls
    ]
    unknown = sorted(set(referenced_urls).difference(urls))
    unused = sorted(set(urls).difference(referenced_urls))
    if unknown:
        raise AuditError(
            f"environment references missing package metadata: {unknown[:3]!r}"
        )
    package_by_url = {package.url: package for package in packages}
    for platform, platform_urls in references.items():
        for url in platform_urls:
            package = package_by_url[url]
            if package.ecosystem == "conda" and package.subdirectory not in (
                platform,
                "noarch",
            ):
                raise AuditError(
                    f"Conda package subdirectory does not match platform {platform}: {url}"
                )
            if package.wheel_tags is not None:
                _wheel_supports_platform(package.wheel_tags, platform, url)
    if unused:
        raise AuditError(f"unreferenced package metadata is forbidden: {unused[:3]!r}")

    return AuditResult(
        lock_sha256=lock_sha256,
        channels=channels,
        indexes=indexes,
        platforms=tuple(references),
        platform_references=tuple(
            (platform, tuple(platform_urls))
            for platform, platform_urls in references.items()
        ),
        reference_count=len(referenced_urls),
        packages=packages,
    )


def source_provenance(source_date_epoch: str, source_revision: str) -> SourceProvenance:
    if not re.fullmatch(r"0|[1-9][0-9]*", source_date_epoch):
        raise AuditError(
            "source date epoch must be a canonical non-negative Unix timestamp"
        )
    if not SOURCE_REVISION_RE.fullmatch(source_revision):
        raise AuditError("source revision must be a full lowercase Git object ID")
    try:
        instant = datetime.fromtimestamp(int(source_date_epoch), timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise AuditError(
            "source date epoch is outside the supported timestamp range"
        ) from exc
    return SourceProvenance(
        created=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        revision=source_revision,
    )


def make_spdx(result: AuditResult, provenance: SourceProvenance) -> dict[str, object]:
    root_id = "SPDXRef-PixiLock"
    package_entries: list[dict[str, object]] = [
        {
            "SPDXID": root_id,
            "name": "openfusion-pixi-lock",
            "versionInfo": result.lock_sha256,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "comment": (
                "All-platform build and development dependency lock. "
                "This is not an inventory of a final OpenFusion runtime package. "
                + CHECKSUM_DISCLOSURE
            ),
        }
    ]
    relationships: list[dict[str, str]] = []

    for package in result.packages:
        package_id = f"SPDXRef-{package.ecosystem}-{package.sha256}"
        comment_parts = [f"Ecosystem: {package.ecosystem}"]
        if package.build:
            comment_parts.append(f"Conda build: {package.build}")
        if package.reported_license:
            comment_parts.append(
                f"Pixi lock reported license: {package.reported_license}"
            )
        comment_parts.append(CHECKSUM_DISCLOSURE)
        package_entries.append(
            {
                "SPDXID": package_id,
                "name": package.name,
                "versionInfo": package.version,
                "downloadLocation": package.url,
                "packageFileName": package.filename,
                "checksums": [{"algorithm": "SHA256", "checksumValue": package.sha256}],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "comment": "; ".join(comment_parts),
            }
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package_id,
            }
        )

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"openfusion-pixi-lock-{result.lock_sha256[:12]}",
        "comment": CHECKSUM_DISCLOSURE,
        "documentNamespace": (
            "https://github.com/PLASMA-FR/openfusion/sbom/pixi-lock/"
            f"{provenance.revision}/{result.lock_sha256}"
        ),
        "creationInfo": {
            "created": provenance.created,
            "creators": ["Tool: OpenFusion pixi-lock-audit/1"],
            "comment": f"Source revision: {provenance.revision}",
        },
        "documentDescribes": [root_id],
        "packages": package_entries,
        "relationships": relationships,
    }


def make_report(result: AuditResult, provenance: SourceProvenance) -> dict[str, object]:
    conda_count = sum(package.ecosystem == "conda" for package in result.packages)
    pypi_count = sum(package.ecosystem == "pypi" for package in result.packages)
    return {
        "schema_version": 1,
        "status": "passed",
        "scope": "all-platform-pixi-source-lock",
        "is_final_runtime_sbom": False,
        "archive_bytes_verified": False,
        "created": provenance.created,
        "source_revision": provenance.revision,
        "lock_sha256": result.lock_sha256,
        "channels": list(result.channels),
        "indexes": list(result.indexes),
        "platforms": list(result.platforms),
        "environment_reference_count": result.reference_count,
        "platform_reference_counts": {
            platform: len(urls) for platform, urls in result.platform_references
        },
        "unique_package_count": len(result.packages),
        "conda_package_count": conda_count,
        "pypi_package_count": pypi_count,
        "checksum_disclosure": CHECKSUM_DISCLOSURE,
        "metadata_validation": (
            "Every referenced package record has a unique canonical HTTPS URL and "
            "an asserted SHA-256 digest; archive bytes were not downloaded or hashed."
        ),
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists() and path.is_symlink():
        raise AuditError(f"refusing to replace symbolic link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("pixi.lock"))
    parser.add_argument("--source-date-epoch", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--spdx-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        provenance = source_provenance(args.source_date_epoch, args.source_revision)
        result = audit_lock(args.lock)
        _write_json(args.spdx_out, make_spdx(result, provenance))
        _write_json(args.report_out, make_report(result, provenance))
    except AuditError as exc:
        print(f"Pixi lock audit failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Pixi lock audit passed: "
        f"{len(result.packages)} unique packages, "
        f"{result.reference_count} platform references, "
        f"SHA-256 {result.lock_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
