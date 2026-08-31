# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "packaging" / "linux" / "runtime_closure.py"
LAUNCHER = ROOT / "src" / "Main" / "OpenFusionRuntimeLauncher.c"
MAIN_CMAKE = ROOT / "src" / "Main" / "CMakeLists.txt"
SPEC = importlib.util.spec_from_file_location("openfusion_runtime_closure", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
closure = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = closure
SPEC.loader.exec_module(closure)


def dynamic_elf(
    *,
    needed: tuple[str, ...] = (),
    runpath: str | None = "$ORIGIN",
    rpath: str | None = None,
    soname: str | None = None,
    interpreter: str | None = None,
    marker: bytes = b"",
) -> bytes:
    strings = bytearray(b"\0")

    def add(value: str) -> int:
        offset = len(strings)
        strings.extend(value.encode("ascii") + b"\0")
        return offset

    needed_offsets = [add(value) for value in needed]
    soname_offset = add(soname) if soname else None
    runpath_offset = add(runpath) if runpath is not None else None
    rpath_offset = add(rpath) if rpath is not None else None
    base = 0x400000
    dynamic_offset = 0x180
    interpreter_offset = 0x300
    string_offset = 0x500
    entries = [(5, base + string_offset), (10, len(strings))]
    entries.extend((1, value) for value in needed_offsets)
    if soname_offset is not None:
        entries.append((14, soname_offset))
    if rpath_offset is not None:
        entries.append((15, rpath_offset))
    if runpath_offset is not None:
        entries.append((29, runpath_offset))
    entries.append((0, 0))
    dynamic = b"".join(struct.pack("<qQ", tag, value) for tag, value in entries)
    interpreter_content = (
        interpreter.encode("ascii") + b"\0" if interpreter is not None else b""
    )
    total = max(
        string_offset + len(strings),
        dynamic_offset + len(dynamic),
        interpreter_offset + len(interpreter_content),
    ) + len(marker)
    image = bytearray(total)
    ident = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        image,
        0,
        ident,
        3,
        62,
        1,
        0,
        64,
        0,
        0,
        64,
        56,
        3 if interpreter is not None else 2,
        0,
        0,
        0,
    )
    struct.pack_into(
        "<IIQQQQQQ", image, 64, 1, 5, 0, base, base, total, total, 0x1000
    )
    if interpreter is not None:
        struct.pack_into(
            "<IIQQQQQQ",
            image,
            176,
            3,
            4,
            interpreter_offset,
            base + interpreter_offset,
            base + interpreter_offset,
            len(interpreter_content),
            len(interpreter_content),
            1,
        )
        image[
            interpreter_offset : interpreter_offset + len(interpreter_content)
        ] = interpreter_content
    struct.pack_into(
        "<IIQQQQQQ",
        image,
        120,
        2,
        6,
        dynamic_offset,
        base + dynamic_offset,
        base + dynamic_offset,
        len(dynamic),
        len(dynamic),
        8,
    )
    image[dynamic_offset : dynamic_offset + len(dynamic)] = dynamic
    image[string_offset : string_offset + len(strings)] = strings
    if marker:
        image[-len(marker) :] = marker
    return bytes(image)


class RuntimeClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="openfusion-runtime-test-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, content: bytes, executable: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if executable else 0o644)

    def test_bounded_parser_reads_needed_soname_and_runpath(self) -> None:
        path = self.root / "sample.so"
        self.write(
            path,
            dynamic_elf(
                needed=("libc.so.6", "libdependency.so"),
                runpath="$ORIGIN/../lib:$ORIGIN",
                soname="libsample.so.1",
            ),
        )
        info = closure.parse_elf(path, "sample.so")
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(("libc.so.6", "libdependency.so"), info.needed)
        self.assertEqual("libsample.so.1", info.soname)
        self.assertEqual(("$ORIGIN/../lib", "$ORIGIN"), info.runpath)

    def test_openvino_license_provenance_is_exact_and_self_contained(self) -> None:
        packages, evidence = closure._license_provenance()
        locked_packages = closure._parse_pixi_lock(
            (ROOT / "pixi.lock").read_bytes()
        )
        locked_linux_openvino = {
            url: record.sha256
            for url, record in locked_packages.items()
            if "/linux-64/libopenvino" in url
            or "/linux-aarch64/libopenvino" in url
        }
        self.assertEqual(24, len(packages))
        self.assertEqual(set(locked_linux_openvino), set(packages))
        self.assertEqual(4, len(evidence))
        self.assertEqual(
            {"linux-64", "linux-aarch64"},
            {
                "linux-aarch64" if "/linux-aarch64/" in url else "linux-64"
                for url in packages
            },
        )
        for url, (package_sha256, license_name) in packages.items():
            self.assertEqual(locked_linux_openvino[url], package_sha256)
            self.assertEqual("Apache-2.0", license_name)
        self.assertEqual(
            {
                "licenses/openvino-2025.0.0/LICENSE",
                "licenses/openvino-2025.0.0/licensing/onednn_third-party-programs.txt",
                "licenses/openvino-2025.0.0/licensing/runtime-third-party-programs.txt",
                "licenses/openvino-2025.0.0/licensing/third-party-programs.txt",
            },
            {path for path, _content in evidence},
        )

    def test_gui_runtime_launcher_pins_package_paths_and_execs_real_binary(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        cmake = MAIN_CMAKE.read_text(encoding="utf-8")
        self.assertIn('readlink("/proc/self/exe"', source)
        self.assertIn('{"QT_PLUGIN_PATH", "/lib/qt6/plugins"}', source)
        self.assertIn(
            '{"QT_QPA_PLATFORM_PLUGIN_PATH", "/lib/qt6/plugins/platforms"}',
            source,
        )
        self.assertIn('"%s/libexec/OpenFusion.real"', source)
        self.assertIn("execv(real_executable, argv)", source)
        self.assertIn("add_executable(OpenFusionRuntimeLauncher", cmake)
        self.assertIn("libexec/OpenFusion.real", cmake)

    def test_origin_relative_recursive_closure_passes(self) -> None:
        self.write(
            self.root / "bin" / "OpenFusionCmd",
            dynamic_elf(needed=("libdependency.so",), runpath="$ORIGIN/../lib"),
            executable=True,
        )
        self.write(
            self.root / "lib" / "libdependency.so",
            dynamic_elf(
                needed=("libc.so.6",),
                runpath="$ORIGIN",
                soname="libdependency.so",
            ),
        )
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertEqual(2, report.dynamic_elf_count)
        self.assertEqual((), report.issues)

    def test_absolute_runpath_and_missing_dependency_fail_closed(self) -> None:
        self.write(
            self.root / "bin" / "OpenFusion",
            dynamic_elf(
                needed=("libmissing.so",),
                runpath="/build/.pixi/envs/default/lib:$ORIGIN/../lib",
            ),
            executable=True,
        )
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertTrue(any("not package-relative" in issue for issue in report.issues))
        self.assertTrue(any("libmissing.so" in issue for issue in report.issues))

    def test_legacy_rpath_and_conflicting_soname_are_rejected(self) -> None:
        self.write(
            self.root / "lib" / "libone.so",
            dynamic_elf(rpath="$ORIGIN", runpath=None, soname="libcollision.so", marker=b"1"),
        )
        self.write(
            self.root / "lib" / "libtwo.so",
            dynamic_elf(runpath="$ORIGIN", soname="libcollision.so", marker=b"2"),
        )
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertTrue(any("DT_RPATH" in issue for issue in report.issues))
        self.assertTrue(any("conflicting central ELF definitions" in issue for issue in report.issues))

    def test_system_abi_shadow_and_interpreter_suffix_spoof_are_rejected(self) -> None:
        self.write(
            self.root / "bin" / "OpenFusion",
            dynamic_elf(
                needed=("libc.so.6",),
                runpath="$ORIGIN/../lib",
                interpreter="/attacker/ld-linux-x86-64.so.2",
            ),
            executable=True,
        )
        self.write(
            self.root / "lib" / "libc-copy.so",
            dynamic_elf(runpath="$ORIGIN", soname="libc.so.6"),
        )
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertTrue(any("unapproved ELF interpreter" in issue for issue in report.issues))
        self.assertTrue(any("shadows approved system ABI" in issue for issue in report.issues))

    def test_libc_basename_and_libm_symlink_target_shadows_are_rejected(self) -> None:
        library = self.root / "lib"
        library.mkdir()
        os.symlink("libdependency.so", library / "libc.so.6")
        os.symlink("../lib/./libm.so.6", library / "math-provider")
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertTrue(
            any(
                "entry basename shadows approved system ABI libc.so.6"
                in issue
                for issue in report.issues
            )
        )
        self.assertTrue(
            any(
                "symlink target shadows approved system ABI libm.so.6"
                in issue
                for issue in report.issues
            )
        )

    def test_nested_generic_origin_does_not_satisfy_central_lib_policy(self) -> None:
        self.write(
            self.root / "lib" / "plugin" / "consumer.so",
            dynamic_elf(needed=("libprivate.so",), runpath="$ORIGIN"),
        )
        self.write(
            self.root / "lib" / "plugin" / "libprivate.so",
            dynamic_elf(needed=("libc.so.6",), runpath="$ORIGIN"),
        )
        report = closure.audit_runtime_closure(self.root, "x86_64")
        self.assertTrue(any("outside central package lib" in issue for issue in report.issues))

    def test_dynamic_string_table_must_fit_file_backed_load_segment(self) -> None:
        image = bytearray(dynamic_elf(needed=("libc.so.6",)))
        struct.pack_into("<Q", image, 0x180 + 8, 0x400000 + len(image) - 1)
        path = self.root / "malformed.so"
        self.write(path, bytes(image))
        with self.assertRaisesRegex(closure.ClosureError, "string table is unmapped"):
            closure.parse_elf(path, "malformed.so")

    def test_absolute_needed_is_retargeted_to_existing_basename_suffix(self) -> None:
        path = self.root / "absolute-needed.so"
        self.write(
            path,
            dynamic_elf(
                needed=("/locked/pixi/lib/libsqlite3.so",),
                runpath="$ORIGIN",
            ),
        )
        source_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        before = closure.parse_elf(path, "absolute-needed.so")
        self.assertIsNotNone(before)
        assert before is not None
        descriptor = os.open(path, os.O_RDWR)
        try:
            self.assertTrue(
                closure._normalize_needed_descriptor(
                    descriptor, "absolute-needed.so", before
                )
            )
        finally:
            os.close(descriptor)
        after = closure.parse_elf(path, "absolute-needed.so")
        self.assertIsNotNone(after)
        assert after is not None
        self.assertEqual(("libsqlite3.so",), after.needed)
        self.assertNotEqual(source_digest, hashlib.sha256(path.read_bytes()).hexdigest())

    def _package(
        self,
        prefix: Path,
        lock_lines: list[str],
        name: str,
        version: str,
        files: list[str],
        depends: list[str] | None = None,
    ) -> None:
        digest = hashlib.sha256(name.encode("ascii")).hexdigest()
        url = f"https://conda.anaconda.org/conda-forge/linux-64/{name}-{version}-0.conda"
        metadata = {
            "build": "0",
            "depends": depends or [],
            "files": files,
            "license": "MIT" if name != "python" else "Python-2.0",
            "name": name,
            "sha256": digest,
            "subdir": "linux-64",
            "url": url,
            "version": version,
        }
        path = prefix / "conda-meta" / f"{name}-{version}-0.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata), encoding="utf-8")
        lock_lines.extend(
            (f"- conda: {url}", f"  sha256: {digest}", f"  license: {metadata['license']}")
        )

    def test_bundler_copies_locked_python_qt_and_recursive_elf_graph(self) -> None:
        stage = self.root / "stage"
        pixi = self.root / "pixi"
        stage.mkdir()
        pixi.mkdir()
        self.write(
            stage / "bin" / "OpenFusion",
            dynamic_elf(
                needed=("libdependency.so",),
                runpath="/build/.pixi/envs/default/lib:$ORIGIN/../lib",
            ),
            executable=True,
        )
        self.write(
            stage / "bin" / "OpenFusionCmd",
            dynamic_elf(needed=("libdependency.so",), runpath="$ORIGIN/../lib"),
            executable=True,
        )
        python_path = "lib/python3.11/encodings/__init__.py"
        plugin_path = "lib/qt6/plugins/platforms/libqxcb.so"
        dependency_path = "lib/libdependency.so"
        dependency_data_path = "share/dependency/runtime.dat"
        support_path = "share/support/runtime.dat"
        self.write(pixi / python_path, b"# locked encodings\n")
        self.write(
            pixi / plugin_path,
            dynamic_elf(
                needed=("libc.so.6",),
                runpath=None,
                rpath="$ORIGIN/../../..",
            ),
        )
        self.write(pixi / dependency_data_path, b"dependency runtime data\n")
        self.write(pixi / support_path, b"recursive support data\n")
        self.write(
            pixi / dependency_path,
            dynamic_elf(
                needed=("libc.so.6",),
                runpath="$ORIGIN",
                soname="libdependency.so",
            ),
        )
        lock_lines: list[str] = []
        self._package(pixi, lock_lines, "python", "3.11.9", [python_path])
        self._package(pixi, lock_lines, "qt6-main", "6.8.3", [plugin_path])
        self._package(
            pixi,
            lock_lines,
            "dependency",
            "1.0",
            [dependency_path, dependency_data_path],
            depends=["support >=1"],
        )
        self._package(pixi, lock_lines, "support", "1.0", [support_path])
        lock = self.root / "pixi.lock"
        lock.write_text(
            "version: 6\npackages:\n" + "\n".join(lock_lines) + "\n",
            encoding="utf-8",
        )

        manifest_path = closure.bundle_runtime(stage, pixi, lock, "x86_64", 1_700_000_000)
        self.assertEqual(stage / closure.MANIFEST_RELATIVE_PATH, manifest_path)
        self.assertTrue((stage / python_path).is_file())
        self.assertTrue((stage / plugin_path).is_file())
        self.assertTrue((stage / dependency_path).is_file())
        self.assertTrue((stage / dependency_data_path).is_file())
        self.assertTrue((stage / support_path).is_file())
        self.assertEqual((), closure.verify_runtime_closure(stage, "x86_64").issues)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(lock.read_bytes()).hexdigest(), manifest["dependency_lock_sha256"])
        self.assertEqual(
            ["bin/OpenFusion"],
            [record["path"] for record in manifest["stage_transformations"]],
        )
        self.assertEqual(
            sorted(
                (
                    dependency_data_path,
                    dependency_path,
                    plugin_path,
                    python_path,
                    support_path,
                )
            ),
            sorted(record["path"] for record in manifest["files"]),
        )
        plugin_record = next(
            record for record in manifest["files"] if record["path"] == plugin_path
        )
        self.assertTrue(plugin_record["runpath_normalized"])
        self.assertNotEqual(plugin_record["source_sha256"], plugin_record["sha256"])
        plugin_info = closure.parse_elf(stage / plugin_path, plugin_path)
        self.assertIsNotNone(plugin_info)
        assert plugin_info is not None
        self.assertEqual((), plugin_info.rpath)
        self.assertEqual(("$ORIGIN/../../..",), plugin_info.runpath)

        managed_directories = []
        for record in manifest["files"]:
            if record["type"] == "file":
                (stage / record["path"]).chmod(
                    0o555 if record["mode"] == 0o755 else 0o444
                )
        for record in manifest["managed_entries"]:
            if record["type"] == "directory":
                directory = stage / record["path"]
                directory.chmod(0o555)
                managed_directories.append(directory)
        self.assertEqual(
            (), closure.verify_runtime_closure(stage, "x86_64").issues
        )
        for directory in managed_directories:
            directory.chmod(0o755)

        mode_record = next(
            record
            for record in manifest["files"]
            if record["type"] == "file" and record["mode"] == 0o644
        )
        mode_path = stage / mode_record["path"]
        for bad_mode in (0o666, 0o777, 0o4755, 0o700, 0o744):
            with self.subTest(file_mode=oct(bad_mode)):
                mode_path.chmod(bad_mode)
                with self.assertRaisesRegex(
                    closure.ClosureError, "noncanonical|privileged"
                ):
                    closure.verify_runtime_closure(stage, "x86_64")
        mode_path.chmod(0o644)

        directory_mode_path = managed_directories[0]
        for bad_mode in (0o777, 0o700):
            with self.subTest(directory_mode=oct(bad_mode)):
                directory_mode_path.chmod(bad_mode)
                with self.assertRaisesRegex(
                    closure.ClosureError, "noncanonical directory mode"
                ):
                    closure.verify_runtime_closure(stage, "x86_64")
        directory_mode_path.chmod(0o755)

        with self.assertRaisesRegex(closure.ClosureError, "does not match signed"):
            closure.verify_runtime_closure(
                stage,
                "x86_64",
                expected_dependency_lock_sha256="0" * 64,
            )

        managed_root = stage / "lib" / "python3.11"
        for kind in ("file", "directory", "symlink"):
            with self.subTest(extra=kind):
                extra = managed_root / f"unmanifested-{kind}"
                if kind == "file":
                    extra.write_bytes(b"extra")
                    extra.chmod(0o644)
                elif kind == "directory":
                    extra.mkdir(mode=0o755)
                else:
                    os.symlink("encodings", extra)
                with self.assertRaisesRegex(
                    closure.ClosureError, "unmanifested or changed"
                ):
                    closure.verify_runtime_closure(stage, "x86_64")
                if kind == "directory":
                    extra.rmdir()
                else:
                    extra.unlink()

    def test_locked_runtime_symlink_escape_is_rejected(self) -> None:
        stage = self.root / "stage"
        pixi = self.root / "pixi"
        stage.mkdir()
        pixi.mkdir()
        outside = self.root / "outside.py"
        outside.write_text("escape\n", encoding="utf-8")
        source = pixi / "lib/python3.11/encodings/__init__.py"
        source.parent.mkdir(parents=True)
        os.symlink(outside, source)
        plugin = "lib/qt6/plugins/platforms/libqxcb.so"
        self.write(pixi / plugin, dynamic_elf(needed=("libc.so.6",)))
        lock_lines: list[str] = []
        self._package(pixi, lock_lines, "python", "3.11.9", [source.relative_to(pixi).as_posix()])
        self._package(pixi, lock_lines, "qt6-main", "6.8.3", [plugin])
        lock = self.root / "pixi.lock"
        lock.write_text(
            "version: 6\npackages:\n" + "\n".join(lock_lines) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(closure.ClosureError, "absolute|escapes.*root"):
            closure.bundle_runtime(stage, pixi, lock, "x86_64", 1_700_000_000)

    def test_structural_lock_rejects_coordinate_hash_splicing(self) -> None:
        prefix = self.root / "pixi"
        prefix.mkdir()
        runtime = "lib/python3.11/encodings/__init__.py"
        self.write(prefix / runtime, b"# encodings\n")
        lines: list[str] = []
        self._package(prefix, lines, "python", "3.11.9", [runtime])
        lock = self.root / "pixi.lock"
        record = lines[:]
        record[1] = "  sha256: " + "f" * 64
        lock.write_text(
            "version: 6\npackages:\n" + "\n".join(record) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(closure.ClosureError, "absent from pixi.lock"):
            closure._load_packages(prefix, lock, "x86_64")


if __name__ == "__main__":
    unittest.main()
