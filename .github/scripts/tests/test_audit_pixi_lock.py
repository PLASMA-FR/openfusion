#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 OpenFusion contributors

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "audit_pixi_lock.py"
SPEC = importlib.util.spec_from_file_location("audit_pixi_lock", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit_pixi_lock = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_pixi_lock
SPEC.loader.exec_module(audit_pixi_lock)

CONDA_URLS = {
    platform: (
        f"https://conda.anaconda.org/conda-forge/{platform}/"
        "example-lib-1.2.3-h123_0.conda"
    )
    for platform in audit_pixi_lock.EXPECTED_PLATFORMS
}
CONDA_SHAS = {
    platform: f"{index:x}" + "a" * 63
    for index, platform in enumerate(audit_pixi_lock.EXPECTED_PLATFORMS, start=1)
}
CONDA_URL = CONDA_URLS["linux-64"]
CONDA_SHA = CONDA_SHAS["linux-64"]
PYPI_URL = (
    f"https://files.pythonhosted.org/packages/ab/cd/{'e' * 60}/"
    "example_py-2.0.0-py3-none-any.whl"
)
PYPI_SHA = "f" * 64
PLATFORM_WHEEL_SHA = "d" * 64
SOURCE_DATE_EPOCH = "0"
SOURCE_REVISION = "0123456789abcdef0123456789abcdef01234567"


def valid_lock() -> str:
    references = []
    for platform in audit_pixi_lock.EXPECTED_PLATFORMS:
        references.extend(
            [
                f"      {platform}:",
                f"      - conda: {CONDA_URLS[platform]}",
                f"      - pypi: {PYPI_URL}",
            ]
        )
    package_records = []
    for platform in audit_pixi_lock.EXPECTED_PLATFORMS:
        package_records.extend(
            [
                f"- conda: {CONDA_URLS[platform]}",
                f"  sha256: {CONDA_SHAS[platform]}",
                "  build_number: 0",
                "  track_features: []",
            ]
        )
    return "\n".join(
        [
            "version: 6",
            "environments:",
            "  default:",
            "    channels:",
            "    - url: https://conda.anaconda.org/freecad/",
            "    - url: https://conda.anaconda.org/conda-forge/",
            "    indexes:",
            "    - https://pypi.org/simple",
            "    packages:",
            *references,
            "packages:",
            *package_records,
            f"- pypi: {PYPI_URL}",
            "  name: example-py",
            "  version: 2.0.0",
            f"  sha256: {PYPI_SHA}",
            "",
        ]
    )


def lock_with_platform_wheel(platform: str, platform_tag: str) -> str:
    wheel_url = PYPI_URL.replace("py3-none-any.whl", f"cp311-cp311-{platform_tag}.whl")
    platform_references = "\n".join(
        (
            f"      {platform}:",
            f"      - conda: {CONDA_URLS[platform]}",
            f"      - pypi: {PYPI_URL}",
        )
    )
    replacement_references = platform_references.replace(PYPI_URL, wheel_url)
    return valid_lock().replace(
        platform_references, replacement_references, 1
    ) + "\n".join(
        (
            f"- pypi: {wheel_url}",
            "  name: example-py",
            "  version: 2.0.0",
            f"  sha256: {PLATFORM_WHEEL_SHA}",
            "",
        )
    )


class PixiLockAuditTest(unittest.TestCase):
    def write_lock(self, directory: Path, contents: str) -> Path:
        path = directory / "pixi.lock"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_valid_lock_generates_truthfully_scoped_spdx(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), valid_lock())
            result = audit_pixi_lock.audit_lock(lock_path)
            provenance = audit_pixi_lock.source_provenance(
                SOURCE_DATE_EPOCH, SOURCE_REVISION
            )
            spdx = audit_pixi_lock.make_spdx(result, provenance)

        self.assertEqual(len(result.packages), 6)
        self.assertEqual(result.reference_count, 10)
        self.assertEqual(spdx["spdxVersion"], "SPDX-2.3")
        self.assertEqual(spdx["creationInfo"]["created"], "1970-01-01T00:00:00Z")
        self.assertIn(SOURCE_REVISION, spdx["documentNamespace"])
        self.assertEqual(len(spdx["packages"]), 7)
        self.assertIn(
            "not an inventory of a final OpenFusion runtime",
            spdx["packages"][0]["comment"],
        )
        self.assertTrue(
            all(p["licenseDeclared"] == "NOASSERTION" for p in spdx["packages"])
        )
        self.assertEqual(spdx["comment"], audit_pixi_lock.CHECKSUM_DISCLOSURE)
        self.assertTrue(
            all(
                audit_pixi_lock.CHECKSUM_DISCLOSURE in p["comment"]
                for p in spdx["packages"]
            )
        )

    def test_repository_lock_passes(self) -> None:
        repository_lock = Path(__file__).parents[3] / "pixi.lock"
        result = audit_pixi_lock.audit_lock(repository_lock)
        self.assertGreater(len(result.packages), 1000)
        self.assertEqual(set(result.platforms), set(audit_pixi_lock.EXPECTED_PLATFORMS))

    def test_missing_digest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(f"  sha256: {PYPI_SHA}\n", "")
            )
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "SHA-256"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_non_https_package_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir),
                valid_lock().replace(
                    "https://files.pythonhosted.org", "http://files.pythonhosted.org"
                ),
            )
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "does not use HTTPS"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_conda_url_ambiguities_fail_closed(self) -> None:
        variants = (
            (
                "raw traversal",
                CONDA_URL.replace("/linux-64/", "/../linux-64/"),
                "exactly channel/subdirectory/archive",
            ),
            (
                "encoded traversal",
                CONDA_URL.replace("/linux-64/", "/%2e%2e/linux-64/"),
                "canonical decoded components",
            ),
            (
                "encoded separator",
                CONDA_URL.replace("/conda-forge/", "/conda-forge%2Flinux-64/"),
                "canonical decoded components",
            ),
            ("backslash", CONDA_URL.replace("/linux-64/", "\\linux-64/"), "forbidden"),
            (
                "control",
                CONDA_URL.replace("example-lib", "example\x01-lib"),
                "forbidden",
            ),
            ("query", CONDA_URL + "?download=1", "query or fragment"),
            ("fragment", CONDA_URL + "#archive", "query or fragment"),
            ("userinfo", CONDA_URL.replace("https://", "https://user@"), "credentials"),
            (
                "port",
                CONDA_URL.replace("conda.anaconda.org", "conda.anaconda.org:443"),
                "explicit port",
            ),
            (
                "channel prefix",
                CONDA_URL.replace("/conda-forge/", "/conda-forge.evil/"),
                "channel is not allowlisted",
            ),
            (
                "unreviewed subdirectory",
                CONDA_URL.replace("/linux-64/", "/linux-ppc64le/"),
                "subdirectory is not allowlisted",
            ),
        )
        for label, rejected_url, message in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(CONDA_URL, rejected_url)
                )
                with self.assertRaisesRegex(audit_pixi_lock.AuditError, message):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_conda_archive_name_allows_leading_underscore_only(self) -> None:
        valid_url = (
            "https://conda.anaconda.org/conda-forge/linux-64/"
            "_libavif_api-1.3.0-h57928b3_2.conda"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = audit_pixi_lock.audit_lock(
                self.write_lock(
                    Path(temp_dir), valid_lock().replace(CONDA_URL, valid_url)
                )
            )
        self.assertIn(valid_url, (package.url for package in result.packages))

        for leading_character in (".", "-"):
            with self.subTest(
                leading_character=leading_character
            ), tempfile.TemporaryDirectory() as temp_dir:
                invalid_url = valid_url.replace(
                    "_libavif_api", f"{leading_character}libavif_api"
                )
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(CONDA_URL, invalid_url)
                )
                with self.assertRaisesRegex(
                    audit_pixi_lock.AuditError, "archive name is not canonical"
                ):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_unreviewed_channel_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir),
                valid_lock().replace(
                    "https://conda.anaconda.org/freecad/",
                    "https://conda.anaconda.org/unreviewed/",
                    1,
                ),
            )
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "allowlist"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_unreferenced_package_metadata_fails_closed(self) -> None:
        unused_url = "https://conda.anaconda.org/conda-forge/noarch/unused-1.0-0.conda"
        contents = valid_lock() + f"- conda: {unused_url}\n  sha256: {'9' + 'c' * 63}\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), contents)
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "unreferenced"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_duplicate_digest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(PYPI_SHA, CONDA_SHA)
            )
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "duplicate package SHA-256"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_duplicate_platform_reference_fails_closed(self) -> None:
        duplicate = f"      linux-64:\n      - conda: {CONDA_URL}"
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir),
                valid_lock().replace(
                    duplicate,
                    duplicate + f"\n      - conda: {CONDA_URL}",
                    1,
                ),
            )
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "duplicate package references"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_platform_reference_associations_are_retained_and_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), valid_lock())
            result = audit_pixi_lock.audit_lock(lock_path)
        references = dict(result.platform_references)
        self.assertIn(CONDA_URLS["win-64"], references["win-64"])

        swapped = valid_lock().replace(
            f"      - conda: {CONDA_URLS['win-64']}",
            f"      - conda: {CONDA_URLS['linux-64']}",
            1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), swapped)
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "does not match platform"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_pypi_wheel_platform_swap_fails_closed(self) -> None:
        windows_wheel = PYPI_URL.replace(
            "py3-none-any.whl", "cp311-cp311-win_amd64.whl"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(PYPI_URL, windows_wheel)
            )
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "do not support linux-64"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_linux_wheel_policy_tags_are_closed_and_platform_specific(self) -> None:
        valid_tags = {
            "linux-64": (
                "linux_x86_64",
                "manylinux1_x86_64",
                "manylinux2010_x86_64",
                "manylinux2014_x86_64",
                "manylinux_2_17_x86_64",
                "musllinux_1_2_x86_64",
            ),
            "linux-aarch64": (
                "linux_aarch64",
                "manylinux2014_aarch64",
                "manylinux_2_17_aarch64",
                "musllinux_1_2_aarch64",
            ),
        }
        for platform, tags in valid_tags.items():
            for tag in tags:
                with self.subTest(
                    platform=platform, tag=tag
                ), tempfile.TemporaryDirectory() as temp_dir:
                    audit_pixi_lock.audit_lock(
                        self.write_lock(
                            Path(temp_dir), lock_with_platform_wheel(platform, tag)
                        )
                    )

        invalid_tags = (
            ("linux-64", "manylinuxevil_x86_64"),
            ("linux-aarch64", "manylinuxevil_aarch64"),
        )
        for platform, tag in invalid_tags:
            with self.subTest(
                platform=platform, tag=tag
            ), tempfile.TemporaryDirectory() as temp_dir:
                with self.assertRaisesRegex(
                    audit_pixi_lock.AuditError, f"do not support {platform}"
                ):
                    audit_pixi_lock.audit_lock(
                        self.write_lock(
                            Path(temp_dir), lock_with_platform_wheel(platform, tag)
                        )
                    )

    def test_platform_any_requires_a_none_abi(self) -> None:
        invalid_wheel = PYPI_URL.replace("py3-none-any.whl", "cp311-cp311-any.whl")
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(PYPI_URL, invalid_wheel)
            )
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "non-none ABI"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_noncanonical_header_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir),
                valid_lock().replace(
                    "environments:\n", "environments:\n# injected\n", 1
                ),
            )
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "canonical Pixi layout"
            ):
                audit_pixi_lock.audit_lock(lock_path)

    def test_pypi_wheel_identity_must_match_locked_metadata(self) -> None:
        variants = (
            ("name metadata", "  name: example-py", "  name: different"),
            ("version metadata", "  version: 2.0.0", "  version: 2.0.1"),
            ("filename name", "example_py-2.0.0", "different-2.0.0"),
            ("filename version", "example_py-2.0.0", "example_py-2.0.1"),
        )
        for label, old, new in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(old, new)
                )
                with self.assertRaisesRegex(
                    audit_pixi_lock.AuditError, "identity does not match"
                ):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_pypi_sdist_identity_is_parsed(self) -> None:
        sdist_url = PYPI_URL.replace(
            "example_py-2.0.0-py3-none-any.whl", "example_py-2.0.0.tar.gz"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(PYPI_URL, sdist_url)
            )
            result = audit_pixi_lock.audit_lock(lock_path)
        package = next(
            package for package in result.packages if package.ecosystem == "pypi"
        )
        self.assertEqual(package.filename, "example_py-2.0.0.tar.gz")

    def test_pypi_standard_normalizations_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            normalized = valid_lock().replace(
                "  name: example-py", "  name: Example...Py"
            )
            normalized = normalized.replace("  version: 2.0.0", "  version: v2.0.0.0")
            result = audit_pixi_lock.audit_lock(
                self.write_lock(Path(temp_dir), normalized)
            )
        self.assertEqual(
            next(
                package.name
                for package in result.packages
                if package.ecosystem == "pypi"
            ),
            "Example...Py",
        )

    def test_requires_python_accepts_canonical_single_quoted_specifiers(self) -> None:
        for specifier in (">=3.6", ">=3.7"):
            with self.subTest(
                specifier=specifier
            ), tempfile.TemporaryDirectory() as temp_dir:
                contents = valid_lock().replace(
                    f"  sha256: {PYPI_SHA}\n",
                    f"  sha256: {PYPI_SHA}\n  requires_python: '{specifier}'\n",
                )
                result = audit_pixi_lock.audit_lock(
                    self.write_lock(Path(temp_dir), contents)
                )
            package = next(
                package for package in result.packages if package.ecosystem == "pypi"
            )
            self.assertEqual(package.version, "2.0.0")

    def test_single_quoted_scalar_decodes_doubled_apostrophes(self) -> None:
        contents = valid_lock().replace(
            "  track_features: []\n",
            "  track_features: []\n  license: 'OpenFusion''s Test License'\n",
            1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = audit_pixi_lock.audit_lock(
                self.write_lock(Path(temp_dir), contents)
            )
        package = next(
            package for package in result.packages if package.ecosystem == "conda"
        )
        self.assertEqual(package.reported_license, "OpenFusion's Test License")

    def test_requires_python_and_single_quote_errors_fail_closed(self) -> None:
        variants = (
            ("missing operator", "'3.6'", "requires_python specifier"),
            ("reversed operator", "'=>3.6'", "requires_python specifier"),
            ("invalid list member", "'>=3.6,python'", "requires_python specifier"),
            (
                "invalid wildcard operator",
                "'>=3.6.*'",
                "wildcard uses an invalid operator",
            ),
            ("unclosed quote", "'>=3.6", "unsupported quoted"),
            ("undoubled apostrophe", "'>=3.6'bad'", "unsupported quoted"),
        )
        for label, field_value, message in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                contents = valid_lock().replace(
                    f"  sha256: {PYPI_SHA}\n",
                    f"  sha256: {PYPI_SHA}\n  requires_python: {field_value}\n",
                )
                with self.assertRaisesRegex(audit_pixi_lock.AuditError, message):
                    audit_pixi_lock.audit_lock(
                        self.write_lock(Path(temp_dir), contents)
                    )

    def test_pypi_dev_normalization_does_not_collide_with_local_dev(self) -> None:
        equivalent_versions = (
            ("1.0-dev", "1.0.dev0"),
            ("1.0_dev2", "1.0.dev2"),
        )
        for locked_version, filename_version in equivalent_versions:
            with self.subTest(
                locked_version=locked_version
            ), tempfile.TemporaryDirectory() as temp_dir:
                archive_url = PYPI_URL.replace("2.0.0", filename_version)
                contents = (
                    valid_lock()
                    .replace(PYPI_URL, archive_url)
                    .replace("  version: 2.0.0", f"  version: {locked_version}")
                )
                audit_pixi_lock.audit_lock(self.write_lock(Path(temp_dir), contents))

        collision_url = PYPI_URL.replace("2.0.0", "1.0.dev0+dev")
        collision = (
            valid_lock()
            .replace(PYPI_URL, collision_url)
            .replace("  version: 2.0.0", "  version: 1.0+dev")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                audit_pixi_lock.AuditError, "identity does not match"
            ):
                audit_pixi_lock.audit_lock(self.write_lock(Path(temp_dir), collision))

    def test_pypi_escaped_and_ambiguous_filenames_fail_closed(self) -> None:
        variants = (
            (
                "percent escape",
                PYPI_URL.replace("example_py", "%65xample_py"),
                "canonical decoded components",
            ),
            (
                "ambiguous wheel",
                PYPI_URL.replace("example_py-2.0.0", "example-py-2.0.0"),
                "ambiguous|build tag",
            ),
            (
                "invalid version",
                PYPI_URL.replace("example_py-2.0.0", "example_py-2..0"),
                "PEP 440 version",
            ),
            (
                "missing sdist name",
                PYPI_URL.replace("example_py-2.0.0-py3-none-any.whl", "-2.0.0.tar.gz"),
                "missing a distribution or version",
            ),
            (
                "missing sdist version",
                PYPI_URL.replace(
                    "example_py-2.0.0-py3-none-any.whl", "example_py-.tar.gz"
                ),
                "missing a distribution or version",
            ),
            (
                "invalid sdist version",
                PYPI_URL.replace(
                    "example_py-2.0.0-py3-none-any.whl",
                    "example_py-not_a_version.tar.gz",
                ),
                "PEP 440 version",
            ),
            (
                "ambiguous sdist separators",
                PYPI_URL.replace("example_py-2.0.0-py3-none-any.whl", "foo-1-2.tar.gz"),
                "ambiguous component boundaries",
            ),
        )
        for label, rejected_url, message in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(PYPI_URL, rejected_url)
                )
                with self.assertRaisesRegex(audit_pixi_lock.AuditError, message):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_canonical_conda_v6_fields_are_typed(self) -> None:
        noarch_url = CONDA_URL.replace("/linux-64/", "/noarch/")
        valid_noarch = valid_lock().replace(CONDA_URL, noarch_url)
        valid_noarch = valid_noarch.replace(
            "  build_number: 0\n",
            "  build_number: 0\n  noarch: python\n  track_features:\n  - feature_name\n",
            1,
        ).replace("  track_features: []\n", "", 1)
        with tempfile.TemporaryDirectory() as temp_dir:
            audit_pixi_lock.audit_lock(self.write_lock(Path(temp_dir), valid_noarch))

        invalid_values = (
            ("build_number", "  build_number: 0", "  build_number: 01", "build_number"),
            (
                "noarch",
                "  build_number: 0",
                "  build_number: 0\n  noarch: executable",
                "invalid canonical scalar 'noarch'",
            ),
            (
                "track_features",
                "  track_features: []",
                "  track_features: feature_name",
                "must use a YAML list",
            ),
        )
        for label, old, new, message in invalid_values:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(old, new, 1)
                )
                with self.assertRaisesRegex(audit_pixi_lock.AuditError, message):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_conda_matchspec_internal_wildcards_are_plain_scalars(self) -> None:
        contents = valid_lock().replace(
            "  build_number: 0\n",
            "  build_number: 0\n  depends:\n"
            "  - python_abi 3.11.* *_cp311\n"
            "  - __cuda  >=12.8\n"
            "  - imath<3.2.0a0\n",
            1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = audit_pixi_lock.audit_lock(
                self.write_lock(Path(temp_dir), contents)
            )
        self.assertEqual(len(result.packages), 6)

    def test_unexpected_package_schema_fails_closed(self) -> None:
        variants = (
            (
                "unknown field",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  mystery: value\n",
                "unexpected 'mystery' field",
            ),
            (
                "wrong ecosystem field",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  name: example-lib\n",
                "unexpected 'name' field",
            ),
            (
                "mapping",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  depends:\n    nested: invalid\n",
                "unexpected package record schema",
            ),
            (
                "orphan list item",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  - orphan\n",
                "orphan package list item",
            ),
            (
                "scalar list",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  depends: python >=3\n",
                "must use a YAML list",
            ),
            (
                "duplicate field",
                f"  sha256: {CONDA_SHA}\n",
                f"  sha256: {CONDA_SHA}\n  sha256: {CONDA_SHA}\n",
                "duplicate 'sha256' field",
            ),
            (
                "inline map",
                "  track_features: []\n",
                "  track_features: {feature: enabled}\n",
                "must use a YAML list",
            ),
            (
                "inline list",
                "  track_features: []\n",
                "  track_features: [feature]\n",
                "must use a YAML list",
            ),
            (
                "anchor item",
                "  track_features: []\n",
                "  track_features:\n  - &feature enabled\n",
                "non-string YAML form",
            ),
            (
                "alias item",
                "  track_features: []\n",
                "  track_features:\n  - *feature\n",
                "non-string YAML form",
            ),
            (
                "tagged item",
                "  track_features: []\n",
                "  track_features:\n  - !!str feature\n",
                "non-string YAML form",
            ),
            (
                "mapping item",
                "  track_features: []\n",
                "  track_features:\n  - {feature: enabled}\n",
                "non-string YAML form",
            ),
            (
                "nested sequence",
                "  track_features: []\n",
                "  track_features:\n  - - nested\n",
                "non-string YAML form",
            ),
            (
                "nested mapping indicator",
                "  track_features: []\n",
                "  track_features:\n  - ? nested\n",
                "non-string YAML form",
            ),
            (
                "leading scalar comment",
                "  track_features: []\n",
                "  track_features: []\n  license: # comment\n",
                "non-string YAML form",
            ),
            (
                "trailing scalar comment",
                "  track_features: []\n",
                "  track_features: []\n  license: value # comment\n",
                "non-string YAML form",
            ),
            (
                "list comment",
                "  track_features: []\n",
                "  track_features:\n  - # comment\n",
                "non-string YAML form",
            ),
            (
                "double-quoted scalar",
                "  track_features: []\n",
                '  track_features: []\n  license: "BSD-3-Clause"\n',
                "unsupported quoted",
            ),
            (
                "double-quoted list item",
                "  track_features: []\n",
                '  track_features:\n  - "feature"\n',
                "unsupported quoted",
            ),
            (
                "block scalar",
                "  track_features: []\n",
                "  track_features: []\n  license: |\n    BSD-3-Clause\n",
                "non-string YAML form",
            ),
            (
                "single-quoted list item",
                "  track_features: []\n",
                "  track_features:\n  - 'feature'\n",
                "unsupported quoted",
            ),
            (
                "binary integer",
                "  track_features: []\n",
                "  track_features: []\n  license: +0b1010_0101\n",
                "non-string YAML form",
            ),
            (
                "octal integer",
                "  track_features: []\n",
                "  track_features: []\n  license: -0o7_55\n",
                "non-string YAML form",
            ),
            (
                "hex integer",
                "  track_features: []\n",
                "  track_features: []\n  license: 0xCA_FE\n",
                "non-string YAML form",
            ),
            (
                "exponent float",
                "  track_features: []\n",
                "  track_features: []\n  license: -1.2e+03\n",
                "non-string YAML form",
            ),
            (
                "infinity",
                "  track_features: []\n",
                "  track_features: []\n  license: .inf\n",
                "non-string YAML form",
            ),
            (
                "not a number",
                "  track_features: []\n",
                "  track_features: []\n  license: -.NaN\n",
                "non-string YAML form",
            ),
            (
                "date",
                "  track_features: []\n",
                "  track_features: []\n  license: 2026-08-30\n",
                "non-string YAML form",
            ),
            (
                "timestamp",
                "  track_features: []\n",
                "  track_features: []\n  license: 2026-08-30T04:17:00Z\n",
                "non-string YAML form",
            ),
        )
        for label, old, new, message in variants:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                lock_path = self.write_lock(
                    Path(temp_dir), valid_lock().replace(old, new, 1)
                )
                with self.assertRaisesRegex(audit_pixi_lock.AuditError, message):
                    audit_pixi_lock.audit_lock(lock_path)

    def test_spdx_output_is_repeatable_and_namespace_is_collision_resistant(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            result = audit_pixi_lock.audit_lock(
                self.write_lock(directory, valid_lock())
            )
            provenance = audit_pixi_lock.source_provenance(
                SOURCE_DATE_EPOCH, SOURCE_REVISION
            )
            first = directory / "first.spdx.json"
            second = directory / "second.spdx.json"
            audit_pixi_lock._write_json(
                first, audit_pixi_lock.make_spdx(result, provenance)
            )
            audit_pixi_lock._write_json(
                second, audit_pixi_lock.make_spdx(result, provenance)
            )
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()
            namespace = audit_pixi_lock.make_spdx(result, provenance)[
                "documentNamespace"
            ]

        self.assertEqual(first_bytes, second_bytes)
        self.assertIn(SOURCE_REVISION, namespace)
        self.assertIn(result.lock_sha256, namespace)

    def test_source_provenance_is_mandatory_and_canonical(self) -> None:
        for epoch in ("", "-1", "01", "now"):
            with self.subTest(epoch=epoch):
                with self.assertRaisesRegex(
                    audit_pixi_lock.AuditError, "source date epoch"
                ):
                    audit_pixi_lock.source_provenance(epoch, SOURCE_REVISION)
        for revision in ("", "ABCDEF" * 7, "1" * 39, "g" * 40):
            with self.subTest(revision=revision):
                with self.assertRaisesRegex(
                    audit_pixi_lock.AuditError, "source revision"
                ):
                    audit_pixi_lock.source_provenance(SOURCE_DATE_EPOCH, revision)

    def test_report_is_not_a_release_sbom_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), valid_lock())
            provenance = audit_pixi_lock.source_provenance(
                SOURCE_DATE_EPOCH, SOURCE_REVISION
            )
            report = audit_pixi_lock.make_report(
                audit_pixi_lock.audit_lock(lock_path), provenance
            )
        self.assertFalse(report["is_final_runtime_sbom"])
        self.assertFalse(report["archive_bytes_verified"])
        self.assertEqual(report["scope"], "all-platform-pixi-source-lock")
        self.assertEqual(report["source_revision"], SOURCE_REVISION)
        self.assertEqual(
            report["checksum_disclosure"], audit_pixi_lock.CHECKSUM_DISCLOSURE
        )
        json.dumps(report)

    def test_dependency_review_covers_pull_requests_and_merge_queue(self) -> None:
        workflow = (Path(__file__).parents[2] / "workflows" / "security.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if: github.event_name == 'pull_request' || github.event_name == 'merge_group'",
            workflow,
        )
        self.assertIn(
            "base-ref: ${{ github.event_name == 'merge_group' && github.event.merge_group.base_sha || github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            "head-ref: ${{ github.event_name == 'merge_group' && github.event.merge_group.head_sha || github.event.pull_request.head.sha }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
