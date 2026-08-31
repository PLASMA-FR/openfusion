#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / ".github" / "scripts" / "prepare_windows_test_runtime.py"
WINDOWS_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "windows.yml"
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
                directories,
                [(build / "bin").resolve(), material.resolve(), part.resolve()],
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


class DiscoverQtPluginLayoutTest(unittest.TestCase):
    @staticmethod
    def create_layout(root: Path) -> tuple[Path, Path, Path]:
        plugin_directory = root / "pixi prefix" / "Library" / "plugins"
        platform_directory = plugin_directory / "platforms"
        platform_directory.mkdir(parents=True)
        (platform_directory / "qwindows.dll").touch()
        (platform_directory / "qoffscreen.dll").touch()
        manifest = root / "build" / "tests" / "qt-plugin-paths.txt"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            f"{plugin_directory}\n{platform_directory}\n", encoding="utf-8"
        )
        return plugin_directory, platform_directory, manifest

    def test_accepts_qmake_derived_plugin_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plugin_directory, platform_directory, manifest = self.create_layout(root)

            discovered = runtime.discover_qt_plugin_layout(manifest)

            self.assertEqual(
                discovered,
                (plugin_directory.resolve(), platform_directory.resolve()),
            )

    def test_accepts_non_ascii_qmake_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "Qt-\u00e9\u8a66\u9a13"
            plugin_directory, platform_directory, manifest = self.create_layout(root)

            discovered = runtime.discover_qt_plugin_layout(manifest)

            self.assertEqual(
                discovered,
                (plugin_directory.resolve(), platform_directory.resolve()),
            )

    def test_rejects_extra_manifest_line_as_command_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, _, manifest = self.create_layout(root)
            with manifest.open("a", encoding="utf-8", newline="\n") as output:
                output.write("QT_PLUGIN_PATH=C:\\untrusted\n")

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "exactly two"):
                runtime.discover_qt_plugin_layout(manifest)

    def test_rejects_platform_directory_outside_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plugin_directory, _, manifest = self.create_layout(root)
            unrelated = root / "unrelated" / "platforms"
            unrelated.mkdir(parents=True)
            (unrelated / "qwindows.dll").touch()
            (unrelated / "qoffscreen.dll").touch()
            manifest.write_text(f"{plugin_directory}\n{unrelated}\n", encoding="utf-8")

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "platforms child"):
                runtime.discover_qt_plugin_layout(manifest)

    def test_rejects_missing_windows_platform_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, platform_directory, manifest = self.create_layout(root)
            (platform_directory / "qwindows.dll").unlink()

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "qwindows"):
                runtime.discover_qt_plugin_layout(manifest)

    def test_rejects_stale_suffixed_platform_plugin_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, platform_directory, manifest = self.create_layout(root)
            (platform_directory / "qwindows.dll").rename(
                platform_directory / "qwindows-stale.dll"
            )

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "qwindows"):
                runtime.discover_qt_plugin_layout(manifest)

    def test_rejects_distinct_unicode_casefold_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            plugin_directory = root / "Stra\u00dfe" / "plugins"
            expected_platform_directory = plugin_directory / "platforms"
            expected_platform_directory.mkdir(parents=True)
            unrelated_platform_directory = root / "Strasse" / "plugins" / "platforms"
            unrelated_platform_directory.mkdir(parents=True)
            (unrelated_platform_directory / "qwindows.dll").touch()
            (unrelated_platform_directory / "qoffscreen.dll").touch()
            manifest = root / "qt-plugin-paths.txt"
            manifest.write_text(
                f"{plugin_directory}\n{unrelated_platform_directory}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "platforms child"):
                runtime.discover_qt_plugin_layout(manifest)


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
            with self.assertRaisesRegex(
                runtime.RuntimeLayoutError, "contains a newline"
            ):
                runtime.write_runtime_paths(
                    [Path("invalid\npath")], root / "github-path", root / "manifest"
                )


class WriteQtPluginEnvironmentTest(unittest.TestCase):
    def test_appends_exact_plugin_assignments_to_github_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            github_environment = root / "commands" / "github-env"
            github_environment.parent.mkdir(parents=True)
            github_environment.write_text("EXISTING=value\n", encoding="utf-8")
            plugin_directory = root / "pixi prefix" / "Library" / "plugins"
            platform_directory = plugin_directory / "platforms"

            runtime.write_qt_plugin_environment(
                plugin_directory, platform_directory, github_environment
            )

            self.assertEqual(
                github_environment.read_text(encoding="utf-8"),
                "EXISTING=value\n"
                f"QT_PLUGIN_PATH={plugin_directory}\n"
                f"QT_QPA_PLATFORM_PLUGIN_PATH={platform_directory}\n",
            )

    def test_rejects_newline_in_plugin_environment_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(
                runtime.RuntimeLayoutError, "contains a newline"
            ):
                runtime.write_qt_plugin_environment(
                    Path("invalid\nplugin"),
                    root / "platforms",
                    root / "github-env",
                )


class WindowsWorkflowRuntimeTest(unittest.TestCase):
    def test_qt_environment_export_precedes_every_native_product_test(self) -> None:
        workflow = WINDOWS_WORKFLOW.read_text(encoding="utf-8")
        helper = ".github/scripts/prepare_windows_test_runtime.py"
        self.assertEqual(workflow.count(helper), 1)
        helper_position = workflow.index(helper)
        next_step_position = workflow.index(
            "- name: Discover CTest tests", helper_position
        )
        helper_step = workflow[helper_position:next_step_position]
        self.assertIn('--github-env "$env:GITHUB_ENV"', helper_step)
        self.assertIn(
            "--qt-plugin-manifest "
            "build/release/tests/windows-native-test-qt-plugin-paths.txt",
            helper_step,
        )

        for later_step in (
            "- name: Validate TechDraw GUI SVG and PDF export",
            "- name: Run native FreeCADCmd baseline",
            "- name: Inventory and run native FreeCAD GUI baseline",
        ):
            with self.subTest(step=later_step):
                self.assertLess(helper_position, workflow.index(later_step))


if __name__ == "__main__":
    unittest.main()
