"""Static release guard for the unaudited inherited Windows thumbnail provider."""

from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INSTALLER_RELATIVE_ROOT = Path("package") / "WindowsInstaller"
INSTALLER_ROOT = REPOSITORY_ROOT / INSTALLER_RELATIVE_ROOT
FORBIDDEN_PROVIDER_RELATIVE_PATH = (
    INSTALLER_RELATIVE_ROOT / "thumbnail" / "FCStdThumbnail.dll"
)
INHERITED_PROVIDER_SHA256 = (
    "cf9985aca43c116fe3565436a9da267de8b7f17ceed8c0cae000cfb40e69a1b0"
)
FORBIDDEN_INSTALLER_TEXT = {
    "FCStdThumbnail": "inherited provider filename or component name",
    "FILES_THUMBS": "inherited provider input directory",
    "{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}": "inherited provider CLSID",
    "{E357FCCD-A995-4576-B01F-234630154E96}": "thumbnail-handler interface",
    "RegDLL": "COM DLL registration directive",
}
REGULAR_BLOB_MODES = {"100644", "100755"}
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
VALID_INDEX_MODES = REGULAR_BLOB_MODES | {SYMLINK_MODE, GITLINK_MODE}
MAX_SUBMODULE_DEPTH = 16
LFS_POINTER_MAX_BYTES = 1024
LFS_OBJECT_MAX_SIZE = (1 << 63) - 1
LFS_VERSION_LINE = b"version https://git-lfs.github.com/spec/v1"
BLOB_STREAM_CHUNK_BYTES = 64 * 1024
FORBIDDEN_INSTALLER_TEXT_BYTES = {
    fragment: fragment.encode("ascii").upper() for fragment in FORBIDDEN_INSTALLER_TEXT
}
FORBIDDEN_TEXT_OVERLAP_BYTES = (
    max(len(pattern) for pattern in FORBIDDEN_INSTALLER_TEXT_BYTES.values()) - 1
)


@dataclass(frozen=True)
class IndexEntry:
    path: Path
    mode: str
    object_id: str


@dataclass(frozen=True)
class BlobInspection:
    size: int
    sha256: str
    lfs_prefix: bytes
    forbidden_text_fragments: tuple
    text_scanned: bool


def validate_object_id(value):
    if isinstance(value, bytes):
        try:
            object_id = value.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Git returned a non-ASCII object ID") from error
    else:
        object_id = value
    if not isinstance(object_id, str) or len(object_id) not in (40, 64):
        raise RuntimeError(f"Git returned an invalid object ID: {object_id!r}")
    try:
        int(object_id, 16)
    except ValueError as error:
        raise RuntimeError(
            f"Git returned an invalid object ID: {object_id!r}"
        ) from error
    return object_id.lower()


def validate_sha256(value):
    if isinstance(value, bytes):
        try:
            digest = value.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("SHA-256 digest is not ASCII") from error
    else:
        digest = value
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError(f"invalid SHA-256 digest: {digest!r}")
    try:
        int(digest, 16)
    except ValueError as error:
        raise RuntimeError(f"invalid SHA-256 digest: {digest!r}") from error
    return digest.lower()


