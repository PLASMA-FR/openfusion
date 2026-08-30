#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 OpenFusion contributors

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "audit_pixi_lock.py"
SPEC = importlib.util.spec_from_file_location("audit_pixi_lock", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit_pixi_lock = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_pixi_lock
SPEC.loader.exec_module(audit_pixi_lock)

CONDA_URL = (
    "https://conda.anaconda.org/conda-forge/linux-64/"
    "example-lib-1.2.3-h123_0.conda"
)
PYPI_URL = (
    "https://files.pythonhosted.org/packages/ab/cd/"
    "example_py-2.0.0-py3-none-any.whl"
)
CONDA_SHA = "a" * 64
PYPI_SHA = "b" * 64


def valid_lock() -> str:
    references = []
    for platform in audit_pixi_lock.EXPECTED_PLATFORMS:
        references.extend(
            [
                f"      {platform}:",
                f"      - conda: {CONDA_URL}",
                f"      - pypi: {PYPI_URL}",
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
            f"- conda: {CONDA_URL}",
            f"  sha256: {CONDA_SHA}",
            "  license: BSD-3-Clause",
            f"- pypi: {PYPI_URL}",
            "  name: example-py",
            "  version: 2.0.0",
            f"  sha256: {PYPI_SHA}",
            "",
        ]
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
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "0"}):
                spdx = audit_pixi_lock.make_spdx(result)

        self.assertEqual(len(result.packages), 2)
        self.assertEqual(result.reference_count, 10)
        self.assertEqual(spdx["spdxVersion"], "SPDX-2.3")
        self.assertEqual(spdx["creationInfo"]["created"], "1970-01-01T00:00:00Z")
        self.assertEqual(len(spdx["packages"]), 3)
        self.assertIn(
            "not an inventory of a final OpenFusion runtime",
            spdx["packages"][0]["comment"],
        )
        self.assertTrue(all(p["licenseDeclared"] == "NOASSERTION" for p in spdx["packages"]))

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
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "does not use HTTPS"):
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
        contents = valid_lock() + f"- conda: {unused_url}\n  sha256: {'c' * 64}\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), contents)
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "unreferenced"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_duplicate_digest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir), valid_lock().replace(PYPI_SHA, CONDA_SHA)
            )
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "duplicate package SHA-256"):
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
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "duplicate package references"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_noncanonical_header_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(
                Path(temp_dir),
                valid_lock().replace("environments:\n", "environments:\n# injected\n", 1),
            )
            with self.assertRaisesRegex(audit_pixi_lock.AuditError, "canonical Pixi layout"):
                audit_pixi_lock.audit_lock(lock_path)

    def test_report_is_not_a_release_sbom_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = self.write_lock(Path(temp_dir), valid_lock())
            report = audit_pixi_lock.make_report(audit_pixi_lock.audit_lock(lock_path))
        self.assertFalse(report["is_final_runtime_sbom"])
        self.assertEqual(report["scope"], "all-platform-pixi-source-lock")
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
