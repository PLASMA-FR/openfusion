#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import hashlib
import importlib.util
import json
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


class StageSoftwareOpenGLTest(unittest.TestCase):
    @staticmethod
    def create_renderer(root: Path, payload: bytes = b"locked mesa renderer") -> Path:
        renderer = root / "prefix" / "Library" / "bin" / "opengl32sw.dll"
        renderer.parent.mkdir(parents=True)
        renderer.write_bytes(payload)
        return renderer

    def test_stages_locked_renderer_under_native_dependency_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            renderer = self.create_renderer(root)
            binary_directory = root / "build" / "bin"
            binary_directory.mkdir(parents=True)

            destination, digest = runtime.stage_software_opengl(
                renderer, binary_directory
            )

            self.assertEqual(destination, (binary_directory / "opengl32.dll").resolve())
            self.assertEqual(destination.read_bytes(), renderer.read_bytes())
            self.assertEqual(digest, hashlib.sha256(renderer.read_bytes()).hexdigest())

    def test_accepts_an_identical_already_staged_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            renderer = self.create_renderer(root)
            binary_directory = root / "build" / "bin"
            binary_directory.mkdir(parents=True)
            destination = binary_directory / "opengl32.dll"
            destination.write_bytes(renderer.read_bytes())

            staged, _ = runtime.stage_software_opengl(renderer, binary_directory)

            self.assertEqual(staged, destination.resolve())

    def test_rejects_a_different_existing_native_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            renderer = self.create_renderer(root)
            binary_directory = root / "build" / "bin"
            binary_directory.mkdir(parents=True)
            (binary_directory / "opengl32.dll").write_bytes(b"unexpected renderer")

            with self.assertRaisesRegex(
                runtime.RuntimeLayoutError, "Refusing to replace"
            ):
                runtime.stage_software_opengl(renderer, binary_directory)

    def test_rejects_an_unexpected_source_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            renderer = root / "untrusted.dll"
            renderer.write_bytes(b"renderer")
            binary_directory = root / "build" / "bin"
            binary_directory.mkdir(parents=True)

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "must be named"):
                runtime.stage_software_opengl(renderer, binary_directory)

    @staticmethod
    def create_locked_renderer_environment(root: Path) -> tuple[Path, Path, str]:
        prefix = root / "locked prefix"
        renderer = StageSoftwareOpenGLTest.create_renderer(root)
        renderer.relative_to(root / "prefix")
        prefix.mkdir(parents=True)
        target = prefix / "Library" / "bin" / "opengl32sw.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(renderer.read_bytes())
        package_url = (
            "https://conda.anaconda.org/conda-forge/win-64/"
            "qt6-main-6.8.3-test_0.conda"
        )
        metadata = prefix / "conda-meta" / "qt6-main-6.8.3-test_0.json"
        metadata.parent.mkdir()
        metadata.write_text(
            json.dumps(
                {
                    "name": "qt6-main",
                    "version": "6.8.3",
                    "build": "test_0",
                    "subdir": "win-64",
                    "url": package_url,
                    "files": ["Library/bin/opengl32sw.dll"],
                }
            ),
            encoding="utf-8",
        )
        lock = root / "pixi.lock"
        lock.write_text(
            "version: 6\npackages:\n"
            f"- conda: {package_url}\n"
            f"  sha256: {'a' * 64}\n",
            encoding="utf-8",
        )
        return prefix, lock, package_url

    def test_resolves_renderer_from_locked_active_conda_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix, lock, package_url = self.create_locked_renderer_environment(root)

            renderer, provenance = runtime.locked_conda_software_opengl(
                {"CONDA_PREFIX": str(prefix)}, lock
            )

            self.assertEqual(
                renderer, (prefix / "Library" / "bin" / "opengl32sw.dll").resolve()
            )
            self.assertIn("qt6-main-6.8.3-test_0", provenance)
            self.assertIn(package_url, provenance)

    def test_rejects_renderer_owner_missing_from_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix, lock, _ = self.create_locked_renderer_environment(root)
            lock.write_text("version: 6\npackages: []\n", encoding="utf-8")

            with self.assertRaisesRegex(
                runtime.RuntimeLayoutError, "not uniquely present"
            ):
                runtime.locked_conda_software_opengl(
                    {"CONDA_PREFIX": str(prefix)}, lock
                )

    def test_rejects_renderer_owned_by_an_unexpected_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix, lock, _ = self.create_locked_renderer_environment(root)
            metadata = next((prefix / "conda-meta").glob("qt6-main-*.json"))
            record = json.loads(metadata.read_text(encoding="utf-8"))
            record["name"] = "untrusted-renderer"
            metadata.write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "not owned"):
                runtime.locked_conda_software_opengl(
                    {"CONDA_PREFIX": str(prefix)}, lock
                )

    def test_rejects_duplicate_renderer_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix, lock, _ = self.create_locked_renderer_environment(root)
            metadata = next((prefix / "conda-meta").glob("qt6-main-*.json"))
            duplicate = prefix / "conda-meta" / "duplicate.json"
            duplicate.write_bytes(metadata.read_bytes())

            with self.assertRaisesRegex(runtime.RuntimeLayoutError, "exactly one"):
                runtime.locked_conda_software_opengl(
                    {"CONDA_PREFIX": str(prefix)}, lock
                )

    def test_rejects_renderer_resolving_outside_active_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix, lock, _ = self.create_locked_renderer_environment(root)
            renderer = prefix / "Library" / "bin" / "opengl32sw.dll"
            outside = root / "outside-opengl32sw.dll"
            outside.write_bytes(renderer.read_bytes())
            renderer.unlink()
            try:
                renderer.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")

            with self.assertRaisesRegex(
                runtime.RuntimeLayoutError, "outside CONDA_PREFIX"
            ):
                runtime.locked_conda_software_opengl(
                    {"CONDA_PREFIX": str(prefix)}, lock
                )

    def test_rejects_missing_conda_prefix(self) -> None:
        with self.assertRaisesRegex(runtime.RuntimeLayoutError, "CONDA_PREFIX"):
            runtime.locked_conda_software_opengl({}, Path("pixi.lock"))


