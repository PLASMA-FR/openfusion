#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reject quarantined material-pattern assets and build references.

The inherited files identified below contain ``License: "All rights reserved"``
metadata.  That metadata does not establish downstream redistribution
permission, so the files are intentionally absent from OpenFusion source and
release inputs while their status remains unresolved.  This check anchors the
quarantine to original paths and content identities, and inspects all relevant
Git-tracked material and packaging inputs rather than a single source folder.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import List, NamedTuple, Sequence


# Each entry records the original path, Git blob OID, raw-content SHA-256, and
# byte length at the pinned FreeCAD foundation commit.  The Git OID makes the
# normal SHA-1 repository check cheap; SHA-256 plus size preserves the content
# identity across renames, extension changes, and Git object-format changes.
RESTRICTED_PATTERN_BLOBS = {
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal4.FCMat": (
        "17a4429d203b657f5b1b8d41b839bbd4ff15f5f7",
        "c0c8a05c6a074aec0f0d78a6c769c82690e533766c4290736e6e79f65f2854d6",
        445,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal5.FCMat": (
        "3c8e26d402c0e07ea0ea94cbd170d9353edb9e16",
        "090fcae64985163ee3a7a19223f0640883cdfb363850981e3e30dfdc843db21a",
        446,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond.FCMat": (
        "aa171216df2bc2fe42caf13b443197be5115103f",
        "16923cabb2c7cfe7dbc81a878f57df2f214dca05fb191a9c5c0c27588c605600",
        466,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond2.FCMat": (
        "d727ea94c58b1aa4469836bc93ad1a3002bba421",
        "68765620490e42199c3155e95a59dd20eaeceddce00232bd2299b2792b121715",
        468,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond4.FCMat": (
        "c338c3d00d72dea41e2a5cf8002404dd70e8dc3b",
        "6ac95fdb19b528b23113eb2d28b6e4d444bbf3b77ba555c42dbdca2b460b33e6",
        468,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Horizontal5.FCMat": (
        "3552b6bba998d4364a13631b9500d50267764466",
        "57c9da209ed1b83416f3bf9cf95269465b30d718a357bc6de3f8dbfe95a2c25b",
        447,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Square.FCMat": (
        "3cf218a692f4c473e0298a93aa8c8546ae890ad8",
        "50d949e0cdded9e06555b6f4aa99c525a9e9a4d75451189b6bf200e4078cf036",
        455,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/PAT/Vertical5.FCMat": (
        "a888f82eaf7de19c25c35c7bb620e9266f357773",
        "458704b204b62554971441cf58d90e9db60c1862a7fc07e334968f7c8f7413bd",
        443,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/aluminum.FCMat": (
        "90ec8c897973ddd5e509ecafe489b7b9380972a4",
        "d4b3509d7fab662defaa1ce8b304162911e47d3e14e97521a69d914e069cce48",
        4152,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/brick01.FCMat": (
        "9c9e0b872c379e812d6210c8f066ae360e387a10",
        "7d60d33569b14595f01c3b004d794ee70558a5c4cdda45290e2398415dc66c23",
        5379,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/concrete.FCMat": (
        "c67f68982ee7b8b2e2a65a31a53d45397537b929",
        "7fd139d97585882e99a1bc135fe3287510f29935a88e2340605a4dbf311defe4",
        5949,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cross.FCMat": (
        "cf7eaed3fb4cb7589a62a1f2855f224c28e7d47f",
        "c76fb05a6b50c1569297eb13ac777911197f71b0b6b83960facbf7dc0aac64a4",
        3595,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cuprous.FCMat": (
        "2328d710259c67b10a07a9e0b5b8dd2686881694",
        "b631e1203ef5aa36d46ac42578b808843dc0a983112b135f112d31a30d249a1b",
        13050,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal1.FCMat": (
        "eac8cabfa9d52fbc0cf82d1ae8fca3f02cc83329",
        "7d55cadafba01e22d04445e437050056814eb0cc674370e8761b723462117da7",
        16436,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal2.FCMat": (
        "8717e8c59c67c0198cef302438c0843bede6d702",
        "1774f34da05c2fe18d7c4c27de71da15e584171efc8f7103e173989a132ac53b",
        16380,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/earth.FCMat": (
        "00c831812c9362cadb5693ca650443ab9bfce516",
        "786a0cabb6323527f089699430c0d90eb0556761f8f56864c52c942c14a4ef57",
        4358,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/general_steel.FCMat": (
        "069b355ae9c0b336bf75eff8ef3d4251ff84958c",
        "c547b32db500b33e5c33ff3525265d3f76c907b23623119ac895636df33ef1e6",
        2943,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/glass.FCMat": (
        "37e6736d72a931db7e1c67a15ed388788bf5504f",
        "b1ae56530ad8e30ee9941b5a3e7f339181d6495c3e882392a8cbeb67eb84dcff",
        17308,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45L.FCMat": (
        "16c0abae8d235ca77aef41b1554931f2ac6ac668",
        "3c410f515ccce2e819dbc27c081d82320120eaeebd33c26798f29e7e0a592e99",
        2800,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45R.FCMat": (
        "cccb5ee1f6122417cb63525da38da6d5f8296ee9",
        "4a82feb6ef4dc87564cc1a96e708bd3329e105bb45b357b34edafe6744d176cd",
        2800,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hbone.FCMat": (
        "7768784551541dfc625e83fb49664d563bd2f454",
        "fdaa7e728d0258ac6f40561a0175c15859e416cc9f399ac50b0aef0b573f8e8e",
        8971,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/line.FCMat": (
        "80713096c1484f9d826084e64c40bce9371b8e04",
        "29c9014693158a0b4db5092fb80188d1b79d0d9c3c215a2785f58a5c7aa82525",
        1963,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plastic.FCMat": (
        "34f40aa0da5b15cb2f27bcf4480575f90634461b",
        "b1c0e1513dfbed3f62c4b5a1200c21c9619b3166579035a285277204fe0af66c",
        3905,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plus.FCMat": (
        "8ab7f45c9ea127d20e607c5faab5493111a7ffd4",
        "ec8577f84069e73ec6dcf93e56af602ae2e7d1b239e99f914c777c28b107adc5",
        3326,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/simple.FCMat": (
        "ba4663e536425bd96c218d3dfb91101a17fb5477",
        "454ae5203cea14b3bfda276c061e5567cb19c37da1708517884463274ae1ce61",
        2441,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/solid.FCMat": (
        "ada25db37e7c7c0d5027397d639f6de6a1a416fe",
        "a78e3caa7123f281737c50f5fe3205c93d889aee5939534101baf74e5264fce5",
        1716,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/square.FCMat": (
        "301cafe72acccaed75889284eb6dd65a13d1882b",
        "c7a5b39ccbb11c200f77739648af8dd144e8fa775505db3d8524ecd8d4a21afe",
        2646,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/steel.FCMat": (
        "16c9aede54eba6671a7db8aca9d625171aaced60",
        "5e8e6f1485d4162603d53acff8c0b4d51fdd6cbfa3489e769e086d3a9a8fb157",
        9071,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/titanium.FCMat": (
        "9067ab3a0afd915ddd841ff507a4757ee158714c",
        "d4465ffd97941944c1ac7aea9e3c014e779adcf719f0961ac230352d38727d5a",
        12243,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/wood.FCMat": (
        "5af0eb461c8ad8a01b35fc0d299f325bc16bd833",
        "53bd7ee224c8d5757214ceae5f203cb00d295efe6e74816d5f6a8f5b8f5f5515",
        19649,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/woodgrain.FCMat": (
        "68ed74332a60133408edb641af6f5bfdfa2b45d8",
        "57e4ecf40bc921794ea05eaa63ea06c6e6aab1711eeca684408e51217344a6be",
        4557,
    ),
    "src/Mod/Material/Resources/Materials/Patterns/Pattern Files/zinc.FCMat": (
        "348417a22ae024d780b4490359ed970b7a34dbae",
        "12da252c407211423ab0752d530ed0b99dde31fe124a5afa82ac9d9dc3fd8f07",
        4985,
    ),
}

