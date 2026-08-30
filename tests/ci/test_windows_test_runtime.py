#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / ".github" / "scripts" / "prepare_windows_test_runtime.py"
SPEC = importlib.util.spec_from_file_location("prepare_windows_test_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class DiscoverRuntimeLayoutTest(unittest.TestCase):
    def test_discovers_and_deduplicates_dynamic_library_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            build = Path(temporary_directory) / "release"
            (build / "bin").mkdir(parents=True)
            material = build / "Mod" / "Material"
            part = build / "Mod" / "Part"
            material.mkdir(parents=True)
            part.mkdir(parents=True)
            (material / "Materials.pyd").touch()
            (material / "MaterialSupport.dll").touch()
            (part / "Part.pyd").touch()
            (part / "ignored.txt").touch()

            directories, artifacts = runtime.discover_runtime_layout(build)

            self.assertEqual(directories[0], (build / "bin").resolve())
            self.assertEqual(
                set(directories[1:]), {material.resolve(), part.resolve()}
            )
            self.assertEqual(
                {artifact.name for artifact in artifacts},
                {"MaterialSupport.dll", "Materials.pyd", "Part.pyd"},
            )

    def test_rejects_module_tree_without_dynamic_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            build = Path(temporary_directory) / "release"
            (build / "bin").mkdir(parents=True)
            (build / "Mod").mkdir()

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "No .dll or .pyd"):
                runtime.discover_runtime_layout(build)

    def test_rejects_missing_required_artifact(self) -> None:
        with self.assertRaisesRegex(
            runtime.RuntimeLayoutError, "Materials.pyd, Part.pyd"
        ):
            runtime.require_artifacts([], ["Part.pyd", "Materials.pyd"])


class WriteRuntimePathsTest(unittest.TestCase):
    def test_appends_github_path_and_writes_deterministic_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            directories = [root / "bin", root / "Mod" / "Material"]
            github_path = root / "commands" / "github-path"
            manifest = root / "logs" / "runtime-paths.txt"
            github_path.parent.mkdir(parents=True)
            github_path.write_text("existing-entry\n", encoding="utf-8")

            runtime.write_runtime_paths(directories, github_path, manifest)

            expected = "\n".join(str(directory) for directory in directories) + "\n"
            self.assertEqual(
                github_path.read_text(encoding="utf-8"), "existing-entry\n" + expected
            )
            self.assertEqual(manifest.read_text(encoding="utf-8"), expected)

    def test_rejects_newline_in_github_command_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "contains a newline"):
                runtime.write_runtime_paths(
                    [Path("invalid\npath")], root / "github-path", root / "manifest"
                )


if __name__ == "__main__":
    unittest.main()