class WriteRuntimePathsTest(unittest.TestCase):
    def test_exports_one_renderer_backend_and_retained_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            renderer = root / "opengl32.dll"
            renderer.write_bytes(b"renderer")
            environment = root / "github-env.txt"

            runtime.write_software_opengl_environment(
                renderer,
                "a" * 64,
                "qt6-main-6.8.3-test_0 package_sha256=" + "b" * 64,
                environment,
            )

            assignments = environment.read_text(encoding="utf-8").splitlines()
            self.assertIn("QT_OPENGL=desktop", assignments)
            self.assertIn(f"OPENFUSION_STAGED_OPENGL_PATH={renderer}", assignments)
            self.assertIn("OPENFUSION_STAGED_OPENGL_SHA256=" + "a" * 64, assignments)

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
        self.assertIn("--stage-software-opengl", helper_step)
        self.assertIn("--lock-file pixi.lock", helper_step)

        graphics_validator = ".github/scripts/validate_gui_graphics_log.py"
        self.assertEqual(workflow.count(graphics_validator), 4)
        self.assertIn("OpenFusionWindowsOpenGLAcceptance", workflow)

        for step_name, exit_marker in (
            (
                "- name: Verify loaded Windows software OpenGL runtime",
                "if ($runtimeExitCode -ne 0)",
            ),
            (
                "- name: Validate TechDraw GUI SVG and PDF export",
                "if ($techDrawExitCode -ne 0)",
            ),
            (
                "- name: Inventory and run native FreeCAD GUI baseline",
                "if ($inventoryExitCode -ne 0)",
            ),
            (
                "- name: Inventory and run native FreeCAD GUI baseline",
                "if ($testExitCode -ne 0)",
            ),
        ):
            with self.subTest(step=step_name, exit_marker=exit_marker):
                step_position = workflow.index(step_name, helper_position)
                exit_position = workflow.index(exit_marker, step_position)
                validator_position = workflow.rfind(
                    graphics_validator, step_position, exit_position
                )
                self.assertGreater(validator_position, step_position)

        for copy_marker, exit_marker in (
            (
                "logs/freecadgui-inventory-application.log",
                "if ($inventoryExitCode -ne 0)",
            ),
            (
                "logs/freecadgui-application.log",
                "if ($testExitCode -ne 0)",
            ),
        ):
            with self.subTest(copy=copy_marker, exit_marker=exit_marker):
                step_position = workflow.index(
                    "- name: Inventory and run native FreeCAD GUI baseline",
                    helper_position,
                )
                self.assertLess(
                    workflow.index(copy_marker, step_position),
                    workflow.index(exit_marker, step_position),
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
