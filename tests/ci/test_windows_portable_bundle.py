# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "packaging" / "windows" / "create_portable_bundle.py"
SPEC = importlib.util.spec_from_file_location("windows_portable_bundle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)


def fake_pe(
    machine: int = 0x8664,
    imports: tuple[str, ...] = (),
    delay_imports: tuple[str, ...] = (),
) -> bytes:
    header = bytearray(0x200)
    data = bytearray(0x800)
    pe = 0x80
    optional = pe + 24
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, pe)
    header[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", header, pe + 4, machine, 1, 0, 0, 0, 0xF0, 0x2022)
    struct.pack_into("<H", header, optional, 0x20B)
    struct.pack_into("<Q", header, optional + 24, 0x140000000)
    struct.pack_into("<I", header, optional + 32, 0x1000)
    struct.pack_into("<I", header, optional + 36, 0x200)
    struct.pack_into("<I", header, optional + 56, 0x2000)
    struct.pack_into("<I", header, optional + 60, 0x200)
    struct.pack_into("<H", header, optional + 68, 3)
    struct.pack_into("<I", header, optional + 108, 16)

    cursor = 0
    if imports:
        descriptor = cursor
        cursor += (len(imports) + 1) * 20
        for index, name in enumerate(imports):
            encoded = name.encode("ascii") + b"\0"
            name_offset = cursor
            data[name_offset:name_offset + len(encoded)] = encoded
            cursor += len(encoded)
            struct.pack_into("<IIIII", data, descriptor + index * 20, 0, 0, 0, 0x1000 + name_offset, 0)
        struct.pack_into("<II", header, optional + 112 + 8, 0x1000 + descriptor, (len(imports) + 1) * 20)
    cursor = (cursor + 31) & ~31
    if delay_imports:
        descriptor = cursor
        cursor += (len(delay_imports) + 1) * 32
        for index, name in enumerate(delay_imports):
            encoded = name.encode("ascii") + b"\0"
            name_offset = cursor
            data[name_offset:name_offset + len(encoded)] = encoded
            cursor += len(encoded)
            struct.pack_into("<IIIIIIII", data, descriptor + index * 32, 1, 0x1000 + name_offset, 0, 0, 0, 0, 0, 0)
        struct.pack_into("<II", header, optional + 112 + 13 * 8, 0x1000 + descriptor, (len(delay_imports) + 1) * 32)
    section = optional + 0xF0
    header[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", header, section + 8, len(data), 0x1000, len(data), 0x200)
    struct.pack_into("<I", header, section + 36, 0x40000040)
    return bytes(header + data)


class PortableBundleFixture:
    package_url = "https://conda.anaconda.org/conda-forge/win-64/qt6-main-6.8.3-test_0.tar.bz2"
    package_sha256 = ""
    revision = "b" * 40
    version = "1.1.3-dev.test"
    epoch = 1_700_000_000
    package_size = 0

    def __init__(self, root: Path) -> None:
        self.root = root
        self.install = root / "install"
        self.prefix = root / "prefix"
        self.output = root / "output"
        self.package_cache = root / "package-cache"
        self.lock = root / "pixi.lock"
        self.license = root / "COPYING"
        self.notice = root / "NOTICE.md"
        self.qt_manifest = root / "qt-plugins.txt"
        (self.install / "bin").mkdir(parents=True)
        (self.install / "data").mkdir()
        (self.install / "bin" / "OpenFusion.exe").write_bytes(fake_pe())
        (self.install / "bin" / "OpenFusionCmd.exe").write_bytes(fake_pe())
        (self.install / "data" / "product.txt").write_text("OpenFusion\n", encoding="utf-8")
        shutil.copyfile(REPOSITORY_ROOT / "COPYING", self.license)
        shutil.copyfile(REPOSITORY_ROOT / "NOTICE.md", self.notice)
        legal = self.install / "share" / "doc" / "openfusion"
        legal.mkdir(parents=True)
        for source_name, destination_name in (
            ("LICENSE", "LICENSE"),
            ("NOTICE.md", "NOTICE.md"),
            ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
        ):
            shutil.copyfile(REPOSITORY_ROOT / source_name, legal / destination_name)

        prefix_record = "Library/share/openfusion/prefix.txt"
        unselected_binary_record = "Library/unselected-prefix.bin"
        selected_binary_record = "DLLs/short-prefix.pyd"
        placeholder = "/opt/anaconda1anaconda2anaconda3"
        owned = {
            "python.exe": fake_pe(),
            "python311.dll": fake_pe(),
            "DLLs/_ssl.pyd": fake_pe(),
            "Lib/os.py": b"# os\n",
            "Library/bin/Qt6Core.dll": fake_pe(),
            "Library/bin/opengl32sw.dll": fake_pe(),
            "Library/bin/ccx.exe": fake_pe(),
            "Library/bin/gmsh.exe": fake_pe(),
            "Library/bin/dot.exe": fake_pe(),
            "Library/bin/unflatten.exe": fake_pe(),
            "Library/plugins/platforms/qwindows.dll": fake_pe(),
            "Library/plugins/platforms/qoffscreen.dll": fake_pe(),
            "Library/share/qt6/translations/qt_en.qm": b"translation",
            "Library/ssl/openssl.cnf": b"openssl_conf = openssl_init\n",
            "Library/ssl/cacert.pem": b"# test CA inventory\n",
            "Library/lib/ossl-modules/legacy.dll": fake_pe(),
            prefix_record: f"prefix={self.prefix}\n".encode("utf-8"),
            unselected_binary_record: b"x",
            selected_binary_record: fake_pe(),
        }
        archive_owned = dict(owned)
        archive_owned[prefix_record] = f"prefix={placeholder}\n".encode("utf-8")
        for relative, contents in owned.items():
            path = self.prefix / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        immutable_paths = []
        for relative, contents in sorted(archive_owned.items()):
            record = {
                    "_path": relative,
                    "path_type": "hardlink",
                    "sha256": hashlib.sha256(contents).hexdigest(),
                    "size_in_bytes": len(contents),
            }
            if relative == prefix_record:
                record.update(prefix_placeholder=placeholder, file_mode="text")
            elif relative == unselected_binary_record:
                record.update(prefix_placeholder="x", file_mode="binary")
            elif relative == selected_binary_record:
                record.update(prefix_placeholder="MZ", file_mode="binary")
            immutable_paths.append(record)
        paths_inventory = {"paths_version": 1, "paths": immutable_paths}
        index = {
            "name": "qt6-main",
            "version": "6.8.3",
            "build": "test_0",
            "subdir": "win-64",
        }
        self.package_cache.mkdir()
        temporary_archive = self.root / "fixture-package.tar.bz2"
        with tarfile.open(temporary_archive, "w:bz2") as archive:
            archive_payload = {
                "info/index.json": json.dumps(index, sort_keys=True).encode("utf-8"),
                "info/paths.json": json.dumps(paths_inventory, sort_keys=True).encode("utf-8"),
                **archive_owned,
            }
            for relative, contents in sorted(archive_payload.items()):
                member = tarfile.TarInfo(relative)
                member.size = len(contents)
                member.mtime = 0
                import io

                archive.addfile(member, io.BytesIO(contents))
        self.package_size = temporary_archive.stat().st_size
        self.package_sha256 = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()
        cache_archive = bundle.security.archive_cache_path(
            self.package_cache, self.package_url, self.package_sha256
        )
        temporary_archive.replace(cache_archive)

        metadata = self.prefix / "conda-meta" / "qt6-main.json"
        metadata.parent.mkdir()
        metadata.write_text(
            json.dumps(
                {
                    "name": "qt6-main",
                    "version": "6.8.3",
                    "build": "test_0",
                    "subdir": "win-64",
                    "url": self.package_url,
                    "sha256": self.package_sha256,
                    "size": self.package_size,
                    "files": sorted(owned),
                    "paths_data": {"paths_version": 1, "paths": []},
                }
            ),
            encoding="utf-8",
        )
        self.lock.write_text(
            "version: 6\nenvironments:\n  default:\n    packages:\n      win-64:\n"
            f"      - conda: {self.package_url}\npackages:\n"
            f"- conda: {self.package_url}\n  sha256: {self.package_sha256}\n"
            f"  size: {self.package_size}\n",
            encoding="utf-8",
        )
        plugin = (self.prefix / "Library" / "plugins").resolve()
        self.qt_manifest.write_text(f"{plugin}\n{plugin / 'platforms'}\n", encoding="utf-8")

    def config(self, output: Path | None = None):
        return bundle.CreateConfig(
            install_root=self.install,
            conda_prefix=self.prefix,
            qt_plugin_manifest=self.qt_manifest,
            lock_file=self.lock,
            package_cache=self.package_cache,
            license_file=self.license,
            notice_file=self.notice,
            output_dir=output or self.output,
            version=self.version,
            source_revision=self.revision,
            source_date_epoch=self.epoch,
        )


class WindowsPortableBundleTest(unittest.TestCase):
    def test_selected_over_capacity_binary_requires_exact_archive_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            _, manifest_path, _ = bundle.create_bundle(fixture.config())
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            self.assertIn(
                "bin/DLLs/short-prefix.pyd",
                {entry["path"] for entry in manifest["entries"]},
            )

    def test_unselected_short_binary_placeholder_does_not_block_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            archive, _, _ = bundle.create_bundle(fixture.config())
            self.assertTrue(archive.is_file())

    def test_selected_overlap_resolves_unique_authenticated_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.dll"
            path.write_bytes(fake_pe())
            identity = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)
            first = bundle.security.Owner("first-1-0", "first", "1", "0", "win-64", "https://conda.anaconda.org/conda-forge/win-64/first-1-0.conda", "a" * 64, 1)
            second = bundle.security.Owner("second-1-0", "second", "1", "0", "win-64", "https://conda.anaconda.org/conda-forge/win-64/second-1-0.conda", "b" * 64, 1)
            mismatch = bundle.security.OwnedFile(first, (("c" * 64, identity[1]),), "hardlink")
            match = bundle.security.OwnedFile(second, (identity,), "hardlink")
            resolved = bundle.security.resolve_owned_file(
                path, (mismatch, match), PurePosixPath("Library/bin/runtime.dll")
            )
            self.assertEqual(resolved.owner, second)
            broken_overlap = bundle.security.OwnedFile(first, (), "hardlink")
            with self.assertRaisesRegex(
                bundle.security.SecurityError, "prefix relocation could not be authenticated"
            ):
                bundle.security.resolve_owned_file(
                    path,
                    (match, broken_overlap),
                    PurePosixPath("Library/bin/runtime.dll"),
                )
            with self.assertRaisesRegex(bundle.security.SecurityError, "ambiguous"):
                bundle.security.resolve_owned_file(
                    path,
                    (match, bundle.security.OwnedFile(first, (identity,), "hardlink")),
                    PurePosixPath("Library/bin/runtime.dll"),
                )
            qt_owner = bundle.security.Owner("qt6-main-1-0", "qt6-main", "1", "0", "win-64", "https://conda.anaconda.org/conda-forge/win-64/qt6-main-1-0.conda", "d" * 64, 1)
            with self.assertRaisesRegex(bundle.security.SecurityError, "ambiguous"):
                bundle.security.resolve_owned_file(
                    path,
                    (
                        bundle.security.OwnedFile(qt_owner, (identity,), "hardlink"),
                        bundle.security.OwnedFile(second, (identity,), "hardlink"),
                    ),
                    PurePosixPath("Library/bin/opengl32sw.dll"),
                    required_owner="qt6-main",
                )

    def test_rejects_duplicate_path_inside_authenticated_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            old_archive = next(fixture.package_cache.iterdir())
            members = {}
            with tarfile.open(old_archive, "r:bz2") as archive:
                for member in archive:
                    if member.isfile():
                        stream = archive.extractfile(member)
                        assert stream is not None
                        members[member.name] = stream.read()
            paths = json.loads(members["info/paths.json"].decode("utf-8"))
            paths["paths"].append(dict(paths["paths"][0]))
            members["info/paths.json"] = json.dumps(paths, sort_keys=True).encode("utf-8")
            replacement = fixture.root / "duplicate.tar.bz2"
            with tarfile.open(replacement, "w:bz2") as archive:
                import io

                for name, contents in sorted(members.items()):
                    member = tarfile.TarInfo(name)
                    member.size = len(contents)
                    member.mtime = 0
                    archive.addfile(member, io.BytesIO(contents))
            old_archive.unlink()
            fixture.package_sha256 = hashlib.sha256(replacement.read_bytes()).hexdigest()
            fixture.package_size = replacement.stat().st_size
            replacement.replace(
                bundle.security.archive_cache_path(
                    fixture.package_cache, fixture.package_url, fixture.package_sha256
                )
            )
            fixture.lock.write_text(
                "version: 6\nenvironments:\n  default:\n    packages:\n      win-64:\n"
                f"      - conda: {fixture.package_url}\npackages:\n"
                f"- conda: {fixture.package_url}\n  sha256: {fixture.package_sha256}\n"
                f"  size: {fixture.package_size}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(bundle.BundleError, "duplicates a path"):
                bundle.create_bundle(fixture.config())

    def test_creates_reproducible_verified_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            first = bundle.create_bundle(fixture.config(fixture.root / "first"))[0]
            second = bundle.create_bundle(fixture.config(fixture.root / "second"))[0]
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_manifest_binds_locked_runtime_and_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            _, manifest_path, _ = bundle.create_bundle(fixture.config())
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            self.assertEqual(
                manifest["canonical_entrypoints"],
                ["bin/OpenFusion.exe", "bin/OpenFusionCmd.exe"],
            )
            self.assertEqual(manifest["runtime_packages"][0]["url"], fixture.package_url)
            self.assertEqual(
                manifest["pixi_lock_sha256"], hashlib.sha256(fixture.lock.read_bytes()).hexdigest()
            )
            paths = {entry["path"] for entry in manifest["entries"]}
            self.assertIn("bin/opengl32.dll", paths)
            self.assertNotIn("bin/opengl32sw.dll", paths)

    def test_rejects_compatibility_alias_without_canonical_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "bin" / "OpenFusion.exe").rename(
                fixture.install / "bin" / "FreeCAD.exe"
            )
            with self.assertRaisesRegex(bundle.BundleError, "required files"):
                bundle.create_bundle(fixture.config())

    def test_rejects_runtime_owner_not_in_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            fixture.lock.write_text("version: 6\nenvironments: {}\npackages: []\n", encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "Pixi"):
                bundle.create_bundle(fixture.config())

    def test_rejects_unowned_native_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.prefix / "Library" / "bin" / "injected.dll").write_bytes(fake_pe())
            with self.assertRaisesRegex(bundle.BundleError, "unowned native"):
                bundle.create_bundle(fixture.config())

    def test_rejects_forbidden_thumbnail_provider_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "bin" / "FCStdThumbnail.dll").write_bytes(fake_pe())
            with self.assertRaisesRegex(bundle.BundleError, "quarantined thumbnail"):
                bundle.create_bundle(fixture.config())

    def test_rejects_non_amd64_native_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "bin" / "OpenFusion.exe").write_bytes(fake_pe(0xAA64))
            with self.assertRaisesRegex(bundle.BundleError, "not x86-64"):
                bundle.create_bundle(fixture.config())

    def test_rejects_dos_device_and_nfkc_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "data" / "CON.txt").write_text("device", encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "DOS device"):
                bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "data" / "K.txt").write_text("one", encoding="utf-8")
            (fixture.install / "data" / "\N{KELVIN SIGN}.txt").write_text("two", encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "collision"):
                bundle.create_bundle(fixture.config())

    def test_rejects_trailing_dot_path_and_reparse_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "data" / "alias.").write_text("bad", encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "unsafe Windows path"):
                bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            target = fixture.root / "outside.txt"
            target.write_text("outside", encoding="utf-8")
            link = fixture.install / "data" / "link.txt"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            with self.assertRaisesRegex(bundle.BundleError, "reparse"):
                bundle.create_bundle(fixture.config())

    def test_rejects_query_url_and_installed_hash_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            metadata = fixture.prefix / "conda-meta" / "qt6-main.json"
            record = json.loads(metadata.read_text(encoding="utf-8"))
            record["url"] += "?credential=secret"
            metadata.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "credentials, query"):
                bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.prefix / "Library" / "bin" / "Qt6Core.dll").write_bytes(fake_pe(imports=("kernel32.dll",)))
            metadata = fixture.prefix / "conda-meta" / "qt6-main.json"
            record = json.loads(metadata.read_text(encoding="utf-8"))
            record["files"] = ["Library/bin/Qt6Core.dll"]
            record["paths_data"] = {
                "paths_version": 1,
                "paths": [{"_path": "Library/bin/Qt6Core.dll", "sha256_in_prefix": hashlib.sha256(
                    (fixture.prefix / "Library" / "bin" / "Qt6Core.dll").read_bytes()
                ).hexdigest()}],
            }
            metadata.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "identity changed"):
                bundle.create_bundle(fixture.config())

    def test_rejects_unresolved_normal_and_delay_imports(self) -> None:
        for keyword, payload in (
            ("unresolved PE dependency", fake_pe(imports=("missing-runtime.dll",))),
            ("unresolved PE dependency", fake_pe(delay_imports=("missing-delay.dll",))),
        ):
            with self.subTest(payload=payload[:2]), tempfile.TemporaryDirectory() as temporary:
                fixture = PortableBundleFixture(Path(temporary))
                (fixture.install / "bin" / "OpenFusion.exe").write_bytes(payload)
                with self.assertRaisesRegex(bundle.BundleError, keyword):
                    bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            (fixture.install / "bin" / "OpenFusion.exe").write_bytes(
                fake_pe(imports=("api-ms-win-invented-l9-9-9.dll",))
            )
            with self.assertRaisesRegex(bundle.BundleError, "unresolved PE dependency"):
                bundle.create_bundle(fixture.config())

    def test_rejects_system32_and_api_set_payload_shadows(self) -> None:
        for name in ("kernel32.dll", "api-ms-win-invented-l9-9-9.dll"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = PortableBundleFixture(Path(temporary))
                (fixture.install / "bin" / name).write_bytes(fake_pe())
                with self.assertRaisesRegex(bundle.BundleError, "shadows"):
                    bundle.create_bundle(fixture.config())

    def test_rejects_missing_or_modified_authenticated_package_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            archive = next(fixture.package_cache.iterdir())
            archive.unlink()
            with self.assertRaisesRegex(bundle.BundleError, "missing or has wrong size"):
                bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            archive = next(fixture.package_cache.iterdir())
            contents = bytearray(archive.read_bytes())
            contents[-1] ^= 1
            archive.write_bytes(contents)
            with self.assertRaisesRegex(bundle.BundleError, "hash differs"):
                bundle.create_bundle(fixture.config())

    def test_authoritative_legal_scan_rejects_restricted_lfs_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            policy = json.loads((REPOSITORY_ROOT / "packaging/linux/legal_quarantine.json").read_text())
            restricted = policy["restricted_patterns"][0]
            (fixture.install / "data" / "pointer.txt").write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{restricted['sha256']}\nsize {restricted['size']}\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(bundle.BundleError, "authoritative legal quarantine"):
                bundle.create_bundle(fixture.config())
            self.assertFalse(fixture.output.exists() and any(fixture.output.iterdir()))

    def test_authoritative_legal_scan_rejects_wide_arr_and_changed_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            restricted = "License = 'All Rights " + "Reserved'"
            (fixture.install / "data" / "metadata.bin").write_bytes(restricted.encode("utf-32le"))
            with self.assertRaisesRegex(bundle.BundleError, "authoritative legal quarantine"):
                bundle.create_bundle(fixture.config())
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            notice = fixture.install / "share" / "doc" / "openfusion" / "NOTICE.md"
            notice.write_text("changed notice\n", encoding="utf-8")
            with self.assertRaisesRegex(bundle.BundleError, "required shipped legal file"):
                bundle.create_bundle(fixture.config())

    def test_refuses_existing_output_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            bundle.create_bundle(fixture.config())
            with self.assertRaisesRegex(bundle.BundleError, "refusing to replace"):
                bundle.create_bundle(fixture.config())

    def test_verifier_rejects_zip_comment_even_with_updated_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            archive, manifest, checksum = bundle.create_bundle(fixture.config())
            with zipfile.ZipFile(archive, "a") as value:
                value.comment = b"forbidden-comment"
            checksum.write_text(
                f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(bundle.BundleError, "comment"):
                bundle.verify_bundle(
                    archive,
                    manifest,
                    checksum,
                    expected_version=fixture.version,
                    expected_source_revision=fixture.revision,
                    expected_lock_sha256=hashlib.sha256(fixture.lock.read_bytes()).hexdigest(),
                )

    def test_shipped_launchers_own_relocation_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = PortableBundleFixture(Path(temporary))
            archive, _, _ = bundle.create_bundle(fixture.config())
            root = f"OpenFusion-{fixture.version}-Windows-x86_64"
            with zipfile.ZipFile(archive, "r") as value:
                for launcher in ("OpenFusion.cmd", "OpenFusionCmd.cmd", "OpenFusionPython.cmd"):
                    script = value.read(f"{root}/{launcher}").decode("ascii")
                    for variable in (
                        "PATH=", "PYTHONHOME=", "QT_PLUGIN_PATH=", "SSL_CERT_FILE=",
                        "OPENSSL_CONF=", "OPENSSL_MODULES=", "OPENFUSION_PORTABLE_ROOT=",
                    ):
                        self.assertIn(variable, script)


class WindowsPortableWorkflowTest(unittest.TestCase):
    def test_workflow_smokes_and_uploads_final_archive(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "windows.yml").read_text(
            encoding="utf-8"
        )
        package = workflow.index("- name: Build and verify unsigned Windows portable package")
        smoke = workflow.index("OpenFusionCmd.exe", package)
        upload = workflow.index("- name: Upload unsigned Windows portable package", package)
        diagnostics = workflow.index("- name: Record baseline diagnostics", package)
        self.assertLess(package, smoke)
        self.assertLess(smoke, upload)
        self.assertLess(upload, diagnostics)
        self.assertIn("if-no-files-found: error", workflow[upload:diagnostics])
        self.assertIn("OpenFusion-Windows-x86_64-portable-unsigned", workflow[upload:diagnostics])
        package_step = workflow[package:upload]
        for marker in (
            "OpenFusionPython.cmd",
            "portable-runtime-probe.py",
            "import _ssl",
            "ssl.create_default_context()",
            "QT_QPA_PLATFORM = \"offscreen\"",
            "OpenFusionPortableWindowsAcceptance",
            "OpenFusionPortableRoundTrip.FCStd",
            "OpenFusionWindowsOpenGLAcceptance",
            "OPENFUSION_STAGED_OPENGL_SHA256",
        ):
            self.assertIn(marker, package_step)


if __name__ == "__main__":
    unittest.main()
