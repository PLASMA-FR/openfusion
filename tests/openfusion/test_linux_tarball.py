# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[2] / "packaging" / "linux" / "create_deterministic_tarball.py"
SPEC = importlib.util.spec_from_file_location("openfusion_linux_tarball", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tarball = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tarball
SPEC.loader.exec_module(tarball)


class PurePolicyTests(unittest.TestCase):
    def _minimal_manifest(self) -> dict[str, object]:
        version = "0.1.0-test.1"
        architecture = "x86_64"
        root = f"openfusion-{version}-linux-{architecture}"
        artifact = f"{root}.tar.zst"
        snapshot = tarball.Snapshot(1, 1, stat.S_IFREG | 0o644, 0, 0, 0, 1)
        entry = tarball.Entry(
            "file",
            Path("/unused"),
            "file",
            0o644,
            0,
            hashlib.sha256(b"").hexdigest(),
            None,
            snapshot,
        )
        content = tarball._manifest_bytes(
            artifact,
            f"{artifact}.manifest.json",
            f"{artifact}.sha256",
            root,
            version,
            architecture,
            "/opt/openfusion",
            1,
            [entry],
            "0" * 64,
            "test-only-bypass",
        )
        value = json.loads(content)
        assert isinstance(value, dict)
        return value

    def test_semver_rejects_leading_zero_numeric_prerelease(self) -> None:
        self.assertEqual(tarball._validate_version("1.2.3-0"), "1.2.3-0")
        self.assertEqual(tarball._validate_version("1.2.3-alpha01"), "1.2.3-alpha01")
        for invalid in ("1.2.3-00", "1.2.3-alpha.01", "01.2.3", "1.02.3", "1.2.03"):
            with self.subTest(version=invalid):
                with self.assertRaises(tarball.PackagingError):
                    tarball._validate_version(invalid)

    def test_absolute_limits_are_embedded_in_versioned_policy(self) -> None:
        self.assertEqual(tarball.POLICY_VERSION, 1)
        self.assertEqual(tarball.POLICY_LIMITS["archive_bytes"], 16 * 1024**3)
        self.assertEqual(tarball.POLICY_LIMITS["elf_program_headers"], 4096)
        self.assertEqual(tarball.POLICY_LIMITS["pax_header_bytes"], 64 * 1024)
        self.assertEqual(tarball.POLICY_LIMITS["tar_bytes"], 40 * 1024**3)
        self.assertEqual(tarball.POLICY_LIMITS["zstd_memory_mib"], 512)

    def test_path_and_symlink_target_limits_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(tarball.PackagingError, "path exceeds"):
            tarball._validate_relative_path("a" * (tarball.MAX_PATH_BYTES + 1))
        with self.assertRaisesRegex(tarball.PackagingError, "target exceeds"):
            tarball._validate_symlink(
                "link", "a" * (tarball.MAX_TARGET_BYTES + 1)
            )

    def test_elf_machine_validation_is_architecture_specific(self) -> None:
        header = bytearray(64)
        header[:4] = b"\x7fELF"
        header[4] = 2
        header[5] = 1
        header[6] = 1
        header[16:18] = (2).to_bytes(2, "little")
        header[18:20] = (62).to_bytes(2, "little")
        header[20:24] = (1).to_bytes(4, "little")
        identity = tarball._elf_identity(bytes(header), "bin/application")
        self.assertEqual(identity, (2, 1, 62))
        assert identity is not None
        tarball._validate_elf_identity(identity, "bin/application", "x86_64")
        header[18:20] = (183).to_bytes(2, "little")
        wrong = tarball._elf_identity(bytes(header), "bin/application")
        assert wrong is not None
        with self.assertRaisesRegex(tarball.PackagingError, "architecture mismatch"):
            tarball._validate_elf_identity(wrong, "bin/application", "x86_64")

    def test_cli_exposes_no_test_fixture_bypass(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                tarball._parser().parse_args(
                    [
                        "build",
                        "--destdir",
                        "/tmp/stage",
                        "--prefix",
                        "/opt/openfusion",
                        "--version",
                        "0.1.0-test.1",
                        "--architecture",
                        "x86_64",
                        "--output-dir",
                        "/tmp/output",
                        "--staging-is-quiescent",
                        "--test-only-allow-missing-elf",
                    ]
                )

    def test_companion_basename_validation_precedes_file_access(self) -> None:
        with self.assertRaisesRegex(tarball.PackagingError, "companion basenames"):
            tarball.verify_package(
                "/abs/package.tar.zst",
                "/abs/wrong.manifest.json",
                "/abs/package.tar.zst.sha256",
            )

    def test_sparse_tar_member_is_explicitly_rejected(self) -> None:
        member = tarball.tarfile.TarInfo("root/file")
        member.uid = 0
        member.gid = 0
        member.uname = "root"
        member.gname = "root"
        member.mode = 0o644
        member.mtime = 1
        member.type = tarball.tarfile.GNUTYPE_SPARSE
        member.size = 1
        member.sparse = [(0, 1)]
        with self.assertRaisesRegex(tarball.PackagingError, "sparse tar members"):
            tarball._verify_member_metadata(
                member,
                "root/file",
                {
                    "mode": 0o644,
                    "path": "file",
                    "sha256": "0" * 64,
                    "size": 1,
                    "type": "file",
                },
                1,
            )

    def test_oversized_pax_header_is_rejected_before_tarfile_parsing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openfusion-tar-preflight-") as value:
            path = Path(value) / "hostile.tar"
            info = tarball.tarfile.TarInfo("pax")
            info.type = tarball.tarfile.XHDTYPE
            info.size = tarball.MAX_PAX_HEADER_BYTES + 1
            path.write_bytes(info.tobuf(format=tarball.tarfile.PAX_FORMAT))
            with self.assertRaisesRegex(tarball.PackagingError, "PAX extended header"):
                tarball._preflight_tar_structure(path)

    def test_streamed_tar_iteration_does_not_retain_member_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="openfusion-tar-stream-") as value:
            path = Path(value) / "members.tar"
            with tarball.tarfile.open(path, mode="w") as archive:
                for index in range(32):
                    info = tarball.tarfile.TarInfo(f"root/directory-{index}")
                    info.type = tarball.tarfile.DIRTYPE
                    archive.addfile(info)
            with tarball.tarfile.open(path, mode="r:") as archive:
                count = 0
                for _ in tarball._stream_tar_members(archive):
                    count += 1
                    self.assertLessEqual(len(archive.members), 1)
                self.assertEqual(archive.members, [])
            self.assertEqual(count, 32)

    def test_manifest_rejects_boolean_values_for_integer_policy_fields(self) -> None:
        mutations = (
            ("policy version", lambda value: value["policy"].__setitem__("version", True)),
            ("normalization uid", lambda value: value["normalization"].__setitem__("uid", False)),
        )
        for label, mutate in mutations:
            with self.subTest(field=label):
                manifest = self._minimal_manifest()
                mutate(manifest)
                content = (
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                with self.assertRaises(tarball.PackagingError):
                    tarball._parse_manifest(content)


class SnapshotPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="openfusion-snapshot-test-")
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.private = self.root / "private"
        self.source.mkdir()
        self.private.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _scan(self) -> object:
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return tarball._scan_source_tree(source, None, 1_700_000_000, "x86_64")
        finally:
            os.close(source)

    def test_sparse_file_is_rejected(self) -> None:
        sparse = self.source / "sparse"
        with sparse.open("wb") as stream:
            stream.seek(2 * 1024 * 1024)
            stream.write(b"x")
        with self.assertRaisesRegex(tarball.PackagingError, "sparse staged files"):
            self._scan()

    def test_hardlink_is_rejected(self) -> None:
        original = self.source / "original"
        original.write_bytes(b"payload")
        os.link(original, self.source / "alias")
        with self.assertRaisesRegex(tarball.PackagingError, "hardlinked staged files"):
            self._scan()

    def test_privileged_mode_is_rejected(self) -> None:
        privileged = self.source / "privileged"
        privileged.write_bytes(b"payload")
        privileged.chmod(0o4755)
        with self.assertRaisesRegex(tarball.PackagingError, "setuid"):
            self._scan()

    def test_xattr_is_rejected(self) -> None:
        decorated = self.source / "decorated"
        decorated.write_bytes(b"payload")
        try:
            os.setxattr(decorated, "user.openfusion-test", b"value")
        except OSError as error:
            self.skipTest(f"test filesystem does not support user xattrs: {error}")
        with self.assertRaisesRegex(tarball.PackagingError, "xattrs"):
            self._scan()

    def test_wrong_elf_machine_is_rejected_even_for_test_fixture(self) -> None:
        (self.source / "bin").mkdir()
        header = bytearray(64)
        header[:4] = b"\x7fELF"
        header[4] = 2
        header[5] = 1
        header[6] = 1
        header[16:18] = (2).to_bytes(2, "little")
        header[18:20] = (183).to_bytes(2, "little")
        header[20:24] = (1).to_bytes(4, "little")
        executable = self.source / "bin" / "application"
        executable.write_bytes(header)
        executable.chmod(0o755)
        with self.assertRaisesRegex(tarball.PackagingError, "architecture mismatch"):
            self._scan()

    def test_header_only_fake_elf_cannot_validate_production_architecture(self) -> None:
        (self.source / "bin").mkdir()
        header = bytearray(64)
        header[:4] = b"\x7fELF"
        header[4] = 2
        header[5] = 1
        header[6] = 1
        header[16:18] = (2).to_bytes(2, "little")
        header[18:20] = (62).to_bytes(2, "little")
        header[20:24] = (1).to_bytes(4, "little")
        header[32:40] = (64).to_bytes(8, "little")
        header[52:54] = (64).to_bytes(2, "little")
        header[54:56] = (56).to_bytes(2, "little")
        header[56:58] = (1).to_bytes(2, "little")
        executable = self.source / "bin" / "fake"
        executable.write_bytes(header)
        executable.chmod(0o755)
        scan = self._scan()
        self.assertFalse(scan.representative_elf_found)

    def test_directory_addition_during_copy_is_detected(self) -> None:
        (self.source / "file").write_bytes(b"payload")
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        destination = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        original = tarball._copy_and_hash_regular_file
        injected = False

        def mutate_after_copy(*args: object, **kwargs: object) -> object:
            nonlocal injected
            result = original(*args, **kwargs)
            if not injected:
                injected = True
                (self.source / "late-addition").write_bytes(b"late")
            return result

        try:
            with mock.patch.object(
                tarball, "_copy_and_hash_regular_file", side_effect=mutate_after_copy
            ):
                with self.assertRaisesRegex(tarball.PackagingError, "membership changed"):
                    tarball._scan_source_tree(
                        source, destination, 1_700_000_000, "x86_64"
                    )
        finally:
            os.close(destination)
            os.close(source)

    def test_missing_representative_elf_requires_test_only_api(self) -> None:
        (self.source / "file").write_bytes(b"payload")
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        private = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaisesRegex(tarball.PackagingError, "proves the x86_64"):
                tarball._create_private_snapshot(
                    source,
                    private,
                    1_700_000_000,
                    "x86_64",
                    "0.1.0",
                    False,
                )
        finally:
            try:
                tarball._remove_tree_at(private, "snapshot")
            except FileNotFoundError:
                pass
            os.close(private)
            os.close(source)

    def test_test_fixture_snapshot_is_private_and_read_only(self) -> None:
        (self.source / "file").write_bytes(b"payload")
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        private = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            snapshot, status, source_scan = tarball._create_private_snapshot(
                source,
                private,
                1_700_000_000,
                "x86_64",
                "0.1.0-test.1",
                True,
            )
            self.assertEqual(status, "test-only-bypass")
            self.assertEqual(len(source_scan.records), 1)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o555)
            self.assertEqual(stat.S_IMODE((snapshot / "file").stat().st_mode), 0o444)
        finally:
            try:
                tarball._remove_tree_at(private, "snapshot")
            except FileNotFoundError:
                pass
            os.close(private)
            os.close(source)

    def test_bounded_copy_detects_source_metadata_change(self) -> None:
        source_path = self.source / "input"
        source_path.write_bytes(b"payload")
        source = os.open(source_path, os.O_RDONLY)
        destination = self.private / "copy"
        real_read = os.read
        changed = False

        def mutate_after_read(descriptor: int, size: int) -> bytes:
            nonlocal changed
            data = real_read(descriptor, size)
            if descriptor == source and data and not changed:
                changed = True
                os.utime(source_path, ns=(1_800_000_000_000_000_000,) * 2)
            return data

        try:
            with mock.patch.object(tarball.os, "read", side_effect=mutate_after_read):
                with self.assertRaisesRegex(tarball.PackagingError, "changed"):
                    tarball._copy_open_file_bounded(
                        source,
                        destination,
                        "test input",
                        1024,
                    )
        finally:
            os.close(source)
        self.assertFalse(destination.exists())

    def test_directory_path_replacement_is_detected(self) -> None:
        descriptor = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        moved = self.root / "moved-source"
        self.source.rename(moved)
        self.source.mkdir()
        try:
            with self.assertRaisesRegex(tarball.PackagingError, "path was replaced"):
                tarball._require_directory_identity(
                    self.source, descriptor, "staged source"
                )
        finally:
            os.close(descriptor)

    def test_directory_ancestry_uses_descriptor_identity(self) -> None:
        nested = self.source / "nested" / "output"
        nested.mkdir(parents=True)
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        output = os.open(nested, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertTrue(tarball._directory_descriptor_is_within(output, source))
            self.assertFalse(tarball._directory_descriptor_is_within(source, output))
        finally:
            os.close(output)
            os.close(source)


@unittest.skipUnless(shutil.which("zstd"), "zstd is required for tar.zst integration tests")
class ZstdIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="openfusion-package-test-")
        self.root = Path(self.temporary.name).resolve()
        self.destdir = self.root / "stage"
        self.prefix = self.destdir / "opt" / "openfusion"
        self.output_one = self.root / "output-one"
        self.output_two = self.root / "output-two"
        self.prefix.mkdir(parents=True)
        self.output_one.mkdir()
        self.output_two.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _populate(self) -> None:
        (self.prefix / "bin").mkdir()
        executable = self.prefix / "bin" / "test-launcher"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o751)
        (self.prefix / "lib").mkdir()
        library = self.prefix / "lib" / "libOpenFusion.so.1"
        library.write_bytes(b"synthetic-library\x00payload")
        library.chmod(0o600)
        os.symlink("libOpenFusion.so.1", self.prefix / "lib" / "libOpenFusion.so")
        (self.prefix / "share").mkdir()
        (self.prefix / "share" / "Unicode-模型.txt").write_text("model data\n", encoding="utf-8")

    def _build(self, output: Path) -> tuple[Path, Path, Path]:
        return tarball.build_package(
            self.destdir,
            "/opt/openfusion",
            "0.1.0-test.1",
            "x86_64",
            output,
            1_700_000_000,
            staging_is_quiescent=True,
            output_is_exclusive=True,
            _test_only_allow_missing_elf=True,
        )

    def _verify(self, outputs: tuple[Path, Path, Path]) -> None:
        tarball.verify_package(
            *outputs,
            _test_only_allow_missing_elf=True,
        )

    def test_repeated_build_is_byte_identical_and_verifiable(self) -> None:
        self._populate()
        first = self._build(self.output_one)

        for path in self.prefix.rglob("*"):
            if not path.is_symlink():
                os.utime(path, (1_720_000_000, 1_720_000_000))
        (self.prefix / "bin" / "test-launcher").chmod(0o777)
        (self.prefix / "lib" / "libOpenFusion.so.1").chmod(0o444)
        second = self._build(self.output_two)

        for first_path, second_path in zip(first, second, strict=True):
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
        self._verify(first)
        self._verify(second)

        manifest = json.loads(first[1].read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_date_epoch"], 1_700_000_000)
        self.assertEqual(
            [record["path"] for record in manifest["entries"]],
            [
                "bin",
                "bin/test-launcher",
                "lib",
                "lib/libOpenFusion.so",
                "lib/libOpenFusion.so.1",
                "share",
                "share/Unicode-模型.txt",
            ],
        )
        records = {record["path"]: record for record in manifest["entries"]}
        self.assertEqual(records["bin/test-launcher"]["mode"], 0o755)
        self.assertEqual(records["lib/libOpenFusion.so.1"]["mode"], 0o644)
        self.assertEqual(records["lib/libOpenFusion.so"]["target"], "libOpenFusion.so.1")
        artifact_digest = hashlib.sha256(first[0].read_bytes()).hexdigest()
        self.assertEqual(manifest["archive_sha256"], artifact_digest)
        self.assertEqual(manifest["architecture"], "x86_64")
        self.assertEqual(manifest["elf_validation"], "test-only-bypass")
        self.assertEqual(manifest["policy"]["version"], tarball.POLICY_VERSION)
        checksum_lines = first[2].read_text(encoding="ascii").splitlines()
        self.assertEqual(len(checksum_lines), 2)
        self.assertTrue(checksum_lines[0].endswith(f"  {first[0].name}"))
        self.assertTrue(checksum_lines[1].endswith(f"  {first[1].name}"))

    def test_test_fixture_verification_requires_explicit_api_bypass(self) -> None:
        self._populate()
        outputs = self._build(self.output_one)
        with self.assertRaisesRegex(tarball.PackagingError, "explicit test API flag"):
            tarball.verify_package(*outputs)
        self._verify(outputs)

        with contextlib.redirect_stderr(io.StringIO()):
            result = tarball.main(
                [
                    "verify",
                    "--archive",
                    str(outputs[0]),
                    "--manifest",
                    str(outputs[1]),
                    "--checksum",
                    str(outputs[2]),
                ]
            )
        self.assertEqual(result, 2)

    def test_source_mutation_after_snapshot_prevents_publication(self) -> None:
        self._populate()
        real_verify = tarball._verify_archive_data
        mutation_injected = False

        def verify_then_mutate(*args: object, **kwargs: object) -> object:
            nonlocal mutation_injected
            result = real_verify(*args, **kwargs)
            if not mutation_injected:
                mutation_injected = True
                (self.prefix / "share" / "late-addition").write_bytes(b"late")
            return result

        with mock.patch.object(
            tarball, "_verify_archive_data", side_effect=verify_then_mutate
        ):
            with self.assertRaisesRegex(tarball.PackagingError, "before publication"):
                self._build(self.output_one)
        self.assertEqual(list(self.output_one.iterdir()), [])

    def test_real_x86_64_elf_is_required_without_test_bypass(self) -> None:
        (self.prefix / "bin").mkdir()
        executable = self.prefix / "bin" / "test-launcher"
        shutil.copyfile("/usr/bin/true", executable)
        executable.chmod(0o755)
        outputs = tarball.build_package(
            self.destdir,
            "/opt/openfusion",
            "0.1.0",
            "x86_64",
            self.output_one,
            1_700_000_000,
            staging_is_quiescent=True,
            output_is_exclusive=True,
        )
        manifest = json.loads(outputs[1].read_text(encoding="utf-8"))
        self.assertEqual(manifest["elf_validation"], "validated")
        tarball.verify_package(*outputs)

    def test_archive_is_published_last_as_commit_marker(self) -> None:
        self._populate()
        real_link = os.link
        publication_order: list[str] = []

        def record_link(source: object, destination: object, **kwargs: object) -> None:
            publication_order.append(str(source))
            real_link(source, destination, **kwargs)

        with mock.patch.object(tarball.os, "link", side_effect=record_link):
            outputs = self._build(self.output_one)
        self.assertEqual(publication_order[-1], outputs[0].name)
        self.assertEqual(publication_order[:-1], [outputs[1].name, outputs[2].name])

    def test_output_directory_exclusivity_must_be_explicit(self) -> None:
        self._populate()
        with self.assertRaisesRegex(tarball.PackagingError, "exclusively control"):
            tarball.build_package(
                self.destdir,
                "/opt/openfusion",
                "0.1.0-test.1",
                "x86_64",
                self.output_one,
                1_700_000_000,
                staging_is_quiescent=True,
                _test_only_allow_missing_elf=True,
            )

    def test_publication_failure_rolls_back_precommit_companions(self) -> None:
        self._populate()
        real_link = os.link

        def fail_archive_link(
            source: object, destination: object, **kwargs: object
        ) -> None:
            if str(source).endswith(".tar.zst"):
                raise OSError(errno.EIO, "injected archive-link failure")
            real_link(source, destination, **kwargs)

        with mock.patch.object(tarball.os, "link", side_effect=fail_archive_link):
            with self.assertRaises(OSError):
                self._build(self.output_one)
        self.assertEqual(list(self.output_one.iterdir()), [])

    def test_internal_parent_symlink_is_allowed(self) -> None:
        (self.prefix / "bin").mkdir()
        (self.prefix / "lib").mkdir()
        (self.prefix / "lib" / "runtime.so").write_bytes(b"runtime")
        os.symlink("../lib/runtime.so", self.prefix / "bin" / "runtime.so")
        outputs = self._build(self.output_one)
        self._verify(outputs)

    def test_bytewise_sort_is_not_depth_first(self) -> None:
        (self.prefix / "a").mkdir()
        (self.prefix / "a" / "z").write_bytes(b"nested")
        (self.prefix / "a-file").write_bytes(b"sibling")
        outputs = self._build(self.output_one)
        manifest = json.loads(outputs[1].read_text(encoding="utf-8"))
        self.assertEqual(
            [record["path"] for record in manifest["entries"]],
            ["a", "a-file", "a/z"],
        )
        self._verify(outputs)

    def test_absolute_and_escaping_symlinks_are_rejected(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        os.symlink("/etc/passwd", self.prefix / "absolute")
        with self.assertRaisesRegex(tarball.PackagingError, "absolute symlink"):
            self._build(self.output_one)
        (self.prefix / "absolute").unlink()
        os.symlink("../../../../outside", self.prefix / "escape")
        with self.assertRaisesRegex(tarball.PackagingError, "escapes the packaged prefix"):
            self._build(self.output_one)

    def test_fifo_is_rejected(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        os.mkfifo(self.prefix / "forbidden-fifo")
        with self.assertRaisesRegex(tarball.PackagingError, "special files are forbidden"):
            self._build(self.output_one)

    def test_output_inside_prefix_is_rejected(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        nested_output = self.prefix / "output"
        nested_output.mkdir()
        with self.assertRaisesRegex(tarball.PackagingError, "must not be inside"):
            self._build(nested_output)

    def test_symlinked_prefix_component_is_rejected(self) -> None:
        alternate = self.destdir / "alternate"
        alternate.mkdir()
        (alternate / "file").write_bytes(b"payload")
        (self.destdir / "opt" / "openfusion").rmdir()
        os.symlink("../alternate", self.destdir / "opt" / "openfusion")
        with self.assertRaisesRegex(tarball.PackagingError, "without following symlinks"):
            self._build(self.output_one)

    def test_existing_output_is_not_overwritten(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        artifact = self.output_one / "openfusion-0.1.0-test.1-linux-x86_64.tar.zst"
        artifact.write_bytes(b"keep-me")
        with self.assertRaisesRegex(tarball.PackagingError, "refusing to overwrite"):
            self._build(self.output_one)
        self.assertEqual(artifact.read_bytes(), b"keep-me")

    def test_tampered_archive_and_checksum_fail_verification(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        artifact.chmod(stat.S_IRUSR | stat.S_IWUSR)
        with artifact.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(tarball.PackagingError, "SHA-256"):
            tarball.verify_package(artifact, manifest, checksum)

    def test_tampered_checksum_fails_verification(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        checksum.write_text(f"{'0' * 64}  {artifact.name}\n", encoding="ascii")
        with self.assertRaisesRegex(tarball.PackagingError, "checksum file"):
            tarball.verify_package(artifact, manifest, checksum)

    def test_canonical_manifest_rejects_added_fields_even_with_updated_checksum(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_data["unexpected"] = "field"
        manifest.write_text(
            json.dumps(
                manifest_data,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        checksum.write_text(
            f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
            f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(tarball.PackagingError, "manifest fields"):
            tarball.verify_package(artifact, manifest, checksum)

    def test_symlinked_companion_directory_is_rejected(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        alias = self.root / "output-alias"
        os.symlink(self.output_one.name, alias)
        with self.assertRaisesRegex(tarball.PackagingError, "cannot safely open"):
            tarball.verify_package(
                alias / artifact.name,
                alias / manifest.name,
                alias / checksum.name,
            )

    def test_decompression_is_bounded(self) -> None:
        plain = self.root / "plain"
        compressed = self.root / "plain.zst"
        output = self.root / "expanded"
        plain.write_bytes(b"x" * 4096)
        zstd = tarball._find_zstd(None)
        tarball._compress(plain, compressed, zstd)
        with self.assertRaisesRegex(tarball.PackagingError, "size limit"):
            tarball._decompress(compressed, output, zstd, 128)

    def test_cli_requires_source_date_epoch(self) -> None:
        self._populate()
        previous = os.environ.pop("SOURCE_DATE_EPOCH", None)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                result = tarball.main(
                    [
                        "build",
                        "--destdir",
                        str(self.destdir),
                        "--prefix",
                        "/opt/openfusion",
                        "--version",
                        "0.1.0",
                        "--architecture",
                        "x86_64",
                        "--output-dir",
                        str(self.output_one),
                        "--staging-is-quiescent",
                    ]
                )
        finally:
            if previous is not None:
                os.environ["SOURCE_DATE_EPOCH"] = previous
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