RESTRICTED_PATTERN_PATHS = tuple(RESTRICTED_PATTERN_BLOBS)
MATERIAL_SOURCE_PREFIX = "src/Mod/Material/"
PATTERN_ROOT = Path("src/Mod/Material/Resources/Materials/Patterns")
LEGAL_QUARANTINE_POLICY_PATH = "packaging/linux/legal_quarantine.json"
LEGAL_QUARANTINE_POLICY_SHA256 = (
    "4dd36d5954b3ae05759842f2b1e2cc24c68a1826131b9a5dbc75de9330704603"
)
RESTRICTED_METADATA = re.compile(
    r"^\s*[\"']?License[\"']?\s*[:=]\s*[\"']?All\s+rights\s+reserved" r"(?:[\"']|\s|$)",
    re.IGNORECASE | re.MULTILINE,
)

_BUILD_MANIFEST_NAMES = {
    "build",
    "build.bazel",
    "cmakelists.txt",
    "configure.ac",
    "configure.in",
    "meson.build",
    "meson_options.txt",
    "sconscript",
    "sconstruct",
    "workspace",
}
_BUILD_MANIFEST_SUFFIXES = (
    ".cmake",
    ".cmake.in",
    ".iss",
    ".nsi",
    ".pri",
    ".pro",
    ".qrc",
    ".spec",
    ".wxi",
    ".wxs",
)
_PACKAGE_CONTEXT_PARTS = {
    ".github",
    "appimage",
    "build-aux",
    "cmake",
    "debian",
    "flatpak",
    "installer",
    "installers",
    "package",
    "packages",
    "packaging",
    "rpm",
    "snap",
    "workflows",
}
_PACKAGE_NAME_MARKERS = (
    "artifact",
    "bundle",
    "deploy",
    "install",
    "manifest",
    "package",
    "packaging",
)
_PACKAGE_TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".conf",
    ".ini",
    ".in",
    ".json",
    ".list",
    ".lst",
    ".manifest",
    ".plist",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


