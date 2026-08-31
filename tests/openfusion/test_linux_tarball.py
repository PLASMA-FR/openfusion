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
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = (
    Path(__file__).parents[2]
    / "packaging"
    / "linux"
    / "create_deterministic_tarball.py"
)
WORKFLOW = (
    Path(__file__).parents[2] / ".github" / "workflows" / "linux-packaging-policy.yml"
)
MAIN_CMAKE = Path(__file__).parents[2] / "src" / "Main" / "CMakeLists.txt"
RESTRICTED_PATTERN_GUARD = (
    Path(__file__).parents[2] / "tools" / "release" / "check_restricted_material_patterns.py"
)
THUMBNAIL_GUARD = (
    Path(__file__).parents[2]
    / "package"
    / "WindowsInstaller"
    / "tests"
    / "test_thumbnail_provider_quarantine.py"
)
SPEC = importlib.util.spec_from_file_location("openfusion_linux_tarball", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tarball = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tarball
SPEC.loader.exec_module(tarball)


VERSION = "0.1.0-dev.1"
SOURCE_REVISION = "1" * 40
SOURCE_DATE_EPOCH = 1_700_000_000


def valid_elf(marker: bytes) -> bytes:
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    header[6] = 1
    header[16:18] = (2).to_bytes(2, "little")
    header[18:20] = (62).to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    return bytes(header) + marker + b"\x00$ORIGIN/../lib\x00"


class SignedIdentityMixin:
    @classmethod
    def setUpClass(cls) -> None:
        super_method = getattr(super(), "setUpClass", None)
        if super_method is not None:
            super_method()
        openssl = shutil.which("openssl")
        if openssl is None:
            raise AssertionError("openssl is required; signed identity tests cannot be skipped")
        cls.openssl = Path(openssl).resolve()
        cls.key_directory = tempfile.TemporaryDirectory(prefix="openfusion-identity-key-")
        key_root = Path(cls.key_directory.name).resolve()
        cls.private_key = key_root / "identity-private.pem"
        cls.public_key = key_root / "identity-public.pem"
        subprocess.run(
            [
                str(cls.openssl),
                "genpkey",
                "-algorithm",
                "ED25519",
                "-out",
                str(cls.private_key),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                str(cls.openssl),
                "pkey",
                "-in",
                str(cls.private_key),
                "-pubout",
                "-out",
                str(cls.public_key),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        cls.key_sha256 = hashlib.sha256(
            tarball._public_key_der(cls.public_key, cls.openssl)
        ).hexdigest()
        cls.openssl_sha256 = tarball._sha256_regular_path_bounded(
            cls.openssl, "test openssl", tarball.MAX_FILE_BYTES
        )
        cls.openssl_version = tarball._run_openssl(
            [str(cls.openssl), "version"], "test version query"
        ).decode("utf-8").strip()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.key_directory.cleanup()
        super_method = getattr(super(), "tearDownClass", None)
        if super_method is not None:
            super_method()

    def provenance(
        self,
        lock_digest: str,
        version: str = VERSION,
        cmake_cache_sha256: str = "2" * 64,
    ) -> dict[str, object]:
        return {
            "build_type": "Release",
            "builder": "openfusion-policy-test",
            "cmake_cache_sha256": cmake_cache_sha256,
            "compiler": "Clang 21.1.0",
            "dependency_lock_sha256": lock_digest,
            "format_version": tarball.BUILD_PROVENANCE_FORMAT_VERSION,
            "generator": "Ninja",
            "openssl_sha256": self.openssl_sha256,
            "openssl_version": self.openssl_version,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "source_revision": SOURCE_REVISION,
            "version": version,
        }

    def signed_payload(
        self,
        *,
        version: str = VERSION,
        gui_digest: str = "3" * 64,
        cli_digest: str = "4" * 64,
        gui_size: int = 101,
        cli_size: int = 102,
        lock_digest: str = "5" * 64,
        payload_tree: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "architecture": "x86_64",
            "build_provenance": self.provenance(lock_digest, version),
            "dependency_lock": {"path": "pixi.lock", "sha256": lock_digest},
            "executables": {
                "cli": {
                    "compatibility_path": tarball.COMPATIBILITY_EXECUTABLES["cli"],
                    "path": tarball.CANONICAL_EXECUTABLES["cli"],
                    "sha256": cli_digest,
                    "size": cli_size,
                },
                "gui": {
                    "compatibility_path": tarball.COMPATIBILITY_EXECUTABLES["gui"],
                    "path": tarball.CANONICAL_EXECUTABLES["gui"],
                    "sha256": gui_digest,
                    "size": gui_size,
                },
            },
            "format_version": tarball.IDENTITY_FORMAT_VERSION,
            "install_prefix": "/opt/openfusion",
            "platform": "linux",
            "product": "OpenFusion",
            "payload_tree": payload_tree
            or {
                "domain": tarball.PAYLOAD_TREE_DOMAIN[:-1].decode("ascii"),
                "entry_count": 1,
                "policy_sha256": "6" * 64,
                "sha256": "7" * 64,
                "total_file_bytes": 1,
            },
            "release_channel": "development",
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "source_revision": SOURCE_REVISION,
            "version": version,
        }

    def sign_payload(self, payload: dict[str, object]) -> dict[str, object]:
        return tarball._sign_identity_payload(payload, self.private_key, self.openssl)

    def resign_manifest_identity(self, manifest: dict[str, object]) -> None:
        records = manifest["entries"]
        assert isinstance(records, list)
        payload_records = [
            record
            for record in records
            if record["path"] != tarball.IDENTITY_RELATIVE_PATH
        ]
        policy_bytes = tarball._canonical_json_bytes(
            {"limits": tarball.POLICY_LIMITS, "version": tarball.POLICY_VERSION}
        )
        records_bytes = tarball._canonical_json_bytes(payload_records)
        digest = hashlib.sha256()
        digest.update(tarball.PAYLOAD_TREE_DOMAIN)
        digest.update(policy_bytes)
        digest.update(records_bytes)
        tree = {
            "domain": tarball.PAYLOAD_TREE_DOMAIN[:-1].decode("ascii"),
            "entry_count": len(payload_records),
            "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
            "sha256": digest.hexdigest(),
            "total_file_bytes": sum(
                int(record["size"])
                for record in payload_records
                if record["type"] == "file"
            ),
        }
        old_envelope = manifest["product_identity"]
        assert isinstance(old_envelope, dict)
        payload = json.loads(json.dumps(old_envelope["payload"]))
        payload["payload_tree"] = tree
        envelope = self.sign_payload(payload)
        manifest["product_identity"] = envelope
        content = tarball._identity_envelope_bytes(envelope)
        identity_record = next(
            record
            for record in records
            if record["path"] == tarball.IDENTITY_RELATIVE_PATH
        )
        identity_record["size"] = len(content)
        identity_record["sha256"] = hashlib.sha256(content).hexdigest()

    def expected_lock_sha256(self) -> str:
        return getattr(self, "lock_digest", "5" * 64)

    def parse_manifest(self, content: bytes, *_legacy: object) -> dict[str, object]:
        return tarball._parse_manifest(
            content,
            self.public_key,
            self.openssl,
            self.key_sha256,
            "development",
            VERSION,
            "x86_64",
            "/opt/openfusion",
            SOURCE_REVISION,
            self.expected_lock_sha256(),
        )

    def verify_identity_envelope(
        self, envelope: object, *_legacy: object
    ) -> dict[str, object]:
        return tarball._verify_identity_envelope(
            envelope,
            self.public_key,
            self.openssl,
            self.key_sha256,
            "development",
        )

    def verify_package(
        self,
        archive: Path | str,
        manifest: Path | str,
        checksum: Path | str,
        trusted_public_key: Path | str | None = None,
        *_legacy: object,
    ) -> None:
        tarball.verify_package(
            archive,
            manifest,
            checksum,
            trusted_public_key or self.public_key,
            self.key_sha256,
            "development",
            VERSION,
            "x86_64",
            "/opt/openfusion",
            SOURCE_REVISION,
            self.expected_lock_sha256(),
        )

    def build_package(
        self,
        destdir: Path,
        prefix: str,
        version: str,
        architecture: str,
        output: Path,
        epoch: int,
        identity: Path,
        trusted_public_key: Path,
        **kwargs: object,
    ) -> tuple[Path, Path, Path]:
        return tarball.build_package(
            destdir,
            prefix,
            version,
            architecture,
            output,
            epoch,
            identity,
            trusted_public_key,
            self.key_sha256,
            "development",
            SOURCE_REVISION,
            self.expected_lock_sha256(),
            **kwargs,
        )

    def create_identity(
        self,
        destdir: Path,
        prefix: str,
        version: str,
        architecture: str,
        channel: str,
        lock_file: Path,
        provenance_file: Path,
        signing_key: Path,
        output: Path,
        openssl: str,
    ) -> Path:
        return tarball.create_identity(
            destdir,
            prefix,
            version,
            architecture,
            channel,
            lock_file,
            provenance_file,
            self.cmake_cache_file,
            signing_key,
            output,
            openssl,
        )


class PurePolicyTests(SignedIdentityMixin, unittest.TestCase):
    def _minimal_manifest(self) -> dict[str, object]:
        version = VERSION
        architecture = "x86_64"
        root = f"openfusion-{version}-linux-{architecture}"
        artifact = f"{root}.tar.zst"
        snapshot = tarball.Snapshot(1, 1, stat.S_IFREG | 0o644, 0, 0, 0, 1)
        entries = [
            tarball.Entry("bin", Path("/unused"), "directory", 0o755, 0, None, None, snapshot),
            tarball.Entry("bin/FreeCAD", Path("/unused"), "symlink", 0o777, 0, None, "OpenFusion", snapshot),
            tarball.Entry("bin/FreeCADCmd", Path("/unused"), "symlink", 0o777, 0, None, "OpenFusionCmd", snapshot),
            tarball.Entry("bin/OpenFusion", Path("/unused"), "file", 0o755, 101, "3" * 64, None, snapshot),
            tarball.Entry("bin/OpenFusionCmd", Path("/unused"), "file", 0o755, 102, "4" * 64, None, snapshot),
            tarball.Entry("file", Path("/unused"), "file", 0o644, 0, hashlib.sha256(b"").hexdigest(), None, snapshot),
            tarball.Entry("share", Path("/unused"), "directory", 0o755, 0, None, None, snapshot),
            tarball.Entry("share/openfusion", Path("/unused"), "directory", 0o755, 0, None, None, snapshot),
        ]
        identity = self.sign_payload(
            self.signed_payload(payload_tree=tarball._payload_tree_commitment(entries))
        )
        identity_content = tarball._identity_envelope_bytes(identity)
        entries.append(
            tarball.Entry(
                tarball.IDENTITY_RELATIVE_PATH,
                Path("/unused"),
                "file",
                0o644,
                len(identity_content),
                hashlib.sha256(identity_content).hexdigest(),
                None,
                snapshot,
            )
        )
        content = tarball._manifest_bytes(
            artifact,
            f"{artifact}.manifest.json",
            f"{artifact}.sha256",
            root,
            version,
            architecture,
            "/opt/openfusion",
            SOURCE_DATE_EPOCH,
            entries,
            "0" * 64,
            identity,
        )
        value = json.loads(content)
        assert isinstance(value, dict)
        return value

    @staticmethod
    def _canonical_manifest(value: dict[str, object]) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def test_semver_rejects_leading_zero_numeric_prerelease(self) -> None:
        self.assertEqual(tarball._validate_version("1.2.3-0"), "1.2.3-0")
        self.assertEqual(tarball._validate_version("1.2.3-alpha01"), "1.2.3-alpha01")
        for invalid in ("1.2.3-00", "1.2.3-alpha.01", "01.2.3", "1.02.3", "1.2.03"):
            with self.subTest(version=invalid):
                with self.assertRaises(tarball.PackagingError):
                    tarball._validate_version(invalid)

    def test_absolute_limits_are_embedded_in_versioned_policy(self) -> None:
        self.assertEqual(tarball.POLICY_VERSION, 3)
        self.assertEqual(tarball.POLICY_LIMITS["archive_bytes"], 16 * 1024**3)
        self.assertEqual(tarball.POLICY_LIMITS["pax_header_bytes"], 64 * 1024)
        self.assertEqual(tarball.POLICY_LIMITS["symlink_hops"], 40)
        self.assertEqual(tarball.POLICY_LIMITS["symlink_graph_steps"], 2_000_000)
        self.assertEqual(tarball.POLICY_LIMITS["tar_bytes"], 40 * 1024**3)
        self.assertEqual(tarball.POLICY_LIMITS["zstd_memory_mib"], 512)
        self.assertEqual(tarball.POLICY_LIMITS["identity_bytes"], 1024 * 1024)

    def test_tar_numeric_boundaries_match_non_pax_policy(self) -> None:
        maximum = (1 << 33) - 1
        self.assertEqual(tarball.MAX_FILE_BYTES, maximum)
        self.assertEqual(tarball.MAX_SOURCE_DATE_EPOCH, maximum)

        at_limit = tarball.tarfile.TarInfo("file")
        at_limit.size = maximum
        at_limit.mtime = maximum
        self.assertEqual(
            len(at_limit.tobuf(format=tarball.tarfile.PAX_FORMAT)),
            tarball.tarfile.BLOCKSIZE,
        )

        over_limit = tarball.tarfile.TarInfo("file")
        over_limit.size = maximum + 1
        over_limit.mtime = maximum + 1
        self.assertGreater(
            len(over_limit.tobuf(format=tarball.tarfile.PAX_FORMAT)),
            tarball.tarfile.BLOCKSIZE,
        )

        manifest = self._minimal_manifest()
        file_record = next(
            record for record in manifest["entries"] if record["path"] == "file"
        )
        file_record["size"] = maximum
        self.resign_manifest_identity(manifest)
        self.parse_manifest(
            self._canonical_manifest(manifest), self.public_key, self.openssl
        )
        file_record["size"] = maximum + 1
        self.resign_manifest_identity(manifest)
        with self.assertRaisesRegex(tarball.PackagingError, "file exceeds"):
            self.parse_manifest(
                self._canonical_manifest(manifest), self.public_key, self.openssl
            )

        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": str(maximum)}):
            self.assertEqual(tarball._source_date_epoch(), maximum)
        with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": str(maximum + 1)}):
            with self.assertRaisesRegex(tarball.PackagingError, "outside"):
                tarball._source_date_epoch()

    def test_path_and_symlink_target_limits_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(tarball.PackagingError, "path exceeds"):
            tarball._validate_relative_path("a" * (tarball.MAX_PATH_BYTES + 1))
        with self.assertRaisesRegex(tarball.PackagingError, "target exceeds"):
            tarball._validate_symlink("link", "a" * (tarball.MAX_TARGET_BYTES + 1))

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
        tarball._validate_elf_identity((2, 1, 183), "bin/application", "aarch64")
        header[18:20] = (183).to_bytes(2, "little")
        wrong = tarball._elf_identity(bytes(header), "bin/application")
        assert wrong is not None
        with self.assertRaisesRegex(tarball.PackagingError, "architecture mismatch"):
            tarball._validate_elf_identity(wrong, "bin/application", "x86_64")

    def test_symlink_graph_rejects_composed_escape(self) -> None:
        records = [
            ("a", "directory", None),
            ("a/redirect", "symlink", ".."),
            ("gateway", "symlink", "a/redirect/.."),
        ]
        with self.assertRaisesRegex(tarball.PackagingError, "composed symlink escapes"):
            tarball._validate_symlink_graph(records)

    def test_symlink_graph_rejects_cycles_and_excessive_depth(self) -> None:
        with self.assertRaisesRegex(tarball.PackagingError, "symlink cycle"):
            tarball._validate_symlink_graph(
                [("first", "symlink", "second"), ("second", "symlink", "first")]
            )

        records = [
            (f"link-{index}", "symlink", f"link-{index + 1}")
            for index in range(tarball.MAX_SYMLINK_HOPS)
        ]
        records.append((f"link-{tarball.MAX_SYMLINK_HOPS}", "symlink", "target"))
        records.append(("target", "file", None))
        with self.assertRaisesRegex(tarball.PackagingError, "resolution exceeds"):
            tarball._validate_symlink_graph(records)

        allowed = [
            (f"allowed-{index}", "symlink", f"allowed-{index + 1}")
            for index in range(tarball.MAX_SYMLINK_HOPS - 1)
        ]
        allowed.append((f"allowed-{tarball.MAX_SYMLINK_HOPS - 1}", "symlink", "target"))
        allowed.append(("target", "file", None))
        tarball._validate_symlink_graph(allowed)

    def test_symlink_graph_accepts_finite_revisit_state(self) -> None:
        tarball._validate_symlink_graph(
            [
                ("d", "directory", None),
                ("d/up", "symlink", ".."),
                ("file", "file", None),
                ("link", "symlink", "d/up/d/up/file"),
            ]
        )

    def test_symlink_graph_global_budget_bounds_shared_chains(self) -> None:
        records = [
            ("chain-0", "symlink", "chain-1"),
            ("chain-1", "symlink", "chain-2"),
            ("chain-2", "symlink", "target"),
            ("shared-a", "symlink", "chain-0"),
            ("shared-b", "symlink", "chain-0"),
            ("target", "file", None),
        ]
        with self.assertRaisesRegex(tarball.PackagingError, "work budget"):
            tarball._validate_symlink_graph(records, maximum_steps=18)
        tarball._validate_symlink_graph(records, maximum_steps=19)

    def test_symlink_graph_rejects_invalid_target_types(self) -> None:
        cases = (
            (
                [("file", "file", None), ("link", "symlink", "file/child")],
                "non-directory",
            ),
            ([("link", "symlink", "missing")], "dangling symlink"),
        )
        for records, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(tarball.PackagingError, message):
                    tarball._validate_symlink_graph(records)

    def test_manifest_verifier_rejects_composed_symlink_escape(self) -> None:
        manifest = self._minimal_manifest()
        manifest["entries"] = [
            {"mode": 0o755, "path": "a", "type": "directory"},
            {
                "mode": 0o777,
                "path": "a/redirect",
                "target": "..",
                "type": "symlink",
            },
            {
                "mode": 0o777,
                "path": "gateway",
                "target": "a/redirect/..",
                "type": "symlink",
            },
        ]
        with self.assertRaisesRegex(tarball.PackagingError, "composed symlink escapes"):
            self.parse_manifest(
                self._canonical_manifest(manifest), self.public_key, self.openssl
            )

    def test_invalid_identity_signature_precedes_entry_traversal(self) -> None:
        manifest = self._minimal_manifest()
        manifest["product_identity"]["payload"]["version"] = "0.1.0-dev.2"
        manifest["product_identity"]["payload"]["build_provenance"]["version"] = (
            "0.1.0-dev.2"
        )
        with mock.patch.object(
            tarball,
            "_validate_symlink_graph",
            side_effect=AssertionError("entry traversal must not run"),
        ) as graph:
            with self.assertRaisesRegex(
                tarball.PackagingError, "identity verification"
            ):
                self.parse_manifest(
                    self._canonical_manifest(manifest), self.public_key, self.openssl
                )
        graph.assert_not_called()

    def test_signed_identity_rejects_version_revision_hash_and_path_relabeling(self) -> None:
        mutations = (
            lambda payload: (
                payload.__setitem__("version", "0.1.0-dev.2"),
                payload["build_provenance"].__setitem__("version", "0.1.0-dev.2"),
            ),
            lambda payload: (
                payload.__setitem__("source_revision", "6" * 40),
                payload["build_provenance"].__setitem__("source_revision", "6" * 40),
            ),
            lambda payload: (
                payload["dependency_lock"].__setitem__("sha256", "7" * 64),
                payload["build_provenance"].__setitem__(
                    "dependency_lock_sha256", "7" * 64
                ),
            ),
            lambda payload: payload["executables"]["gui"].__setitem__(
                "path", "bin/renamed-openfusion"
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=repr(mutate)):
                envelope = self.sign_payload(self.signed_payload())
                mutate(envelope["payload"])
                with self.assertRaises(tarball.PackagingError):
                    self.verify_identity_envelope(
                        envelope, self.public_key, self.openssl
                    )

    def test_production_channel_requires_repository_spki_allowlist(self) -> None:
        payload = self.signed_payload(version="1.1.3")
        payload["release_channel"] = "production"
        envelope = self.sign_payload(payload)
        with self.assertRaisesRegex(tarball.PackagingError, "trust anchor"):
            tarball._verify_identity_envelope(
                envelope,
                self.public_key,
                self.openssl,
                self.key_sha256,
                "production",
            )

    def test_development_channel_requires_dev_prerelease(self) -> None:
        payload = self.signed_payload(version="1.1.3")
        with self.assertRaisesRegex(tarball.PackagingError, "dev SemVer"):
            tarball._validate_identity_payload(payload)

    def test_openssl_output_is_bounded_during_execution(self) -> None:
        with self.assertRaises(tarball.PackagingError):
            tarball._run_openssl(
                ["/bin/sh", "-c", "yes x | head -c 131072"],
                "hostile output fixture",
            )

    def test_expected_revision_arch_prefix_and_lock_are_mandatory(self) -> None:
        payload = self.signed_payload()
        cases = (
            (VERSION, "aarch64", "/opt/openfusion", SOURCE_REVISION, "5" * 64),
            (VERSION, "x86_64", "/wrong", SOURCE_REVISION, "5" * 64),
            (VERSION, "x86_64", "/opt/openfusion", "8" * 40, "5" * 64),
            (VERSION, "x86_64", "/opt/openfusion", SOURCE_REVISION, "9" * 64),
        )
        for coordinates in cases:
            with self.subTest(coordinates=coordinates):
                with self.assertRaisesRegex(tarball.PackagingError, "coordinates"):
                    tarball._validate_expected_identity_coordinates(payload, *coordinates)

    def test_manifest_epoch_swap_is_rejected_by_signed_identity(self) -> None:
        manifest = self._minimal_manifest()
        manifest["source_date_epoch"] = SOURCE_DATE_EPOCH + 1
        manifest["normalization"]["mtime"] = SOURCE_DATE_EPOCH + 1
        with self.assertRaisesRegex(tarball.PackagingError, "SOURCE_DATE_EPOCH"):
            self.parse_manifest(self._canonical_manifest(manifest))

    def test_missing_zstd_is_a_hard_error(self) -> None:
        with mock.patch.object(tarball.shutil, "which", return_value=None):
            with self.assertRaisesRegex(tarball.PackagingError, "zstd was not found"):
                tarball._find_zstd(None)

    def test_cli_exposes_no_identity_bypass(self) -> None:
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
                        VERSION,
                        "--architecture",
                        "x86_64",
                        "--output-dir",
                        "/tmp/output",
                        "--staging-is-quiescent",
                        "--identity-bypass",
                    ]
                )

    def test_companion_basename_validation_precedes_file_access(self) -> None:
        with self.assertRaisesRegex(tarball.PackagingError, "companion basenames"):
            self.verify_package(
                "/abs/package.tar.zst",
                "/abs/wrong.manifest.json",
                "/abs/package.tar.zst.sha256",
                self.public_key,
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
            (
                "policy version",
                lambda value: value["policy"].__setitem__("version", True),
            ),
            (
                "normalization uid",
                lambda value: value["normalization"].__setitem__("uid", False),
            ),
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
                    self.parse_manifest(
                        content, self.public_key, self.openssl
                    )

    def test_packaging_workflow_covers_merge_queue_and_requires_zstd(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "  merge_group:\n    types:\n      - checks_requested\n", workflow
        )
        self.assertIn("          command -v zstd\n", workflow)
        self.assertIn("          command -v openssl\n", workflow)
        self.assertIn("  clean-container-runtime:\n", workflow)
        self.assertIn("pixi run cmake --build build/release", workflow)
        self.assertIn("packaging/linux/runtime_closure.py bundle", workflow)
        self.assertIn("create_deterministic_tarball.py create-identity", workflow)
        self.assertIn("--network none --read-only", workflow)
        self.assertIn("OPENFUSION_CLEAN_CLI_SMOKE_OK", workflow)
        self.assertIn("OPENFUSION_CLEAN_GUI_SMOKE_OK", workflow)
        self.assertLess(
            workflow.index("Run network-isolated clean-container CLI and GUI lifecycle"),
            workflow.index("Upload verified development archive"),
        )
        upload_block = workflow.split("- name: Upload verified development archive", 1)[1]
        self.assertNotIn("if: always()", upload_block)
        self.assertNotIn("skipUnless", workflow)
        self.assertNotIn("    paths:\n", workflow)

    def test_installed_executable_names_are_openfusion_with_compatibility_aliases(self) -> None:
        content = MAIN_CMAKE.read_text(encoding="utf-8")
        self.assertIn("SET_BIN_DIR(FreeCADMain FreeCAD)", content)
        self.assertIn("SET_BIN_DIR(FreeCADMainCmd FreeCADCmd)", content)
        self.assertIn("copy_if_different", content)
        self.assertIn("OPENFUSION_VERSION_SUFFIX", content)
        self.assertEqual(
            content.count('INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"'),
            3,
        )
        self.assertIn("file(CREATE_LINK", content)
        self.assertIn("OpenFusionCmd", content)

    def test_archive_legal_policy_matches_source_quarantine_identities(self) -> None:
        policy = tarball._legal_quarantine_policy()
        pattern_spec = importlib.util.spec_from_file_location(
            "restricted_pattern_guard", RESTRICTED_PATTERN_GUARD
        )
        assert pattern_spec is not None and pattern_spec.loader is not None
        pattern_guard = importlib.util.module_from_spec(pattern_spec)
        pattern_spec.loader.exec_module(pattern_guard)
        expected_patterns = {
            (path, identity[1], identity[2])
            for path, identity in pattern_guard.RESTRICTED_PATTERN_BLOBS.items()
        }
        actual_patterns = {
            (record["source_path"], record["sha256"], record["size"])
            for record in policy["restricted_patterns"]
        }
        self.assertEqual(32, len(actual_patterns))
        self.assertEqual(expected_patterns, actual_patterns)

        thumbnail_spec = importlib.util.spec_from_file_location(
            "thumbnail_guard", THUMBNAIL_GUARD
        )
        assert thumbnail_spec is not None and thumbnail_spec.loader is not None
        thumbnail_guard = importlib.util.module_from_spec(thumbnail_spec)
        thumbnail_spec.loader.exec_module(thumbnail_guard)
        self.assertEqual(
            thumbnail_guard.INHERITED_PROVIDER_SHA256,
            policy["thumbnail_provider_sha256"],
        )
        self.assertEqual(
            set(thumbnail_guard.FORBIDDEN_INSTALLER_TEXT),
            set(policy["forbidden_text"]),
        )


class SnapshotPolicyTests(SignedIdentityMixin, unittest.TestCase):
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

    def test_source_scan_rejects_composed_symlink_escape(self) -> None:
        (self.source / "a").mkdir()
        os.symlink("..", self.source / "a" / "redirect")
        os.symlink("a/redirect/..", self.source / "gateway")
        with self.assertRaisesRegex(tarball.PackagingError, "composed symlink escapes"):
            self._scan()

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
                with self.assertRaisesRegex(
                    tarball.PackagingError, "membership changed"
                ):
                    tarball._scan_source_tree(
                        source, destination, 1_700_000_000, "x86_64"
                    )
        finally:
            os.close(destination)
            os.close(source)

    def _add_identity_executables(self) -> tuple[dict[str, object], bytes]:
        binary_dir = self.source / "bin"
        binary_dir.mkdir()
        gui = binary_dir / "OpenFusion"
        cli = binary_dir / "OpenFusionCmd"
        gui.write_bytes(valid_elf(b"snapshot-gui"))
        cli.write_bytes(valid_elf(b"snapshot-cli"))
        gui.chmod(0o755)
        cli.chmod(0o755)
        os.symlink("OpenFusion", binary_dir / "FreeCAD")
        os.symlink("OpenFusionCmd", binary_dir / "FreeCADCmd")
        (self.source / "share" / "openfusion").mkdir(parents=True)
        scan = self._scan()
        payload = self.signed_payload(
            gui_digest=hashlib.sha256(gui.read_bytes()).hexdigest(),
            cli_digest=hashlib.sha256(cli.read_bytes()).hexdigest(),
            gui_size=gui.stat().st_size,
            cli_size=cli.stat().st_size,
            payload_tree=tarball._payload_tree_commitment(scan.records),
        )
        envelope = self.sign_payload(payload)
        return payload, tarball._identity_envelope_bytes(envelope)

    def test_signed_snapshot_is_private_read_only_and_contains_identity(self) -> None:
        payload, identity_content = self._add_identity_executables()
        envelope = json.loads(identity_content)
        source = os.open(self.source, os.O_RDONLY | os.O_DIRECTORY)
        private = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        try:
            snapshot, returned_envelope, source_scan = tarball._create_private_snapshot(
                source,
                private,
                SOURCE_DATE_EPOCH,
                "x86_64",
                VERSION,
                "/opt/openfusion",
                identity_content,
                envelope,
                payload,
            )
            self.assertEqual(returned_envelope, envelope)
            self.assertEqual(len(source_scan.records), 7)
            self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o555)
            identity = snapshot / tarball.IDENTITY_RELATIVE_PATH
            self.assertEqual(identity.read_bytes(), identity_content)
            self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o444)
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


class ZstdIntegrationTests(SignedIdentityMixin, unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if shutil.which("zstd") is None:
            raise AssertionError(
                "zstd is required; the Linux packaging release gate must not be skipped"
            )

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
        self.lock_file = self.root / "pixi.lock"
        self.lock_file.write_bytes(b"locked dependency graph\n")
        self.lock_digest = hashlib.sha256(self.lock_file.read_bytes()).hexdigest()
        self.cmake_cache_file = self.root / "CMakeCache.txt"
        self.cmake_cache_file.write_bytes(b"canonical test cache\n")
        cmake_cache_sha256 = hashlib.sha256(
            self.cmake_cache_file.read_bytes()
        ).hexdigest()
        self.provenance_file = self.root / "build-provenance.json"
        self.provenance_file.write_bytes(
            tarball._canonical_json_bytes(
                self.provenance(
                    self.lock_digest,
                    cmake_cache_sha256=cmake_cache_sha256,
                )
            )
        )
        self.identity_file = self.root / "executable-identity.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _populate(self) -> None:
        self._ensure_executables()
        (self.prefix / "lib").mkdir()
        library = self.prefix / "lib" / "libOpenFusion.so.1"
        library.write_bytes(b"synthetic-library\x00payload")
        library.chmod(0o600)
        os.symlink("libOpenFusion.so.1", self.prefix / "lib" / "libOpenFusion.so")
        (self.prefix / "share").mkdir(exist_ok=True)
        (self.prefix / "share" / "openfusion").mkdir(exist_ok=True)
        (self.prefix / "share" / "Unicode-模型.txt").write_text(
            "model data\n", encoding="utf-8"
        )

    def _ensure_executables(self) -> None:
        binary_dir = self.prefix / "bin"
        binary_dir.mkdir(exist_ok=True)
        for name, marker in (("OpenFusion", b"integration-gui"), ("OpenFusionCmd", b"integration-cli")):
            executable = binary_dir / name
            if not executable.exists():
                executable.write_bytes(valid_elf(marker))
                executable.chmod(0o755)
        aliases = (("FreeCAD", "OpenFusion"), ("FreeCADCmd", "OpenFusionCmd"))
        for alias, target in aliases:
            alias_path = binary_dir / alias
            if not alias_path.exists() and not alias_path.is_symlink():
                os.symlink(target, alias_path)
        (self.prefix / "share" / "openfusion").mkdir(parents=True, exist_ok=True)
        legal_directory = self.prefix / "share" / "doc" / "openfusion"
        legal_directory.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE", "NOTICE.md", "THIRD_PARTY_NOTICES.md"):
            destination = legal_directory / name
            if not destination.exists():
                shutil.copyfile(Path(__file__).parents[2] / name, destination)

    def _identity(self) -> Path:
        self._ensure_executables()
        if not self.identity_file.exists():
            self.create_identity(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                "development",
                self.lock_file,
                self.provenance_file,
                self.private_key,
                self.identity_file,
                str(self.openssl),
            )
        return self.identity_file

    def _build(self, output: Path) -> tuple[Path, Path, Path]:
        return self.build_package(
            self.destdir,
            "/opt/openfusion",
            VERSION,
            "x86_64",
            output,
            SOURCE_DATE_EPOCH,
            self._identity(),
            self.public_key,
            staging_is_quiescent=True,
            output_is_exclusive=True,
        )

    def _verify(self, outputs: tuple[Path, Path, Path]) -> None:
        self.verify_package(
            *outputs,
            self.public_key,
        )

    def test_repeated_build_is_byte_identical_and_verifiable(self) -> None:
        self._populate()
        first = self._build(self.output_one)

        for path in self.prefix.rglob("*"):
            if not path.is_symlink():
                os.utime(path, (1_720_000_000, 1_720_000_000))
        (self.prefix / "bin" / "OpenFusion").chmod(0o777)
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
                "bin/FreeCAD",
                "bin/FreeCADCmd",
                "bin/OpenFusion",
                "bin/OpenFusionCmd",
                "lib",
                "lib/libOpenFusion.so",
                "lib/libOpenFusion.so.1",
                "share",
                "share/Unicode-模型.txt",
                "share/doc",
                "share/doc/openfusion",
                "share/doc/openfusion/LICENSE",
                "share/doc/openfusion/NOTICE.md",
                "share/doc/openfusion/THIRD_PARTY_NOTICES.md",
                "share/openfusion",
                "share/openfusion/executable-identity.json",
            ],
        )
        records = {record["path"]: record for record in manifest["entries"]}
        self.assertEqual(records["bin/OpenFusion"]["mode"], 0o755)
        self.assertEqual(records["lib/libOpenFusion.so.1"]["mode"], 0o644)
        self.assertEqual(
            records["lib/libOpenFusion.so"]["target"], "libOpenFusion.so.1"
        )
        artifact_digest = hashlib.sha256(first[0].read_bytes()).hexdigest()
        self.assertEqual(manifest["archive_sha256"], artifact_digest)
        self.assertEqual(manifest["architecture"], "x86_64")
        self.assertEqual(
            manifest["product_identity"]["payload"]["source_revision"],
            SOURCE_REVISION,
        )
        self.assertEqual(manifest["policy"]["version"], tarball.POLICY_VERSION)
        checksum_lines = first[2].read_text(encoding="ascii").splitlines()
        self.assertEqual(len(checksum_lines), 2)
        self.assertTrue(checksum_lines[0].endswith(f"  {first[0].name}"))
        self.assertTrue(checksum_lines[1].endswith(f"  {first[1].name}"))

    def test_verification_requires_the_matching_trusted_key(self) -> None:
        self._populate()
        outputs = self._build(self.output_one)
        other_private = self.root / "other-private.pem"
        other_public = self.root / "other-public.pem"
        subprocess.run(
            [str(self.openssl), "genpkey", "-algorithm", "ED25519", "-out", str(other_private)],
            check=True,
        )
        subprocess.run(
            [str(self.openssl), "pkey", "-in", str(other_private), "-pubout", "-out", str(other_public)],
            check=True,
        )
        with self.assertRaisesRegex(tarball.PackagingError, "fingerprint"):
            self.verify_package(*outputs, other_public)
        self._verify(outputs)

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

    def test_relabelled_x86_64_elf_cannot_reuse_signed_openfusion_identity(self) -> None:
        self._populate()
        identity = self._identity()
        executable = self.prefix / "bin" / "OpenFusion"
        executable.write_bytes(valid_elf(b"untrusted-relabel"))
        executable.chmod(0o755)
        with self.assertRaisesRegex(
            tarball.PackagingError, "payload-tree"
        ):
            self.build_package(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                self.output_one,
                SOURCE_DATE_EPOCH,
                identity,
                self.public_key,
                staging_is_quiescent=True,
                output_is_exclusive=True,
            )
        self.assertEqual(list(self.output_one.iterdir()), [])

    def test_signed_identity_rejects_package_version_swap(self) -> None:
        self._populate()
        identity = self._identity()
        with self.assertRaisesRegex(tarball.PackagingError, "package/source/lock coordinates"):
            self.build_package(
                self.destdir,
                "/opt/openfusion",
                "0.1.0-dev.2",
                "x86_64",
                self.output_one,
                SOURCE_DATE_EPOCH,
                identity,
                self.public_key,
                staging_is_quiescent=True,
                output_is_exclusive=True,
            )
        self.assertEqual(list(self.output_one.iterdir()), [])

    def test_identity_issuance_rejects_entrypoint_without_origin_runpath(self) -> None:
        self._ensure_executables()
        executable = self.prefix / "bin" / "OpenFusion"
        executable.write_bytes(
            valid_elf(b"no-origin").replace(
                b"$ORIGIN/../lib", b"missing-runpath"
            )
        )
        executable.chmod(0o755)
        with self.assertRaisesRegex(tarball.PackagingError, "RUNPATH"):
            self.create_identity(
                self.destdir, "/opt/openfusion", VERSION, "x86_64", "development",
                self.lock_file, self.provenance_file, self.private_key,
                self.identity_file, str(self.openssl),
            )

    def test_identity_creation_rejects_dependency_lock_swap(self) -> None:
        self._ensure_executables()
        self.lock_file.write_bytes(b"substituted dependency graph\n")
        with self.assertRaisesRegex(tarball.PackagingError, "version/lock/CMake/OpenSSL"):
            self.create_identity(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                "development",
                self.lock_file,
                self.provenance_file,
                self.private_key,
                self.identity_file,
                str(self.openssl),
            )

    def test_identity_issuance_rejects_missing_compatibility_alias(self) -> None:
        self._ensure_executables()
        (self.prefix / "bin" / "FreeCAD").unlink()
        with self.assertRaisesRegex(tarball.PackagingError, "compatibility executable"):
            self.create_identity(
                self.destdir, "/opt/openfusion", VERSION, "x86_64", "development",
                self.lock_file, self.provenance_file, self.private_key,
                self.identity_file, str(self.openssl),
            )

    def test_identity_issuance_rejects_retargeted_compatibility_alias(self) -> None:
        self._ensure_executables()
        alias = self.prefix / "bin" / "FreeCAD"
        alias.unlink()
        os.symlink("OpenFusionCmd", alias)
        with self.assertRaisesRegex(tarball.PackagingError, "compatibility executable"):
            self.create_identity(
                self.destdir, "/opt/openfusion", VERSION, "x86_64", "development",
                self.lock_file, self.provenance_file, self.private_key,
                self.identity_file, str(self.openssl),
            )

    def test_identity_issuance_rejects_regular_compatibility_alias(self) -> None:
        self._ensure_executables()
        alias = self.prefix / "bin" / "FreeCAD"
        alias.unlink()
        alias.write_bytes((self.prefix / "bin" / "OpenFusion").read_bytes())
        alias.chmod(0o755)
        with self.assertRaisesRegex(tarball.PackagingError, "compatibility executable"):
            self.create_identity(
                self.destdir, "/opt/openfusion", VERSION, "x86_64", "development",
                self.lock_file, self.provenance_file, self.private_key,
                self.identity_file, str(self.openssl),
            )

    def test_signed_identity_rejects_gui_cli_byte_swap(self) -> None:
        self._populate()
        identity = self._identity()
        gui = self.prefix / "bin" / "OpenFusion"
        cli = self.prefix / "bin" / "OpenFusionCmd"
        gui_bytes = gui.read_bytes()
        cli_bytes = cli.read_bytes()
        gui.write_bytes(cli_bytes)
        cli.write_bytes(gui_bytes)
        gui.chmod(0o755)
        cli.chmod(0o755)
        with self.assertRaisesRegex(tarball.PackagingError, "payload-tree"):
            self.build_package(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                self.output_one,
                SOURCE_DATE_EPOCH,
                identity,
                self.public_key,
                staging_is_quiescent=True,
                output_is_exclusive=True,
            )
        self.assertEqual(list(self.output_one.iterdir()), [])

    def test_signed_tree_rejects_tampered_shared_library(self) -> None:
        self._populate()
        identity = self._identity()
        library = self.prefix / "lib" / "libOpenFusion.so.1"
        library.write_bytes(b"tampered shared library")
        with self.assertRaisesRegex(tarball.PackagingError, "payload-tree"):
            self.build_package(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                self.output_one,
                SOURCE_DATE_EPOCH,
                identity,
                self.public_key,
                staging_is_quiescent=True,
                output_is_exclusive=True,
            )

    def test_rebuilt_archive_cannot_reauthorize_tampered_library(self) -> None:
        self._populate()
        artifact, manifest, _ = self._build(self.output_one)
        original_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        attacker_dir = self.root / "attacker"
        attacker_dir.mkdir()
        attacker_payload = self.root / "attacker-payload"
        shutil.copytree(self.prefix, attacker_payload, symlinks=True)
        identity_content = tarball._identity_envelope_bytes(
            original_manifest["product_identity"]
        )
        (attacker_payload / tarball.IDENTITY_RELATIVE_PATH).write_bytes(identity_content)
        (attacker_payload / "lib" / "libOpenFusion.so.1").write_bytes(b"rebuilt tamper")
        entries = tarball._scan_tree(attacker_payload)
        tar_path = attacker_dir / "rebuilt.tar"
        tarball._write_tar(
            tar_path,
            str(original_manifest["archive_root"]),
            entries,
            SOURCE_DATE_EPOCH,
        )
        rebuilt_artifact = attacker_dir / artifact.name
        tarball._compress(tar_path, rebuilt_artifact, tarball._find_zstd(None))
        rebuilt_manifest = attacker_dir / manifest.name
        rebuilt_manifest.write_bytes(
            tarball._manifest_bytes(
                artifact.name,
                manifest.name,
                f"{artifact.name}.sha256",
                str(original_manifest["archive_root"]),
                VERSION,
                "x86_64",
                "/opt/openfusion",
                SOURCE_DATE_EPOCH,
                entries,
                hashlib.sha256(rebuilt_artifact.read_bytes()).hexdigest(),
                original_manifest["product_identity"],
            )
        )
        rebuilt_checksum = attacker_dir / f"{artifact.name}.sha256"
        rebuilt_checksum.write_text(
            f"{hashlib.sha256(rebuilt_artifact.read_bytes()).hexdigest()}  {rebuilt_artifact.name}\n"
            f"{hashlib.sha256(rebuilt_manifest.read_bytes()).hexdigest()}  {rebuilt_manifest.name}\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(tarball.PackagingError, "payload-tree"):
            self.verify_package(rebuilt_artifact, rebuilt_manifest, rebuilt_checksum)

    def test_legal_scan_rejects_arr_metadata_without_filename_allowlist(self) -> None:
        self._populate()
        (self.prefix / "opaque-payload").write_bytes(
            b'General:\nLicense: "All rights reserved"\n'
        )
        with self.assertRaisesRegex(tarball.PackagingError, "redistribution permission"):
            self._build(self.output_one)

    def test_legal_scan_rejects_installer_tokens_in_any_payload_file(self) -> None:
        self._populate()
        fixtures = (
            b'RegDLL "$INSTDIR\\renamed-provider.bin"\n',
            b'<handler clsid="{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}" />\n',
            "RegDLL ".encode("utf-16le"),
            b"\xff\xfe\x00\x00" + "RegDLL ".encode("utf-32le"),
            "{E357FCCD-A995-4576-B01F-234630154E96}".encode("utf-32be"),
            b"x" * (tarball.LEGAL_SCAN_CHUNK_BYTES - 3)
            + "FILES_THUMBS".encode("utf-32le"),
        )
        for index, content in enumerate(fixtures):
            with self.subTest(index=index):
                if self.identity_file.exists():
                    self.identity_file.unlink()
                output = self.root / f"legal-output-{index}"
                output.mkdir()
                (self.prefix / f"opaque-{index}").write_bytes(content)
                with self.assertRaisesRegex(tarball.PackagingError, "thumbnail-provider text"):
                    self._build(output)
                (self.prefix / f"opaque-{index}").unlink()

    def test_legal_scan_allows_bare_regdll_binary_collision(self) -> None:
        self._populate()
        (self.prefix / "benign-binary-collision").write_bytes(
            b"\x01RegDLL\x00"
            + "RegDLL".encode("utf-16le")
            + "RegDLL".encode("utf-32le")
        )
        outputs = self._build(self.output_one)
        self._verify(outputs)

    def test_legal_scan_allows_internal_fcstd_thumbnail_symbol(self) -> None:
        self._populate()
        (self.prefix / "legitimate-start-symbol").write_bytes(
            b"loadFCStdThumbnail\x00FCStdThumbnail\x00"
        )
        outputs = self._build(self.output_one)
        self._verify(outputs)

    def test_legal_scan_rejects_utf32_arr_metadata_with_and_without_bom(self) -> None:
        self._populate()
        fixtures = (
            b"\x00\x00\xfe\xff"
            + "License: All rights reserved".encode("utf-32be"),
            b"x" * (tarball.LEGAL_SCAN_CHUNK_BYTES - 5)
            + "\nLicense: All rights reserved".encode("utf-32le"),
        )
        for index, content in enumerate(fixtures):
            with self.subTest(index=index):
                if self.identity_file.exists():
                    self.identity_file.unlink()
                output = self.root / f"legal-arr-output-{index}"
                output.mkdir()
                (self.prefix / f"opaque-arr-{index}").write_bytes(content)
                with self.assertRaisesRegex(
                    tarball.PackagingError, "redistribution permission"
                ):
                    self._build(output)
                (self.prefix / f"opaque-arr-{index}").unlink()

    def test_legal_scan_rejects_lfs_pointer_to_restricted_identity(self) -> None:
        self._populate()
        restricted = tarball._legal_quarantine_policy()["restricted_patterns"][0]
        pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{restricted['sha256']}\n"
            f"size {restricted['size']}\n"
        ).encode("ascii")
        (self.prefix / "renamed-lfs-object").write_bytes(pointer)
        with self.assertRaisesRegex(tarball.PackagingError, "Git LFS pointer"):
            self._build(self.output_one)

    def test_legal_scan_rejects_cross_platform_path_aliases(self) -> None:
        self._populate()
        (self.prefix / "Case-Alias").write_bytes(b"first")
        (self.prefix / "case-alias").write_bytes(b"second")
        with self.assertRaisesRegex(tarball.PackagingError, "path alias collision"):
            self._build(self.output_one)

    def test_legal_scan_rejects_trailing_dot_path_aliases(self) -> None:
        self._populate()
        (self.prefix / "notice").write_bytes(b"first")
        (self.prefix / "notice.").write_bytes(b"second")
        with self.assertRaisesRegex(tarball.PackagingError, "path alias collision"):
            self._build(self.output_one)

    def test_legal_scan_rejects_malformed_lfs_pointer(self) -> None:
        self._populate()
        (self.prefix / "malformed-pointer").write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:not-a-digest\nsize 12\n"
        )
        with self.assertRaisesRegex(tarball.PackagingError, "malformed.*Git LFS"):
            self._build(self.output_one)

    def test_legal_scan_requires_exact_shipped_notices(self) -> None:
        self._ensure_executables()
        notice = self.prefix / "share" / "doc" / "openfusion" / "NOTICE.md"
        notice.unlink()
        entries = tarball._scan_tree(self.prefix)
        with self.assertRaisesRegex(tarball.PackagingError, "required shipped legal file"):
            tarball._verify_legal_quarantine(self.prefix, entries)

        shutil.copyfile(Path(__file__).parents[2] / "NOTICE.md", notice)
        notice.write_bytes(b"substituted notice\n")
        entries = tarball._scan_tree(self.prefix)
        with self.assertRaisesRegex(tarball.PackagingError, "required shipped legal file"):
            tarball._verify_legal_quarantine(self.prefix, entries)

    def test_legal_scan_exact_hash_identity_is_path_independent(self) -> None:
        self._ensure_executables()
        payload = self.prefix / "renamed-asset.data"
        payload.write_bytes(b"synthetic quarantined identity")
        entries = tarball._scan_tree(self.prefix)
        record = next(entry for entry in entries if entry.relative_path == "renamed-asset.data")
        policy = json.loads(json.dumps(tarball._legal_quarantine_policy()))
        policy["restricted_patterns"][0] = {
            "source_path": "historical/restricted.FCMat",
            "sha256": record.sha256,
            "size": record.size,
        }
        with mock.patch.object(tarball, "_legal_quarantine_policy", return_value=policy):
            with self.assertRaisesRegex(tarball.PackagingError, "restricted material pattern"):
                tarball._verify_legal_quarantine(self.prefix, entries)

    def test_legal_scan_fails_closed_on_oversized_payload(self) -> None:
        self._ensure_executables()
        entries = tarball._scan_tree(self.prefix)
        with mock.patch.object(tarball, "MAX_LEGAL_SCAN_FILE_BYTES", 1):
            with self.assertRaisesRegex(tarball.PackagingError, "legal inspection limit"):
                tarball._verify_legal_quarantine(self.prefix, entries)

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
            self.build_package(
                self.destdir,
                "/opt/openfusion",
                VERSION,
                "x86_64",
                self.output_one,
                1_700_000_000,
                self._identity(),
                self.public_key,
                staging_is_quiescent=True,
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
        paths = [record["path"] for record in manifest["entries"]]
        self.assertEqual([path for path in paths if path.startswith("a")], ["a", "a-file", "a/z"])
        self._verify(outputs)

    def test_absolute_and_escaping_symlinks_are_rejected(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        os.symlink("/etc/passwd", self.prefix / "absolute")
        with self.assertRaisesRegex(tarball.PackagingError, "absolute symlink"):
            self._build(self.output_one)
        (self.prefix / "absolute").unlink()
        os.symlink("../../../../outside", self.prefix / "escape")
        with self.assertRaisesRegex(
            tarball.PackagingError, "escapes the packaged prefix"
        ):
            self._build(self.output_one)

    def test_fifo_is_rejected(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        os.mkfifo(self.prefix / "forbidden-fifo")
        with self.assertRaisesRegex(
            tarball.PackagingError, "special files are forbidden"
        ):
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
        with self.assertRaisesRegex(
            tarball.PackagingError, "without following symlinks"
        ):
            self._build(self.output_one)

    def test_existing_output_is_not_overwritten(self) -> None:
        (self.prefix / "file").write_bytes(b"payload")
        artifact = self.output_one / f"openfusion-{VERSION}-linux-x86_64.tar.zst"
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
            self.verify_package(
                artifact,
                manifest,
                checksum,
                self.public_key,
            )

    def test_tampered_checksum_fails_verification(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        checksum.write_text(f"{'0' * 64}  {artifact.name}\n", encoding="ascii")
        with self.assertRaisesRegex(tarball.PackagingError, "checksum file"):
            self.verify_package(
                artifact,
                manifest,
                checksum,
                self.public_key,
            )

    def test_canonical_manifest_rejects_added_fields_even_with_updated_checksum(
        self,
    ) -> None:
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
            self.verify_package(artifact, manifest, checksum, self.public_key)

    def test_symlinked_companion_directory_is_rejected(self) -> None:
        self._populate()
        artifact, manifest, checksum = self._build(self.output_one)
        alias = self.root / "output-alias"
        os.symlink(self.output_one.name, alias)
        with self.assertRaisesRegex(tarball.PackagingError, "cannot safely open"):
            self.verify_package(
                alias / artifact.name,
                alias / manifest.name,
                alias / checksum.name,
                self.public_key,
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
                        VERSION,
                        "--architecture",
                        "x86_64",
                        "--output-dir",
                        str(self.output_one),
                        "--identity",
                        str(self._identity()),
                        "--trusted-public-key",
                        str(self.public_key),
                        "--expected-key-sha256",
                        self.key_sha256,
                        "--expected-release-channel",
                        "development",
                        "--expected-source-revision",
                        SOURCE_REVISION,
                        "--expected-lock-sha256",
                        self.lock_digest,
                        "--staging-is-quiescent",
                    ]
                )
        finally:
            if previous is not None:
                os.environ["SOURCE_DATE_EPOCH"] = previous
        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