def validate_relative_path(relative_path):
    if not isinstance(relative_path, Path):
        relative_path = Path(relative_path)
    if (
        relative_path == Path(".")
        or relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise RuntimeError(f"Git returned an unsafe tracked path: {relative_path!s}")
    return relative_path


def is_exact_forbidden_provider_path(relative_path):
    return relative_path.as_posix().casefold() == (
        FORBIDDEN_PROVIDER_RELATIVE_PATH.as_posix().casefold()
    )


def installer_subtree_parts(relative_path):
    path_parts = relative_path.parts
    installer_parts = INSTALLER_RELATIVE_ROOT.parts
    if len(path_parts) <= len(installer_parts):
        return None
    if tuple(part.casefold() for part in path_parts[: len(installer_parts)]) != tuple(
        part.casefold() for part in installer_parts
    ):
        return None
    return path_parts[len(installer_parts) :]


def is_installer_text_path(relative_path):
    """Select every non-test blob under the case-insensitive installer subtree."""

    installer_parts = installer_subtree_parts(relative_path)
    return installer_parts is not None and "tests" not in {
        part.casefold() for part in installer_parts
    }


def validate_audited_entry(entry):
    relative_path = validate_relative_path(entry.path)
    if entry.mode not in VALID_INDEX_MODES:
        raise RuntimeError(f"Git returned unsupported index mode: {entry.mode!r}")
    validate_object_id(entry.object_id)
    if is_exact_forbidden_provider_path(relative_path):
        raise RuntimeError(
            f"remove quarantined inherited provider path: {relative_path.as_posix()}"
        )
    if entry.mode == SYMLINK_MODE and is_installer_text_path(relative_path):
        raise RuntimeError(
            "installer source selection must not follow a tracked symlink: "
            f"{relative_path.as_posix()}"
        )


def repository_index_entries(repository_root=REPOSITORY_ROOT):
    """Return validated stage-zero index entries, retaining mode and object ID."""

    result = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "--stage", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    entries = []
    seen_paths = set()
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, encoded_path = record.split(b"\t", 1)
            encoded_mode, encoded_object_id, stage = metadata.split()
        except ValueError as error:
            raise RuntimeError("Git index returned malformed stage metadata") from error
        if stage != b"0":
            raise RuntimeError(
                "thumbnail quarantine guard requires an unconflicted index"
            )
        try:
            mode = encoded_mode.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Git index returned a non-ASCII mode") from error
        if mode not in VALID_INDEX_MODES:
            raise RuntimeError(f"Git index returned unsupported mode: {mode!r}")
        if not encoded_path:
            raise RuntimeError("Git index returned an empty tracked path")

        relative_path = validate_relative_path(Path(os.fsdecode(encoded_path)))
        object_id = validate_object_id(encoded_object_id)
        entry = IndexEntry(relative_path, mode, object_id)
        validate_audited_entry(entry)
        if relative_path in seen_paths:
            raise RuntimeError(
                f"Git index returned a duplicate path: {relative_path!s}"
            )
        seen_paths.add(relative_path)
        entries.append(entry)
    return tuple(entries)


def inspect_blob_stream(stream, size, scan_forbidden_text=False):
    if size < 0:
        raise RuntimeError("git cat-file returned a negative blob size")

    digest = hashlib.sha256()
    lfs_prefix = bytearray()
    matched_fragments = set()
    uppercase_overlap = b""
    remaining = size
    while remaining:
        requested = min(remaining, BLOB_STREAM_CHUNK_BYTES)
        chunk = stream.read(requested)
        if not chunk:
            raise RuntimeError(
                "git cat-file ended before returning the declared blob size"
            )
        if len(chunk) > requested:
            raise RuntimeError("git cat-file returned more blob data than requested")
        remaining -= len(chunk)
        digest.update(chunk)

        prefix_remaining = LFS_POINTER_MAX_BYTES - len(lfs_prefix)
        if prefix_remaining > 0:
            lfs_prefix.extend(chunk[:prefix_remaining])

        if scan_forbidden_text:
            uppercase_window = uppercase_overlap + chunk.upper()
            for fragment, pattern in FORBIDDEN_INSTALLER_TEXT_BYTES.items():
                if pattern in uppercase_window:
                    matched_fragments.add(fragment)
            uppercase_overlap = uppercase_window[-FORBIDDEN_TEXT_OVERLAP_BYTES:]

    return BlobInspection(
        size=size,
        sha256=digest.hexdigest(),
        lfs_prefix=bytes(lfs_prefix),
        forbidden_text_fragments=tuple(
            fragment
            for fragment in FORBIDDEN_INSTALLER_TEXT
            if fragment in matched_fragments
        ),
        text_scanned=scan_forbidden_text,
    )


def inspect_blob_bytes(contents, scan_forbidden_text=False):
    return inspect_blob_stream(
        io.BytesIO(contents), len(contents), scan_forbidden_text=scan_forbidden_text
    )


def coerce_blob_inspection(value, require_text_scan=False):
    if isinstance(value, bytes):
        value = inspect_blob_bytes(value, scan_forbidden_text=require_text_scan)
    if not isinstance(value, BlobInspection):
        raise RuntimeError(f"unsupported blob inspection value: {type(value)!r}")
    if value.size < 0:
        raise RuntimeError("blob inspection contains a negative size")
    validate_sha256(value.sha256)
    expected_prefix_size = min(value.size, LFS_POINTER_MAX_BYTES)
    if len(value.lfs_prefix) != expected_prefix_size:
        raise RuntimeError("blob inspection contains an invalid bounded LFS prefix")
    if require_text_scan and not value.text_scanned:
        raise RuntimeError("installer blob was not scanned for forbidden text")
    return value


def git_index_blob_groups(
    repository_root=REPOSITORY_ROOT, entries=None, scan_forbidden_text=False
):
    """Yield grouped exact Git objects for non-gitlink index entries."""

    if entries is None:
        entries = repository_index_entries(repository_root)

    entries_by_object_id = {}
    for entry in entries:
        validate_audited_entry(entry)
        if entry.mode == GITLINK_MODE:
            continue
        entries_by_object_id.setdefault(entry.object_id, []).append(entry)
    if not entries_by_object_id:
        return

    process = subprocess.Popen(
        ["git", "-C", str(repository_root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    completed = False
    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("failed to open git cat-file pipes")

        for object_id, grouped_entries in entries_by_object_id.items():
            process.stdin.write(object_id.encode("ascii") + b"\n")
            process.stdin.flush()

            header = process.stdout.readline()
            if not header.endswith(b"\n"):
                raise RuntimeError(
                    f"git cat-file returned an invalid header for {object_id}"
                )
            fields = header[:-1].split()
            if len(fields) == 2 and fields[1] == b"missing":
                raise RuntimeError(
                    f"Git index blob is missing from the object store: {object_id}"
                )
            if len(fields) != 3:
                raise RuntimeError(
                    f"git cat-file returned malformed metadata for {object_id}"
                )

            returned_object_id, object_type, encoded_size = fields
            if validate_object_id(returned_object_id) != object_id:
                raise RuntimeError(
                    f"git cat-file returned the wrong object for {object_id}"
                )
            if object_type != b"blob":
                raise RuntimeError(
                    f"Git index object {object_id} is {object_type!r}, not a blob"
                )
            if not encoded_size.isdigit():
                raise RuntimeError(
                    f"git cat-file returned an invalid size for {object_id}"
                )

            inspection = inspect_blob_stream(
                process.stdout,
                int(encoded_size),
                scan_forbidden_text=scan_forbidden_text,
            )
            if process.stdout.read(1) != b"\n":
                raise RuntimeError(
                    f"git cat-file returned invalid framing for {object_id}"
                )
            yield tuple(grouped_entries), inspection
        completed = True
    finally:
        stderr = b""
        return_code = None
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            if not completed and process.poll() is None:
                process.kill()
            stderr = process.stderr.read() if process.stderr is not None else b""
            return_code = process.wait()
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        if completed and return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"git cat-file failed with exit code {return_code}: {detail}"
            )


def git_output(repository_root, *arguments):
    result = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"git {' '.join(arguments)} failed with exit code "
            f"{result.returncode}: {detail}"
        )
    return result.stdout.rstrip(b"\r\n")


def path_identity(path):
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def verify_submodule_checkout(parent_root, gitlink_entry):
    parent_root = Path(parent_root).resolve(strict=True)
    checkout = parent_root / gitlink_entry.path
    if checkout.is_symlink():
        raise RuntimeError(
            f"gitlink checkout must not be a symlink: {gitlink_entry.path.as_posix()}"
        )
    try:
        resolved_checkout = checkout.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            f"required gitlink checkout is missing: {gitlink_entry.path.as_posix()}"
        ) from error
    if not resolved_checkout.is_dir():
        raise RuntimeError(
            f"gitlink checkout is not a directory: {gitlink_entry.path.as_posix()}"
        )
    try:
        resolved_checkout.relative_to(parent_root)
    except ValueError as error:
        raise RuntimeError(
            f"gitlink checkout escapes its repository: {gitlink_entry.path.as_posix()}"
        ) from error

    top_level = Path(
        os.fsdecode(git_output(resolved_checkout, "rev-parse", "--show-toplevel"))
    )
    if path_identity(top_level) != path_identity(resolved_checkout):
        raise RuntimeError(
            f"gitlink is not an initialized standalone checkout: {gitlink_entry.path.as_posix()}"
        )
    checkout_head = validate_object_id(
        git_output(resolved_checkout, "rev-parse", "--verify", "HEAD^{commit}")
    )
    if checkout_head != gitlink_entry.object_id:
        raise RuntimeError(
            f"gitlink checkout HEAD {checkout_head} does not match recorded "
            f"commit {gitlink_entry.object_id}: {gitlink_entry.path.as_posix()}"
        )

    index_check = subprocess.run(
        [
            "git",
            "-C",
            str(resolved_checkout),
            "diff-index",
            "--cached",
            "--quiet",
            gitlink_entry.object_id,
            "--",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if index_check.returncode == 1:
        raise RuntimeError(
            "gitlink index does not match its recorded commit: "
            f"{gitlink_entry.path.as_posix()}"
        )
    if index_check.returncode != 0:
        detail = index_check.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"could not verify gitlink index {gitlink_entry.path.as_posix()}: {detail}"
        )
    return resolved_checkout


def recursive_git_index_blob_groups(
    repository_root=REPOSITORY_ROOT,
    logical_prefix=Path(),
    include_entry=None,
    scan_forbidden_text=False,
    max_depth=MAX_SUBMODULE_DEPTH,
    _depth=0,
    _visited_paths=None,
):
    """Yield exact index blobs from a repository and every recorded gitlink."""

    if _depth > max_depth:
        raise RuntimeError(f"gitlink recursion exceeds maximum depth {max_depth}")
    try:
        resolved_root = Path(repository_root).resolve(strict=True)
    except OSError as error:
        raise RuntimeError(
            f"repository checkout is missing: {repository_root}"
        ) from error

    if _visited_paths is None:
        _visited_paths = set()
    identity = path_identity(resolved_root)
    if identity in _visited_paths:
        raise RuntimeError(f"gitlink checkout cycle or alias detected: {resolved_root}")
    _visited_paths.add(identity)

    local_entries = repository_index_entries(resolved_root)
    logical_entries = tuple(
        (
            local_entry,
            IndexEntry(
                logical_prefix / local_entry.path,
                local_entry.mode,
                local_entry.object_id,
            ),
        )
        for local_entry in local_entries
    )
    for _local_entry, logical_entry in logical_entries:
        validate_audited_entry(logical_entry)

    selected_local_entries = tuple(
        local_entry
        for local_entry, logical_entry in logical_entries
        if local_entry.mode != GITLINK_MODE
        and (include_entry is None or include_entry(logical_entry))
    )
    for grouped_entries, inspection in git_index_blob_groups(
        resolved_root,
        selected_local_entries,
        scan_forbidden_text=scan_forbidden_text,
    ):
        yield (
            tuple(
                IndexEntry(
                    logical_prefix / entry.path,
                    entry.mode,
                    entry.object_id,
                )
                for entry in grouped_entries
            ),
            inspection,
        )

    for local_entry, logical_entry in logical_entries:
        if local_entry.mode != GITLINK_MODE:
            continue
        if _depth >= max_depth:
            raise RuntimeError(f"gitlink recursion exceeds maximum depth {max_depth}")
        submodule_root = verify_submodule_checkout(resolved_root, local_entry)
        yield from recursive_git_index_blob_groups(
            submodule_root,
            logical_prefix=logical_entry.path,
            include_entry=include_entry,
            scan_forbidden_text=scan_forbidden_text,
            max_depth=max_depth,
            _depth=_depth + 1,
            _visited_paths=_visited_paths,
        )


def parse_git_lfs_pointer(inspection):
    """Parse a canonical small Git LFS v1 pointer, failing closed if malformed."""

    inspection = coerce_blob_inspection(inspection)
    if inspection.size > LFS_POINTER_MAX_BYTES or not inspection.lfs_prefix.startswith(
        LFS_VERSION_LINE
    ):
        return None
    contents = inspection.lfs_prefix
    body = contents[:-1] if contents.endswith(b"\n") else contents
    lines = body.split(b"\n")
    if (
        len(lines) != 3
        or lines[0] != LFS_VERSION_LINE
        or any(b"\r" in line for line in lines)
    ):
        raise RuntimeError("malformed canonical Git LFS v1 pointer")

    oid_prefix = b"oid sha256:"
    if not lines[1].startswith(oid_prefix):
        raise RuntimeError("Git LFS pointer does not contain a SHA-256 object ID")
    digest = validate_sha256(lines[1][len(oid_prefix) :])

    size_prefix = b"size "
    if not lines[2].startswith(size_prefix):
        raise RuntimeError("Git LFS pointer does not contain an object size")
    encoded_size = lines[2][len(size_prefix) :]
    if not encoded_size.isdigit() or (
        len(encoded_size) > 1 and encoded_size.startswith(b"0")
    ):
        raise RuntimeError("Git LFS pointer contains an invalid object size")
    object_size = int(encoded_size)
    if object_size > LFS_OBJECT_MAX_SIZE:
        raise RuntimeError("Git LFS pointer object size exceeds the supported range")
    return digest, object_size


def forbidden_provider_blob_paths(
    repository_root=REPOSITORY_ROOT,
    index_blob_groups=None,
    forbidden_sha256=INHERITED_PROVIDER_SHA256,
):
    forbidden_sha256 = validate_sha256(forbidden_sha256)
    if index_blob_groups is None:
        index_blob_groups = recursive_git_index_blob_groups(repository_root)

    matches = set()
    for entries, value in index_blob_groups:
        for entry in entries:
            validate_audited_entry(entry)
        inspection = coerce_blob_inspection(value)
        lfs_pointer = parse_git_lfs_pointer(inspection)
        raw_digest_matches = inspection.sha256 == forbidden_sha256
        lfs_digest_matches = (
            lfs_pointer is not None and lfs_pointer[0] == forbidden_sha256
        )
        if raw_digest_matches or lfs_digest_matches:
            matches.update(entry.path for entry in entries)
    return sorted(matches, key=lambda path: path.as_posix())


def forbidden_installer_text_references(
    repository_root=REPOSITORY_ROOT, index_blob_groups=None
):
    if index_blob_groups is None:
        index_blob_groups = recursive_git_index_blob_groups(
            repository_root,
            include_entry=lambda entry: is_installer_text_path(entry.path),
            scan_forbidden_text=True,
        )

    references = []
    for entries, value in index_blob_groups:
        installer_entries = []
        for entry in entries:
            validate_audited_entry(entry)
            if is_installer_text_path(entry.path):
                if entry.mode == SYMLINK_MODE:
                    raise RuntimeError(
                        "installer source selection must not follow a tracked symlink: "
                        f"{entry.path.as_posix()}"
                    )
                installer_entries.append(entry)
        if not installer_entries:
            continue

        inspection = coerce_blob_inspection(value, require_text_scan=True)
        for fragment, description in FORBIDDEN_INSTALLER_TEXT.items():
            if fragment not in inspection.forbidden_text_fragments:
                continue
            references.extend(
                (entry.path, fragment, description) for entry in installer_entries
            )
    return references


class ThumbnailProviderQuarantineTest(unittest.TestCase):
    @staticmethod
    def write_fixture_files(root, files):
        for relative_path, contents in files.items():
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(contents, bytes):
                destination.write_bytes(contents)
            else:
                destination.write_text(contents, encoding="utf-8")

    @staticmethod
    def fixture_git(root, *arguments):
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise AssertionError(
                f"fixture git {' '.join(arguments)} failed with exit code "
                f"{result.returncode}: {detail}"
            )
        return result.stdout.rstrip(b"\r\n")

    @staticmethod
    def synthetic_entry(path, mode="100644"):
        path = Path(path)
        object_id = hashlib.sha1(path.as_posix().encode("utf-8")).hexdigest()
        return IndexEntry(path, mode, object_id)

    def initialize_staged_repository(self, root, files):
        result = subprocess.run(
            ["git", "init", "--quiet", str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise AssertionError(f"fixture git init failed: {detail}")
        self.write_fixture_files(root, files)
        self.fixture_git(root, "add", "--all")

    def commit_staged_repository(self, root, message):
        self.fixture_git(
            root,
            "-c",
            "user.name=OpenFusion Tests",
            "-c",
            "user.email=openfusion-tests@example.invalid",
            "commit",
            "--quiet",
            "-m",
            message,
        )
        return validate_object_id(
            self.fixture_git(root, "rev-parse", "--verify", "HEAD^{commit}")
        )

    def add_gitlink(self, repository_root, relative_path, commit_id):
        self.fixture_git(
            repository_root,
            "update-index",
            "--add",
            "--cacheinfo",
            GITLINK_MODE,
            commit_id,
            relative_path.as_posix(),
        )

    def test_inherited_provider_binary_is_not_in_any_tracked_blob(self):
        matches = forbidden_provider_blob_paths()
        self.assertFalse(
            matches,
            "remove unaudited inherited COM server blob(s): "
            + ", ".join(path.as_posix() for path in matches),
        )

    def test_repository_wide_hash_guard_rejects_filename_evasions(self):
        payload = b"\x00OpenFusion inherited provider fixture\xff"
        forbidden_digest = hashlib.sha256(payload).hexdigest()
        evasive_entries = tuple(
            self.synthetic_entry(path)
            for path in (
                "src/relocated/provider.payload",
                "resources/windows/RENAMED.DLL",
                "vendor/thumbnail-provider",
            )
        )
        clean_entry = self.synthetic_entry("package/WindowsInstaller/setup/clean.nsi")
        blob_groups = (
            (evasive_entries, payload),
            ((clean_entry,), b'Section "OpenFusion"\nSectionEnd\n'),
        )

        matches = forbidden_provider_blob_paths(
            index_blob_groups=blob_groups,
            forbidden_sha256=forbidden_digest,
        )

        self.assertEqual(
            sorted(
                (entry.path for entry in evasive_entries),
                key=lambda path: path.as_posix(),
            ),
            matches,
        )

    def test_text_guard_rejects_regdll_and_thumbnail_clsids(self):
        registration_entry = self.synthetic_entry(
            "package/WindowsInstaller/setup/provider.nsi"
        )
        manifest_entry = self.synthetic_entry(
            "package/WindowsInstaller/setup/provider.manifest"
        )
        blob_groups = (
            ((registration_entry,), b'RegDLL "$INSTDIR\\renamed-provider.bin"\n'),
            (
                (manifest_entry,),
                b'<handler clsid="{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}" />\n',
            ),
        )

        references = forbidden_installer_text_references(index_blob_groups=blob_groups)

        found = {
            (path, fragment.upper()) for path, fragment, _description in references
        }
        self.assertIn((registration_entry.path, "REGDLL"), found)
        self.assertIn(
            (manifest_entry.path, "{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}"),
            found,
        )

    def test_installer_scope_is_case_insensitive_for_windows_paths(self):
        registration_entry = self.synthetic_entry(
            "PACKAGE/windowsinstaller/setup/provider-fragment"
        )

        references = forbidden_installer_text_references(
            index_blob_groups=(
                ((registration_entry,), b'RegDLL "$INSTDIR\\renamed-provider.bin"\n'),
            )
        )

        self.assertIn(
            (registration_entry.path, "REGDLL"),
            {(path, fragment.upper()) for path, fragment, _ in references},
        )

    def test_extensionless_and_inc_installer_fragments_are_scanned(self):
        extensionless_entry = self.synthetic_entry(
            "package/WindowsInstaller/setup/register-provider"
        )
        include_entry = self.synthetic_entry(
            "package/WindowsInstaller/setup/provider.inc"
        )
        references = forbidden_installer_text_references(
            index_blob_groups=(
                ((extensionless_entry,), b'RegDLL "$INSTDIR\\provider.bin"\n'),
                (
                    (include_entry,),
                    b"{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}\n",
                ),
            )
        )

        found = {(path, fragment.upper()) for path, fragment, _ in references}
        self.assertIn((extensionless_entry.path, "REGDLL"), found)
        self.assertIn(
            (include_entry.path, "{4BBBEAB5-BE00-41F4-A209-FE838660B9B1}"),
            found,
        )

    def test_large_tracked_blob_is_hashed_with_bounded_capture(self):
        large_path = Path("assets/large-provider-decoy.bin")
        write_chunk = b"x" * BLOB_STREAM_CHUNK_BYTES
        repetitions = 64
        expected_digest = hashlib.sha256()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(root, {Path("README.txt"): "root\n"})
            destination = root / large_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as stream:
                for _ in range(repetitions):
                    stream.write(write_chunk)
                    expected_digest.update(write_chunk)
            self.fixture_git(root, "add", "--", large_path.as_posix())

            large_inspection = None
            for entries, inspection in recursive_git_index_blob_groups(root):
                if any(entry.path == large_path for entry in entries):
                    large_inspection = inspection
                    break

        self.assertIsNotNone(large_inspection)
        self.assertEqual(BLOB_STREAM_CHUNK_BYTES * repetitions, large_inspection.size)
        self.assertEqual(expected_digest.hexdigest(), large_inspection.sha256)
        self.assertEqual(LFS_POINTER_MAX_BYTES, len(large_inspection.lfs_prefix))
        self.assertFalse(large_inspection.text_scanned)

    def test_installer_text_symlink_is_rejected_before_hidden_regdll(self):
        symlink_entry = self.synthetic_entry(
            "package/WindowsInstaller/setup/provider.nsi", mode=SYMLINK_MODE
        )
        hidden_entry = self.synthetic_entry("hidden/provider.nsi")
        blob_groups = (
            ((symlink_entry,), b"../../../hidden/provider.nsi"),
            ((hidden_entry,), b'RegDLL "$INSTDIR\\hidden-provider.dll"\n'),
        )

        with self.assertRaisesRegex(RuntimeError, "tracked symlink"):
            forbidden_installer_text_references(index_blob_groups=blob_groups)

    def test_exact_provider_path_is_rejected_even_for_a_gitlink(self):
        gitlink_entry = self.synthetic_entry(
            FORBIDDEN_PROVIDER_RELATIVE_PATH, mode=GITLINK_MODE
        )

        with self.assertRaisesRegex(
            RuntimeError, "quarantined inherited provider path"
        ):
            forbidden_provider_blob_paths(index_blob_groups=(((gitlink_entry,), b""),))

    def test_git_lfs_pointer_to_inherited_provider_is_rejected(self):
        pointer_path = Path("assets/renamed-provider")
        pointer = (
            f"version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{INHERITED_PROVIDER_SHA256}\n"
            "size 65536\n"
        ).encode("ascii")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(root, {pointer_path: pointer})
            matches = forbidden_provider_blob_paths(root)

        self.assertEqual([pointer_path], matches)

        malformed_pointer = pointer.replace(b"size 65536", b"size unknown")
        malformed_entry = self.synthetic_entry(pointer_path)
        with self.assertRaisesRegex(RuntimeError, "invalid object size"):
            forbidden_provider_blob_paths(
                index_blob_groups=(((malformed_entry,), malformed_pointer),)
            )

    def test_gitlinks_scan_exact_recorded_commit_recursively(self):
        provider_payload = b"\x00recursive inherited provider fixture\xff"
        forbidden_digest = hashlib.sha256(provider_payload).hexdigest()
        child_path = Path("package/WindowsInstaller/vendor/provider-module")
        grandchild_path = Path("nested/grandchild")
        direct_binary = Path("RENAMED.DLL")
        recursive_binary = Path("payload-without-extension")
        registration = Path("setup/register.nsi")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(root, {Path("README.txt"): "root\n"})

            child_root = root / child_path
            self.initialize_staged_repository(
                child_root,
                {
                    direct_binary: provider_payload,
                    registration: 'RegDLL "$INSTDIR\\renamed-provider.bin"\n',
                },
            )
            grandchild_root = child_root / grandchild_path
            self.initialize_staged_repository(
                grandchild_root, {recursive_binary: provider_payload}
            )
            grandchild_commit = self.commit_staged_repository(
                grandchild_root, "test: add recursive provider fixture"
            )
            self.add_gitlink(child_root, grandchild_path, grandchild_commit)
            child_commit = self.commit_staged_repository(
                child_root, "test: add nested gitlink fixture"
            )
            self.add_gitlink(root, child_path, child_commit)

            matches = forbidden_provider_blob_paths(
                root, forbidden_sha256=forbidden_digest
            )
            references = forbidden_installer_text_references(root)

        expected_matches = sorted(
            (
                child_path / direct_binary,
                child_path / grandchild_path / recursive_binary,
            ),
            key=lambda path: path.as_posix(),
        )
        self.assertEqual(expected_matches, matches)
        self.assertIn(
            (child_path / registration, "REGDLL"),
            {(path, fragment.upper()) for path, fragment, _ in references},
        )

    def test_missing_and_mismatched_gitlink_checkouts_fail_closed(self):
        child_path = Path("dependencies/child")

        with self.subTest(state="missing"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.initialize_staged_repository(root, {Path("README.txt"): "root\n"})
                child_root = root / child_path
                self.initialize_staged_repository(
                    child_root, {Path("payload.txt"): "clean\n"}
                )
                child_commit = self.commit_staged_repository(
                    child_root, "test: add clean child"
                )
                self.add_gitlink(root, child_path, child_commit)
                shutil.rmtree(child_root)

                with self.assertRaisesRegex(RuntimeError, "checkout is missing"):
                    forbidden_provider_blob_paths(root)

        with self.subTest(state="mismatched"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                self.initialize_staged_repository(root, {Path("README.txt"): "root\n"})
                child_root = root / child_path
                self.initialize_staged_repository(
                    child_root, {Path("payload.txt"): "first\n"}
                )
                recorded_commit = self.commit_staged_repository(
                    child_root, "test: add first child commit"
                )
                self.add_gitlink(root, child_path, recorded_commit)
                self.write_fixture_files(child_root, {Path("payload.txt"): "second\n"})
                self.fixture_git(child_root, "add", "--all")
                self.commit_staged_repository(
                    child_root, "test: move child checkout head"
                )

                with self.assertRaisesRegex(
                    RuntimeError, "does not match recorded commit"
                ):
                    forbidden_provider_blob_paths(root)

    def test_clean_legitimate_submodule_is_audited(self):
        child_path = Path("package/WindowsInstaller/vendor/legitimate-module")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(root, {Path("README.txt"): "root\n"})
            child_root = root / child_path
            self.initialize_staged_repository(
                child_root,
                {Path("setup/configure.nsh"): 'Section "Legitimate"\nSectionEnd\n'},
            )
            child_commit = self.commit_staged_repository(
                child_root, "test: add legitimate child"
            )
            self.add_gitlink(root, child_path, child_commit)

            blob_matches = forbidden_provider_blob_paths(root)
            text_references = forbidden_installer_text_references(root)

        self.assertEqual([], blob_matches)
        self.assertEqual([], text_references)

    def test_staged_forbidden_blobs_survive_worktree_replacement_and_deletion(self):
        provider_payload = b"\x00staged inherited provider fixture\xff"
        forbidden_digest = hashlib.sha256(provider_payload).hexdigest()
        binary_path = Path("relocated/RENAMED.DLL")
        registration_path = Path("package/WindowsInstaller/setup/provider.nsi")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(
                root,
                {
                    binary_path: provider_payload,
                    registration_path: 'RegDLL "$INSTDIR\\renamed-provider.bin"\n',
                },
            )
            (root / binary_path).write_bytes(b"clean replacement")
            (root / registration_path).unlink()

            blob_matches = forbidden_provider_blob_paths(
                root, forbidden_sha256=forbidden_digest
            )
            text_references = forbidden_installer_text_references(root)

        self.assertEqual([binary_path], blob_matches)
        self.assertIn(
            (registration_path, "REGDLL"),
            {(path, fragment.upper()) for path, fragment, _ in text_references},
        )

    def test_clean_index_ignores_dirty_and_untracked_forbidden_bytes(self):
        provider_payload = b"\x00dirty inherited provider fixture\xff"
        forbidden_digest = hashlib.sha256(provider_payload).hexdigest()
        tracked_binary = Path("resources/windows/provider.bin")
        tracked_script = Path("package/WindowsInstaller/setup/configure.nsh")
        untracked_binary = Path("build/package/FCStdThumbnail.DLL")
        untracked_script = Path("build/package/register-provider.nsi")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_staged_repository(
                root,
                {
                    tracked_binary: b"clean staged binary",
                    tracked_script: 'Section "OpenFusion"\nSectionEnd\n',
                },
            )
            self.write_fixture_files(
                root,
                {
                    tracked_binary: provider_payload,
                    tracked_script: 'RegDLL "$INSTDIR\\FCStdThumbnail.dll"\n',
                    untracked_binary: provider_payload,
                    untracked_script: (
                        'RegDLL "$INSTDIR\\FCStdThumbnail.dll"\n'
                        "; {E357FCCD-A995-4576-B01F-234630154E96}\n"
                    ),
                },
            )

            blob_matches = forbidden_provider_blob_paths(
                root, forbidden_sha256=forbidden_digest
            )
            text_references = forbidden_installer_text_references(root)

        self.assertEqual([], blob_matches)
        self.assertEqual([], text_references)

    def test_installer_has_no_thumbnail_provider_actions(self):
        references = forbidden_installer_text_references()
        self.assertFalse(
            references,
            "remove inherited thumbnail-provider action(s): "
            + "; ".join(
                f"{path.as_posix()}: {fragment} ({description})"
                for path, fragment, description in references
            ),
        )

    def test_fcstd_open_and_icon_association_remains(self):
        configure = (INSTALLER_ROOT / "setup" / "configure.nsh").read_text(
            encoding="utf-8-sig"
        )
        uninstall = (INSTALLER_ROOT / "setup" / "uninstall.nsh").read_text(
            encoding="utf-8-sig"
        )
        required_install = (
            'WriteRegStr SHCTX "Software\\Classes\\${APP_REGNAME_DOC}\\DefaultIcon"',
            'WriteRegStr SHCTX "Software\\Classes\\${APP_REGNAME_DOC}\\Shell\\open\\command"',
            'WriteRegStr SHCTX "Software\\Classes\\${APP_EXT}" "" "${APP_REGNAME_DOC}"',
        )

        for association in required_install:
            with self.subTest(association=association):
                self.assertIn(association, configure)

        required_uninstall = (
            'ReadRegStr $R0 SHCTX "Software\\Classes\\${APP_EXT}" ""',
            '$R0 == "${APP_REGNAME_DOC}"',
            'DeleteRegKey SHCTX "Software\\Classes\\${APP_EXT}"',
        )

        for association in required_uninstall:
            with self.subTest(association=association):
                self.assertIn(association, uninstall)


if __name__ == "__main__":
    unittest.main()