MAX_INSPECTED_BLOB_SIZE = 1024 * 1024
MAX_LFS_POINTER_SIZE = 1024
MAX_SUBMODULE_DEPTH = 8
LFS_POINTER = re.compile(
    rb"\Aversion https://git-lfs.github.com/spec/v1\n"
    rb"oid sha256:([0-9a-f]{64})\n"
    rb"size (0|[1-9][0-9]*)\n?\Z"
)


class _TrackedBlob(NamedTuple):
    relative: str
    mode: str
    oid: str
    size: int


class _Gitlink(NamedTuple):
    local_relative: str
    relative: str
    oid: str


class _InspectionError(RuntimeError):
    pass


def _stderr_text(completed: subprocess.CompletedProcess[bytes]) -> str:
    return completed.stderr.decode("utf-8", errors="replace").strip()


def _display_path(prefix: str, relative: str) -> str:
    return f"{prefix}/{relative}" if prefix else relative


def _git_index_entries(
    repo_root: Path, prefix: str
) -> tuple[list[_TrackedBlob], list[_Gitlink], list[str]]:
    """Return stage-zero blobs and gitlinks with fail-closed diagnostics."""

    violations: list[str] = []
    try:
        listed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--stage", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        return [], [], [f"cannot enumerate Git-tracked files in {repo_root}: {error}"]

    if listed.returncode != 0:
        detail = _stderr_text(listed) or f"git exited {listed.returncode}"
        return [], [], [f"cannot enumerate Git-tracked files in {repo_root}: {detail}"]

    restricted_paths = {
        original.casefold(): original for original in RESTRICTED_PATTERN_BLOBS
    }
    staged_blobs: list[tuple[str, str, str]] = []
    gitlinks: list[_Gitlink] = []
    for record in listed.stdout.split(b"\0"):
        if not record:
            continue
        try:
            header, path_bytes = record.split(b"\t", 1)
            mode_bytes, oid_bytes, stage_bytes = header.split(b" ", 2)
            mode = mode_bytes.decode("ascii")
            oid = oid_bytes.decode("ascii")
            stage = stage_bytes.decode("ascii")
            local_relative = os.fsdecode(path_bytes)
        except (UnicodeError, ValueError) as error:
            violations.append(f"cannot parse Git index entry in {repo_root}: {error}")
            continue

        path = PurePosixPath(local_relative)
        relative = _display_path(prefix, local_relative)
        original_path = restricted_paths.get(relative.casefold())
        if original_path is not None:
            violations.append(
                f"quarantined path is Git-tracked: {relative} "
                f"(identity: {original_path})"
            )

        if not local_relative or path.is_absolute() or ".." in path.parts:
            violations.append(f"unsafe Git-tracked path: {relative!r}")
            continue
        if stage != "0":
            violations.append(
                f"unmerged Git index entry cannot be inspected: {relative}"
            )
            continue
        if mode == "160000":
            gitlinks.append(_Gitlink(local_relative, relative, oid))
            continue
        if not (mode.startswith("100") or mode == "120000"):
            violations.append(f"unsupported Git index mode {mode} for: {relative}")
            continue
        staged_blobs.append((relative, mode, oid))

    if not staged_blobs:
        return [], gitlinks, violations

    unique_oids = tuple(dict.fromkeys(oid for _, _, oid in staged_blobs))
    batch_input = b"".join(f"{oid}\n".encode("ascii") for oid in unique_oids)
    try:
        checked = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "cat-file",
                "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            ],
            input=batch_input,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        violations.append(
            f"cannot inspect Git-tracked object metadata in {repo_root}: {error}"
        )
        return [], gitlinks, violations

    if checked.returncode != 0:
        detail = _stderr_text(checked) or f"git exited {checked.returncode}"
        violations.append(
            f"cannot inspect Git-tracked object metadata in {repo_root}: {detail}"
        )
        return [], gitlinks, violations

    object_lines = checked.stdout.splitlines()
    if len(object_lines) != len(unique_oids):
        violations.append(
            f"Git object metadata response count did not match the index in {repo_root}"
        )
        return [], gitlinks, violations

    sizes: dict[str, int] = {}
    for expected_oid, line in zip(unique_oids, object_lines):
        try:
            oid_bytes, kind, size_bytes = line.split(b" ", 2)
            oid = oid_bytes.decode("ascii")
            size = int(size_bytes)
        except (UnicodeError, ValueError) as error:
            violations.append(
                f"cannot parse Git object metadata for {expected_oid}: {error}"
            )
            continue
        if oid != expected_oid or kind != b"blob" or size < 0:
            violations.append(f"unexpected Git object metadata for: {expected_oid}")
            continue
        sizes[oid] = size

    tracked = [
        _TrackedBlob(relative, mode, oid, sizes[oid])
        for relative, mode, oid in staged_blobs
        if oid in sizes
    ]
    return tracked, gitlinks, violations


