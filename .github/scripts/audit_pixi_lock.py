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
import os
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
PACKAGE_START_RE = re.compile(r"^- (conda|pypi): (\S+)$")
SCALAR_RE = re.compile(r"^  ([a-z][a-z0-9_]*): (.*)$")
REFERENCE_RE = re.compile(r"^      - (conda|pypi): (\S+)$")
PLATFORM_RE = re.compile(r"^      ([a-z0-9-]+):$")


class AuditError(ValueError):
    """The dependency lock violates the audited format or source policy."""


@dataclass(frozen=True)
class LockedPackage:
    ecosystem: str
    url: str
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
    reference_count: int
    packages: tuple[LockedPackage, ...]


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
            "Pixi platforms changed from the reviewed matrix: " + repr(tuple(references))
        )
    for platform_name, platform_references in references.items():
        if not platform_references:
            raise AuditError(f"platform {platform_name} has no locked package references")
        if len(platform_references) != len(set(platform_references)):
            raise AuditError(f"platform {platform_name} contains duplicate package references")

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


def _validate_url(ecosystem: str, url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise AuditError(f"{ecosystem} package does not use HTTPS: {url}")
    if parsed.username or parsed.password:
        raise AuditError(f"package URL contains credentials: {url}")
    if parsed.query or parsed.fragment:
        raise AuditError(f"package URL contains a query or fragment: {url}")

    if ecosystem == "conda":
        if parsed.netloc != "conda.anaconda.org":
            raise AuditError(f"Conda package host is not allowlisted: {url}")
        if not any(url.startswith(channel) for channel in EXPECTED_CHANNELS):
            raise AuditError(f"Conda package channel is not allowlisted: {url}")
        if not parsed.path.endswith((".conda", ".tar.bz2")):
            raise AuditError(f"Conda package has an unexpected archive suffix: {url}")
    elif ecosystem == "pypi":
        if parsed.netloc != "files.pythonhosted.org" or not parsed.path.startswith(
            "/packages/"
        ):
            raise AuditError(f"PyPI package source is not allowlisted: {url}")
        if not parsed.path.endswith((".whl", ".tar.gz", ".zip")):
            raise AuditError(f"PyPI package has an unexpected archive suffix: {url}")
    else:  # pragma: no cover - protected by the record parser
        raise AuditError(f"unsupported package ecosystem: {ecosystem}")


def _conda_identity(url: str) -> tuple[str, str, str]:
    filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
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


def _finish_package(ecosystem: str, url: str, fields: dict[str, str]) -> LockedPackage:
    _validate_url(ecosystem, url)
    digest = fields.get("sha256", "")
    if not SHA256_RE.fullmatch(digest):
        raise AuditError(f"package is missing a canonical SHA-256 digest: {url}")

    if ecosystem == "conda":
        name, version, build = _conda_identity(url)
    else:
        name = fields.get("name", "")
        version = fields.get("version", "")
        build = None
        if not name or not version:
            raise AuditError(f"PyPI package is missing name or version metadata: {url}")

    reported_license = fields.get("license")
    if reported_license in (None, "", "None"):
        reported_license = None
    return LockedPackage(
        ecosystem=ecosystem,
        url=url,
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

    def finish_current() -> None:
        nonlocal ecosystem, url, fields
        if ecosystem is not None:
            packages.append(_finish_package(ecosystem, url, fields))
        ecosystem = None
        url = ""
        fields = {}

    for line in lines:
        package_match = PACKAGE_START_RE.fullmatch(line)
        if package_match:
            finish_current()
            ecosystem, url = package_match.groups()
            continue
        if line.startswith("- "):
            raise AuditError(f"unexpected top-level package record: {line}")
        if line and not line.startswith(" "):
            raise AuditError(f"unexpected top-level content in package section: {line}")
        scalar_match = SCALAR_RE.fullmatch(line)
        if ecosystem is not None and scalar_match:
            key, value = scalar_match.groups()
            if key in fields:
                raise AuditError(f"duplicate {key!r} field for package {url}")
            fields[key] = value.strip("'\"")

    finish_current()
    if not packages:
        raise AuditError("lock file contains no package records")
    return tuple(packages)


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

    referenced_urls = [url for platform_urls in references.values() for url in platform_urls]
    unknown = sorted(set(referenced_urls).difference(urls))
    unused = sorted(set(urls).difference(referenced_urls))
    if unknown:
        raise AuditError(f"environment references missing package metadata: {unknown[:3]!r}")
    if unused:
        raise AuditError(f"unreferenced package metadata is forbidden: {unused[:3]!r}")

    return AuditResult(
        lock_sha256=lock_sha256,
        channels=channels,
        indexes=indexes,
        platforms=tuple(references),
        reference_count=len(referenced_urls),
        packages=packages,
    )


def _spdx_created() -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is None:
        instant = datetime.now(timezone.utc)
    else:
        try:
            seconds = int(source_date_epoch)
            if seconds < 0:
                raise ValueError
            instant = datetime.fromtimestamp(seconds, timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise AuditError("SOURCE_DATE_EPOCH must be a non-negative Unix timestamp") from exc
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_spdx(result: AuditResult) -> dict[str, object]:
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
                "This is not an inventory of a final OpenFusion runtime package."
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
            comment_parts.append(f"Pixi lock reported license: {package.reported_license}")
        package_entries.append(
            {
                "SPDXID": package_id,
                "name": package.name,
                "versionInfo": package.version,
                "downloadLocation": package.url,
                "packageFileName": unquote(urlsplit(package.url).path.rsplit("/", 1)[-1]),
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": package.sha256}
                ],
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
        "documentNamespace": (
            "https://github.com/PLASMA-FR/openfusion/sbom/pixi-lock/"
            + result.lock_sha256
        ),
        "creationInfo": {
            "created": _spdx_created(),
            "creators": ["Tool: OpenFusion pixi-lock-audit/1"],
        },
        "documentDescribes": [root_id],
        "packages": package_entries,
        "relationships": relationships,
    }


def make_report(result: AuditResult) -> dict[str, object]:
    conda_count = sum(package.ecosystem == "conda" for package in result.packages)
    pypi_count = sum(package.ecosystem == "pypi" for package in result.packages)
    return {
        "schema_version": 1,
        "status": "passed",
        "scope": "all-platform-pixi-source-lock",
        "is_final_runtime_sbom": False,
        "lock_sha256": result.lock_sha256,
        "channels": list(result.channels),
        "indexes": list(result.indexes),
        "platforms": list(result.platforms),
        "environment_reference_count": result.reference_count,
        "unique_package_count": len(result.packages),
        "conda_package_count": conda_count,
        "pypi_package_count": pypi_count,
        "integrity": "Every package has a unique HTTPS URL and SHA-256 digest.",
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
    parser.add_argument("--spdx-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = audit_lock(args.lock)
        _write_json(args.spdx_out, make_spdx(result))
        _write_json(args.report_out, make_report(result))
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
