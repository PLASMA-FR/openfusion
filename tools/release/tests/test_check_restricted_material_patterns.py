# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_TOOLS))

from check_restricted_material_patterns import (  # noqa: E402
    LEGAL_QUARANTINE_POLICY_PATH,
    LEGAL_QUARANTINE_POLICY_SHA256,
    LFS_POINTER,
    MATERIAL_SOURCE_PREFIX,
    MAX_INSPECTED_BLOB_SIZE,
    PATTERN_ROOT,
    RESTRICTED_PATTERN_BLOBS,
    RESTRICTED_PATTERN_PATHS,
    _GitBlobReader,
    _InspectionError,
    find_violations,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RestrictedMaterialPatternsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo_root = Path(self.temporary_directory.name)
        self._git(self.repo_root, "init", "--quiet")

    def _git(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _track(self, relative: str | Path) -> None:
        self._git(self.repo_root, "add", "--", Path(relative).as_posix())

    def _write_bytes(self, relative: str | Path, contents: bytes) -> Path:
        destination = self.repo_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)
        self._track(relative)
        return destination

    def _write(self, relative: str | Path, contents: str) -> Path:
        return self._write_bytes(relative, contents.encode("utf-8"))

    def _add_gitlink(
        self,
        relative: str,
        files: dict[str, bytes] | None = None,
    ) -> tuple[Path, str]:
        checkout = self.repo_root / relative
        checkout.mkdir(parents=True, exist_ok=True)
        self._git(checkout, "init", "--quiet")
        self._git(checkout, "config", "user.name", "OpenFusion Test")
        self._git(checkout, "config", "user.email", "tests@openfusion.invalid")
        for child_relative, contents in (files or {}).items():
            destination = checkout / child_relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)
        self._git(checkout, "add", "--all")
        self._git(checkout, "commit", "--quiet", "--allow-empty", "-m", "fixture")
        head = self._git(checkout, "rev-parse", "HEAD").stdout.decode().strip()
        self._git(
            self.repo_root,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{head},{relative}",
        )
        return checkout, head

    def test_manifest_preserves_all_quarantined_path_and_blob_identities(self) -> None:
        self.assertEqual(32, len(RESTRICTED_PATTERN_BLOBS))
        self.assertEqual(RESTRICTED_PATTERN_PATHS, tuple(RESTRICTED_PATTERN_BLOBS))
        self.assertEqual(
            32, len({item[0] for item in RESTRICTED_PATTERN_BLOBS.values()})
        )
        self.assertEqual(
            32, len({item[1] for item in RESTRICTED_PATTERN_BLOBS.values()})
        )
        for relative, (oid, sha256, size) in RESTRICTED_PATTERN_BLOBS.items():
            self.assertTrue(relative.startswith(f"{PATTERN_ROOT.as_posix()}/"))
            self.assertTrue(relative.endswith(".FCMat"))
            self.assertRegex(oid, r"^[0-9a-f]{40}$")
            self.assertRegex(sha256, r"^[0-9a-f]{64}$")
            self.assertGreater(size, 0)

    def test_clean_tracked_fcmat_and_manifest_pass(self) -> None:
        self._write(
            "assets/materials/allowed.FCMAT",
            "General:\n  License: CC0-1.0\n",
        )
        self._write("packaging/materials.list", "assets/materials/allowed.FCMAT\n")
        self._write("src/Mod/Material/CMakeLists.txt", "# no quarantined patterns\n")
        self.assertEqual([], find_violations(self.repo_root))

    def test_exact_reviewed_legal_quarantine_policy_is_not_a_reference(self) -> None:
        policy = (PROJECT_ROOT / LEGAL_QUARANTINE_POLICY_PATH).read_bytes()
        self.assertEqual(
            LEGAL_QUARANTINE_POLICY_SHA256,
            hashlib.sha256(policy).hexdigest(),
        )
        self._write_bytes(LEGAL_QUARANTINE_POLICY_PATH, policy)
        self.assertEqual([], find_violations(self.repo_root))

    def test_modified_legal_quarantine_policy_fails_closed(self) -> None:
        self._write(LEGAL_QUARANTINE_POLICY_PATH, '{"format_version":1}\n')
        violations = find_violations(self.repo_root)
        self.assertTrue(
            any(
                violation.startswith(
                    "reviewed legal quarantine policy has an unexpected "
                    "content identity: packaging/linux/legal_quarantine.json"
                )
                for violation in violations
            ),
            violations,
        )

    def test_known_path_is_rejected_case_insensitively(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[0]
        tracked = restricted.upper()
        self._write(tracked, "General:\n  License: MIT\n")
        self.assertIn(
            f"quarantined path is Git-tracked: {tracked} (identity: {restricted})",
            find_violations(self.repo_root),
        )

    def test_exact_quarantined_path_is_rejected_when_it_is_a_gitlink(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[0]
        self._add_gitlink(restricted)
        self.assertIn(
            f"quarantined path is Git-tracked: {restricted} "
            f"(identity: {restricted})",
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
            "quarantined material path referenced by build/package manifest "
            f"packaging/CMakeLists.txt: {material_relative} "
            f"(identity: {restricted})",
            find_violations(self.repo_root),
        )

    def test_backslash_reference_is_rejected(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[8]
        material_relative = restricted.removeprefix(MATERIAL_SOURCE_PREFIX)
        windows_relative = material_relative.replace("/", "\\")
        self._write("CMakeLists.txt", f'set(PATTERN "{windows_relative}")\n')
        self.assertIn(
            "quarantined material path referenced by build/package manifest "
            f"CMakeLists.txt: {material_relative} (identity: {restricted})",
            find_violations(self.repo_root),
        )

    def test_moved_fcmat_with_quarantine_metadata_is_rejected(self) -> None:
        moved = "vendor/material-library/moved.FCMat"
        self._write(moved, 'General:\n  License: "All rights reserved"\n')
        self.assertIn(
            "redistribution permission not established by tracked FCMat "
            f"metadata: {moved}",
            find_violations(self.repo_root),
        )

    def test_uppercase_fcmat_extension_is_inspected(self) -> None:
        moved = "assets/material-library/replacement.FCMAT"
        self._write(moved, "General:\n  License = All Rights Reserved\n")
        self.assertIn(
            "redistribution permission not established by tracked FCMat "
            f"metadata: {moved}",
            find_violations(self.repo_root),
        )

    def test_renamed_non_fcmat_blob_is_rejected_by_sha256(self) -> None:
        payload = b"synthetic quarantined pattern blob\n"
        renamed = "assets/opaque-pattern.data"
        self._write_bytes(renamed, payload)
        original = RESTRICTED_PATTERN_PATHS[0]
        oid, _sha256, _size = RESTRICTED_PATTERN_BLOBS[original]
        digest = hashlib.sha256(payload).hexdigest()
        with mock.patch.dict(
            RESTRICTED_PATTERN_BLOBS,
            {original: (oid, digest, len(payload))},
        ):
            self.assertIn(
                f"quarantined blob content is Git-tracked as: {renamed} "
                f"(matches {original}; sha256={digest})",
                find_violations(self.repo_root),
            )

    def test_alternate_packaging_manifest_reference_is_rejected(self) -> None:
        restricted = RESTRICTED_PATTERN_PATHS[0]
        patterns_relative = restricted.removeprefix(f"{PATTERN_ROOT.as_posix()}/")
        self._write("packaging/materials.list", f"include={patterns_relative}\n")
        self.assertIn(
            "quarantined material path referenced by build/package manifest "
            f"packaging/materials.list: {patterns_relative} "
            f"(identity: {restricted})",
            find_violations(self.repo_root),
        )

    def test_recursive_submodule_fcmat_metadata_is_rejected(self) -> None:
        moved = "modules/materials/library/renamed.FCMAT"
        self._add_gitlink(
            "modules/materials",
            {"library/renamed.FCMAT": b"General:\nLicense: All rights reserved\n"},
        )
        self.assertIn(
            "redistribution permission not established by tracked FCMat "
            f"metadata: {moved}",
            find_violations(self.repo_root),
        )

    def test_recursive_submodule_forbidden_hash_is_rejected(self) -> None:
        payload = b"synthetic submodule quarantined blob\n"
        renamed = "modules/materials/assets/opaque.data"
        self._add_gitlink(
            "modules/materials",
            {"assets/opaque.data": payload},
        )
        original = RESTRICTED_PATTERN_PATHS[0]
        oid, _sha256, _size = RESTRICTED_PATTERN_BLOBS[original]
        digest = hashlib.sha256(payload).hexdigest()
        with mock.patch.dict(
            RESTRICTED_PATTERN_BLOBS,
            {original: (oid, digest, len(payload))},
        ):
            self.assertIn(
                f"quarantined blob content is Git-tracked as: {renamed} "
                f"(matches {original}; sha256={digest})",
                find_violations(self.repo_root),
            )

    def test_missing_submodule_checkout_fails_closed(self) -> None:
        checkout, _head = self._add_gitlink("modules/missing")
        shutil.rmtree(checkout)
        self.assertIn(
            "initialized submodule checkout missing for gitlink: modules/missing",
            find_violations(self.repo_root),
        )

    def test_mismatched_submodule_checkout_fails_closed(self) -> None:
        checkout, recorded = self._add_gitlink("modules/mismatched")
        (checkout / "change.txt").write_text("new commit\n", encoding="utf-8")
        self._git(checkout, "add", "change.txt")
        self._git(checkout, "commit", "--quiet", "-m", "advance")
        current = self._git(checkout, "rev-parse", "HEAD").stdout.decode().strip()
        self.assertIn(
            "submodule HEAD does not match recorded gitlink: modules/mismatched "
            f"(recorded={recorded}, checkout={current})",
            find_violations(self.repo_root),
        )

    def test_submodule_index_drift_fails_before_content_scan(self) -> None:
        checkout, _recorded = self._add_gitlink(
            "modules/index-drift",
            {"library/allowed.FCMat": b"General:\nLicense: MIT\n"},
        )
        self._git(checkout, "rm", "--cached", "library/allowed.FCMat")
        self.assertIn(
            "submodule index does not match recorded commit: modules/index-drift",
            find_violations(self.repo_root),
        )

    def test_canonical_lfs_pointer_to_quarantined_blob_is_rejected(self) -> None:
        original = RESTRICTED_PATTERN_PATHS[0]
        _oid, sha256, size = RESTRICTED_PATTERN_BLOBS[original]
        canonical_pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{sha256}\n"
            f"size {size}\n"
        )
        self.assertIsNotNone(LFS_POINTER.fullmatch(canonical_pointer.encode("ascii")))
        renamed = "assets/renamed-pattern.payload"
        self._write(renamed, canonical_pointer)
        self.assertIn(
            "quarantined Git LFS object referenced by tracked pointer: "
            f"{renamed} (matches {original}; oid=sha256:{sha256}; size={size})",
            find_violations(self.repo_root),
        )

        wrong_size = size + 1
        wrong_size_pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{sha256}\n"
            f"size {wrong_size}\n"
        )
        self.assertIsNotNone(LFS_POINTER.fullmatch(wrong_size_pointer.encode("ascii")))
        self._write(renamed, wrong_size_pointer)
        self.assertIn(
            "quarantined Git LFS object referenced by tracked pointer with "
            f"mismatched declared size: {renamed} (matches {original}; "
            f"oid=sha256:{sha256}; declared-size={wrong_size}; "
            f"quarantined-size={size})",
            find_violations(self.repo_root),
        )

    def test_malformed_lfs_pointer_fails_closed(self) -> None:
        relative = "assets/malformed-lfs.data"
        self._write(
            relative,
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:not-a-digest\n"
            "size 445\n",
        )
        self.assertIn(
            f"malformed or unsupported Git LFS pointer content: {relative}",
            find_violations(self.repo_root),
        )

    def test_extended_lfs_pointer_fails_closed(self) -> None:
        relative = "assets/extended-lfs.data"
        self._write(
            relative,
            "version https://git-lfs.github.com/spec/v1\n"
            "ext-0-example sha256:"
            f"{'0' * 64} https://example.invalid/object\n"
            f"oid sha256:{'1' * 64}\n"
            "size 445\n",
        )
        self.assertIn(
            f"malformed or unsupported Git LFS pointer content: {relative}",
            find_violations(self.repo_root),
        )

    def test_duplicate_oid_is_read_once(self) -> None:
        contents = "General:\nLicense: MIT\n"
        self._write("one.FCMat", contents)
        self._write("two.FCMat", contents)
        original_read = _GitBlobReader.read
        with mock.patch.object(
            _GitBlobReader,
            "read",
            autospec=True,
            side_effect=original_read,
        ) as read:
            self.assertEqual([], find_violations(self.repo_root))
            self.assertEqual(1, read.call_count)

    def test_oversized_fcmat_fails_closed_without_buffering(self) -> None:
        relative = "assets/oversized.FCMat"
        contents = b"General:\nLicense: MIT\n" + b"x" * MAX_INSPECTED_BLOB_SIZE
        self._write_bytes(relative, contents)
        self.assertIn(
            "tracked FCMat/build-package manifest exceeds inspection limit: "
            f"{relative} ({len(contents)} > {MAX_INSPECTED_BLOB_SIZE} bytes)",
            find_violations(self.repo_root),
        )

    def test_malformed_cat_file_response_fails_closed(self) -> None:
        process = mock.Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b"malformed\n")
        process.stderr = io.BytesIO()
        process.wait.return_value = 0
        with mock.patch(
            "check_restricted_material_patterns.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaisesRegex(_InspectionError, "malformed Git cat-file"):
                with _GitBlobReader(self.repo_root) as reader:
                    reader.read("0" * 40, 0)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)


class RepositoryQuarantineTest(unittest.TestCase):
    def test_repository_is_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.assertEqual([], find_violations(repo_root))


if __name__ == "__main__":
    unittest.main()