class _GitBlobReader:
    """Stream bounded Git objects from one persistent cat-file process."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._process = None

    def __enter__(self) -> "_GitBlobReader":
        try:
            self._process = subprocess.Popen(
                ["git", "-C", str(self.repo_root), "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise _InspectionError(
                f"cannot start Git blob reader in {self.repo_root}: {error}"
            ) from error
        if (
            self._process.stdin is None
            or self._process.stdout is None
            or self._process.stderr is None
        ):
            self._process.kill()
            self._process.wait()
            raise _InspectionError("Git blob reader did not provide all required pipes")
        return self

    def read(self, oid: str, expected_size: int) -> tuple[bytes, str]:
        if self._process is None:
            raise _InspectionError("Git blob reader is not active")
        if expected_size > MAX_INSPECTED_BLOB_SIZE:
            raise _InspectionError(
                f"refusing to buffer {expected_size} bytes for Git blob {oid}"
            )

        stdin = self._process.stdin
        stdout = self._process.stdout
        assert stdin is not None
        assert stdout is not None
        try:
            stdin.write(f"{oid}\n".encode("ascii"))
            stdin.flush()
            header = stdout.readline(256)
        except (OSError, UnicodeError) as error:
            raise _InspectionError(f"cannot request Git blob {oid}: {error}") from error

        if not header.endswith(b"\n"):
            raise _InspectionError(f"malformed Git cat-file header for {oid}")
        try:
            oid_bytes, kind, size_bytes = header[:-1].split(b" ", 2)
            reported_oid = oid_bytes.decode("ascii")
            reported_size = int(size_bytes)
        except (UnicodeError, ValueError) as error:
            raise _InspectionError(
                f"malformed Git cat-file header for {oid}: {error}"
            ) from error
        if reported_oid != oid or kind != b"blob" or reported_size != expected_size:
            raise _InspectionError(f"unexpected Git cat-file header for {oid}")

        remaining = reported_size
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        while remaining:
            chunk = stdout.read(min(65536, remaining))
            if not chunk:
                raise _InspectionError(f"truncated Git blob content for {oid}")
            digest.update(chunk)
            chunks.append(chunk)
            remaining -= len(chunk)
        if stdout.read(1) != b"\n":
            raise _InspectionError(f"missing Git cat-file terminator for {oid}")
        return b"".join(chunks), digest.hexdigest()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        process = self._process
        self._process = None
        if process is None:
            return False
        stdin = process.stdin
        stdout = process.stdout
        stderr = process.stderr
        diagnostic = ""
        returncode = -1
        try:
            if stdin is not None:
                try:
                    stdin.close()
                except OSError:
                    pass
            if exc_type is not None:
                process.kill()
            elif stderr is not None:
                diagnostic = stderr.read().decode("utf-8", errors="replace").strip()
        finally:
            try:
                returncode = process.wait()
            finally:
                if stdout is not None:
                    stdout.close()
                if stderr is not None:
                    stderr.close()

        if exc_type is None and returncode != 0:
            detail = diagnostic or f"git exited {returncode}"
            raise _InspectionError(f"Git blob reader failed: {detail}")
        return False


def _is_fcmat(relative: str) -> bool:
    return relative.casefold().endswith(".fcmat")


def _parse_lfs_pointer(content: bytes) -> tuple[str, int] | None:
    match = LFS_POINTER.fullmatch(content)
    if match is not None:
        return match.group(1).decode("ascii"), int(match.group(2))

    first_line = content.split(b"\n", 1)[0]
    pointer_shaped = (
        first_line.startswith(b"version https://git-lfs.github.com/spec/")
        or (
            b"git-lfs.github.com/spec/" in content
            and (b"\noid " in content or b"\nsize " in content)
        )
        or (
            content.startswith(b"version ")
            and b"\noid " in content
            and b"\nsize " in content
        )
        or (content.startswith(b"oid sha256:") and b"\nsize " in content)
    )
    if pointer_shaped:
        raise ValueError("malformed or unsupported Git LFS pointer")
    return None


def _is_build_or_package_manifest(relative: str) -> bool:
    path = PurePosixPath(relative)
    name = path.name.casefold()
    if name in _BUILD_MANIFEST_NAMES or name.startswith("makefile"):
        return True
    if any(name.endswith(suffix) for suffix in _BUILD_MANIFEST_SUFFIXES):
        return True

    parts = {part.casefold() for part in path.parts[:-1]}
    has_context = bool(parts & _PACKAGE_CONTEXT_PARTS) or any(
        marker in name for marker in _PACKAGE_NAME_MARKERS
    )
    return has_context and (
        path.suffix.casefold() in _PACKAGE_TEXT_SUFFIXES or not path.suffix
    )


def _reference_identities(original: str) -> tuple[str, ...]:
    prefixes = (
        MATERIAL_SOURCE_PREFIX,
        "src/Mod/Material/Resources/Materials/",
        f"{PATTERN_ROOT.as_posix()}/",
    )
    identities = {original}
    for prefix in prefixes:
        if original.startswith(prefix):
            identities.add(original.removeprefix(prefix))
    return tuple(sorted(identities, key=lambda identity: (-len(identity), identity)))


def _audit_blobs(
    repo_root: Path, blobs: Sequence[_TrackedBlob], violations: list[str]
) -> None:
    restricted_oids = {
        identity[0]: original for original, identity in RESTRICTED_PATTERN_BLOBS.items()
    }
    restricted_content = {
        (identity[1], identity[2]): original
        for original, identity in RESTRICTED_PATTERN_BLOBS.items()
    }
    restricted_sizes = {identity[2] for identity in RESTRICTED_PATTERN_BLOBS.values()}
    reference_sets = {
        original: _reference_identities(original)
        for original in RESTRICTED_PATTERN_BLOBS
    }

    candidates_by_oid: dict[str, list[_TrackedBlob]] = {}
    for entry in blobs:
        original_blob = restricted_oids.get(entry.oid)
        if original_blob is not None:
            violations.append(
                f"quarantined blob is Git-tracked as: {entry.relative} "
                f"(matches {original_blob}; oid={entry.oid})"
            )

        has_text_role = _is_fcmat(entry.relative) or _is_build_or_package_manifest(
            entry.relative
        )
        if has_text_role and entry.size > MAX_INSPECTED_BLOB_SIZE:
            violations.append(
                f"tracked FCMat/build-package manifest exceeds inspection limit: "
                f"{entry.relative} ({entry.size} > {MAX_INSPECTED_BLOB_SIZE} bytes)"
            )
            continue

        if (
            entry.size <= MAX_LFS_POINTER_SIZE
            or entry.size in restricted_sizes
            or has_text_role
        ):
            candidates_by_oid.setdefault(entry.oid, []).append(entry)

    if not candidates_by_oid:
        return

    try:
        with _GitBlobReader(repo_root) as reader:
            for oid, entries in candidates_by_oid.items():
                content, digest = reader.read(oid, entries[0].size)
                original_blob = restricted_content.get((digest, entries[0].size))
                if (
                    original_blob is not None
                    and restricted_oids.get(oid) != original_blob
                ):
                    for entry in entries:
                        violations.append(
                            f"quarantined blob content is Git-tracked as: "
                            f"{entry.relative} (matches {original_blob}; "
                            f"sha256={digest})"
                        )

                try:
                    pointer_identity = _parse_lfs_pointer(content)
                except ValueError:
                    for entry in entries:
                        violations.append(
                            "malformed or unsupported Git LFS pointer content: "
                            f"{entry.relative}"
                        )
                    pointer_identity = None
                if pointer_identity is not None:
                    pointer_oid, pointer_size = pointer_identity
                    pointer_match = next(
                        (
                            (source, quarantined_size)
                            for (
                                quarantined_oid,
                                quarantined_size,
                            ), source in restricted_content.items()
                            if quarantined_oid == pointer_oid
                        ),
                        None,
                    )
                    if pointer_match is not None:
                        pointer_source, quarantined_size = pointer_match
                        for entry in entries:
                            if pointer_size == quarantined_size:
                                violations.append(
                                    f"quarantined Git LFS object referenced by "
                                    f"tracked pointer: {entry.relative} (matches "
                                    f"{pointer_source}; oid=sha256:{pointer_oid}; "
                                    f"size={pointer_size})"
                                )
                            else:
                                violations.append(
                                    f"quarantined Git LFS object referenced by "
                                    f"tracked pointer with mismatched declared size: "
                                    f"{entry.relative} (matches {pointer_source}; "
                                    f"oid=sha256:{pointer_oid}; "
                                    f"declared-size={pointer_size}; "
                                    f"quarantined-size={quarantined_size})"
                                )

                text_entries = [
                    entry
                    for entry in entries
                    if _is_fcmat(entry.relative)
                    or _is_build_or_package_manifest(entry.relative)
                ]
                if not text_entries:
                    continue
                try:
                    text = content.decode("utf-8-sig")
                except UnicodeError as error:
                    for entry in text_entries:
                        role = (
                            "FCMat"
                            if _is_fcmat(entry.relative)
                            else "build/package manifest"
                        )
                        violations.append(
                            f"cannot inspect tracked {role} {entry.relative} "
                            f"as UTF-8: {error}"
                        )
                    continue

                normalized = re.sub(r"/+", "/", text.replace("\\", "/")).casefold()
                for entry in text_entries:
                    is_fcmat = _is_fcmat(entry.relative)
                    is_manifest = _is_build_or_package_manifest(entry.relative)
                    if entry.mode == "120000":
                        role = "FCMat" if is_fcmat else "build/package manifest"
                        violations.append(
                            f"tracked {role} is a symlink and cannot be inspected: "
                            f"{entry.relative}"
                        )
                        continue
                    if is_fcmat and RESTRICTED_METADATA.search(text):
                        violations.append(
                            "redistribution permission not established by tracked "
                            f"FCMat metadata: {entry.relative}"
                        )
                    if is_manifest:
                        if entry.relative == LEGAL_QUARANTINE_POLICY_PATH:
                            if digest != LEGAL_QUARANTINE_POLICY_SHA256:
                                violations.append(
                                    "reviewed legal quarantine policy has an "
                                    "unexpected content identity: "
                                    f"{entry.relative} (sha256={digest})"
                                )
                            continue
                        for original, identities in reference_sets.items():
                            for identity in identities:
                                if identity.casefold() in normalized:
                                    violations.append(
                                        "quarantined material path referenced by "
                                        f"build/package manifest {entry.relative}: "
                                        f"{identity} (identity: {original})"
                                    )
                                    break
    except _InspectionError as error:
        violations.append(f"cannot inspect Git-tracked blobs in {repo_root}: {error}")


def _git_text(repo_root: Path, *arguments: str) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        return None, str(error)
    if completed.returncode != 0:
        detail = _stderr_text(completed) or f"git exited {completed.returncode}"
        return None, detail
    try:
        return completed.stdout.decode("utf-8").strip(), None
    except UnicodeError as error:
        return None, str(error)


def _verified_submodule_checkout(
    parent_root: Path,
    gitlink: _Gitlink,
    boundary: Path,
    violations: list[str],
) -> Path | None:
    checkout = parent_root / gitlink.local_relative
    if not checkout.is_dir():
        violations.append(
            f"initialized submodule checkout missing for gitlink: {gitlink.relative}"
        )
        return None

    resolved = checkout.resolve()
    try:
        resolved.relative_to(boundary)
    except ValueError:
        violations.append(
            f"gitlink checkout escapes repository root: {gitlink.relative}"
        )
        return None

    top_level, top_error = _git_text(resolved, "rev-parse", "--show-toplevel")
    if top_error is not None or top_level is None:
        detail = top_error or "unknown Git error"
        violations.append(
            f"gitlink is not an initialized submodule checkout: "
            f"{gitlink.relative}: {detail}"
        )
        return None
    if Path(top_level).resolve() != resolved:
        violations.append(
            f"gitlink resolves to the wrong Git worktree: {gitlink.relative}"
        )
        return None

    head, head_error = _git_text(resolved, "rev-parse", "--verify", "HEAD^{commit}")
    if head_error is not None or head is None:
        detail = head_error or "unknown Git error"
        violations.append(
            f"cannot verify submodule HEAD for {gitlink.relative}: {detail}"
        )
        return None
    if head.casefold() != gitlink.oid.casefold():
        violations.append(
            f"submodule HEAD does not match recorded gitlink: {gitlink.relative} "
            f"(recorded={gitlink.oid}, checkout={head})"
        )
        return None

    try:
        index_check = subprocess.run(
            [
                "git",
                "-C",
                str(resolved),
                "diff-index",
                "--cached",
                "--quiet",
                gitlink.oid,
                "--",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        violations.append(
            f"cannot compare submodule index to recorded commit for "
            f"{gitlink.relative}: {error}"
        )
        return None
    if index_check.returncode == 1:
        violations.append(
            f"submodule index does not match recorded commit: {gitlink.relative}"
        )
        return None
    if index_check.returncode != 0:
        detail = _stderr_text(index_check) or f"git exited {index_check.returncode}"
        violations.append(
            f"cannot compare submodule index to recorded commit for "
            f"{gitlink.relative}: {detail}"
        )
        return None
    return resolved


def _audit_repository(
    repo_root: Path,
    prefix: str,
    depth: int,
    boundary: Path,
    visited: set[Path],
    violations: list[str],
) -> None:
    resolved = repo_root.resolve()
    if resolved in visited:
        location = prefix or "."
        violations.append(f"recursive gitlink checkout detected at: {location}")
        return
    visited.add(resolved)

    blobs, gitlinks, index_violations = _git_index_entries(resolved, prefix)
    violations.extend(index_violations)
    _audit_blobs(resolved, blobs, violations)

    for gitlink in gitlinks:
        if depth >= MAX_SUBMODULE_DEPTH:
            violations.append(
                f"submodule recursion limit exceeded at: {gitlink.relative}"
            )
            continue
        checkout = _verified_submodule_checkout(resolved, gitlink, boundary, violations)
        if checkout is None:
            continue
        _audit_repository(
            checkout,
            gitlink.relative,
            depth + 1,
            boundary,
            visited,
            violations,
        )


def find_violations(repo_root: Path) -> List[str]:
    """Return sorted quarantine violations from recursively tracked Git indexes."""

    root = repo_root.resolve()
    violations: list[str] = []
    _audit_repository(root, "", 0, root, set(), violations)
    return sorted(set(violations))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to the root containing this script)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    violations = find_violations(args.repo_root)
    if violations:
        print("Restricted material pattern guard: FAILED", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(
        "Restricted material pattern guard: PASS "
        f"({len(RESTRICTED_PATTERN_BLOBS)} source/index path and blob "
        "identities absent)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
