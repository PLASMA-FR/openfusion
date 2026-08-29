# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_TOOLS))

from check_restricted_material_patterns import (  # noqa: E402
    MATERIAL_SOURCE_PREFIX,
    PATTERN_ROOT,
    RESTRICTED_PATTERN_PATHS,
    find_violations,
)


class RestrictedMaterialPatternsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo_root = Path(self.temporary_directory.name)

    def _write(self, relative: str | Path, contents: str) -> Path:
        destination = self.repo_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
        return destination

    def test_manifest_contains_exactly_the_quarantined_pattern_paths(self) -> None:
        self.assertEqual(32, len(RESTRICTED_PATTERN_PATHS))
        self.assertEqual(32, len(set(RESTRICTED_PATTERN_PATHS)))
        for relative in RESTRICTED_PATTERN_PATHS:
            self.assertTrue(relative.startswith(f"{PATTERN_ROOT.as_posix()}/"))
            self.assertTrue(relative.endswith(".FCMat"))

    def test_clean_tree_passes(self) -> None:
        self._write("src/Mod/Material/CMakeLists.txt", "# no quarantined patterns\n")
        self.assertEqual([], find_violations(self.repo_root))

    def test_known_path_is_rejected(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[0]
        self._write(restricted, "General:\n  License: MIT\n")
        self.assertIn(
            f"restricted path exists: {restricted}",
            find_violations(self.repo_root),
        )

    def test_reference_is_rejected_even_when_asset_is_absent(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[-1]
        material_relative = restricted.removeprefix(MATERIAL_SOURCE_PREFIX)
        self._write(
            "packaging/CMakeLists.txt",
            f'install(FILES "{material_relative}" DESTINATION share)\n',
        )
        self.assertIn(
            "restricted path referenced by packaging/CMakeLists.txt: "
            f"{material_relative}",
            find_violations(self.repo_root),
        )

    def test_backslash_reference_is_rejected(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[8]
        material_relative = restricted.removeprefix(MATERIAL_SOURCE_PREFIX)
        windows_relative = material_relative.replace("/", "\\")
        self._write("CMakeLists.txt", f'set(PATTERN "{windows_relative}")\n')
        self.assertIn(
            f"restricted path referenced by CMakeLists.txt: {material_relative}",
            find_violations(self.repo_root),
        )

    def test_renamed_pattern_with_restricted_license_is_rejected(self) -> None:
        renamed = PATTERN_ROOT / "Replacement" / "renamed.FCMat"
        self._write(
            renamed,
            'General:\n  License: "All rights reserved"\n',
        )
        self.assertIn(
            f"restricted license declaration in: {renamed.as_posix()}",
            find_violations(self.repo_root),
        )


class RepositoryQuarantineTest(unittest.TestCase):
    def test_repository_is_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.assertEqual([], find_violations(repo_root))


if __name__ == "__main__":
    unittest.main()
