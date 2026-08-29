# Deterministic Linux tar staging

This directory contains the first gated staging path for a relocatable Linux
`tar.zst`. It is not a published OpenFusion package and does not bypass the
project's identity, asset-provenance, licensing, acceptance, or clean-machine
release gates.

The tool consumes an installation that has already been produced beneath an
absolute `DESTDIR` and exact absolute install prefix. It never runs an install,
renames inherited binaries, downloads dependencies, or edits the staged tree.

## Build and verify a staged archive

For an installation rooted at `/tmp/openfusion-stage/opt/openfusion`, run:

```bash
mkdir -p /tmp/openfusion-output
export SOURCE_DATE_EPOCH=1787961600
python3 packaging/linux/create_deterministic_tarball.py build \
  --destdir /tmp/openfusion-stage \
  --prefix /opt/openfusion \
  --version 0.1.0 \
  --architecture x86_64 \
  --output-dir /tmp/openfusion-output \
  --staging-is-quiescent \
  --output-is-exclusive
```

The output directory must already exist. Inputs and outputs must be canonical
absolute paths; symlinked path components are rejected. The quiescent flag is
an explicit assertion that every installer and process capable of changing
the staged tree has stopped. Mutation detection is defense in depth, not a
substitute for that operational requirement.

The output exclusivity flag is an explicit assertion that the directory is
controlled by this packaging operation; no other process may rename or remove
its entries during publication or rollback. That precondition closes the
otherwise unavoidable POSIX name-based unlink race during rollback. Concurrent
compliant invocations must use separate output directories. The tool also
holds a nonblocking advisory lock on the directory descriptor, but the lock is
not a substitute for the exclusivity assertion because unrelated writers may
ignore it. Existing entries are never overwritten.

The target architecture is explicit and trusted only after all staged ELF
files have the expected class, byte order, and `e_machine`, with at least one
executable ELF beneath `bin/`. That representative must have an in-file,
bounded program-header table and a structurally valid executable `PT_LOAD`
segment; a header-only ELF lookalike is rejected. The production CLI has no
architecture-check bypass, and its verifier rejects artifacts marked with the unit-test bypass.
Synthetic tests can opt in only through an explicit private Python API keyword
and a SemVer prerelease identifier named `test`. A successful run creates and
internally verifies exactly these files:

- `openfusion-0.1.0-linux-x86_64.tar.zst`
- `openfusion-0.1.0-linux-x86_64.tar.zst.manifest.json`
- `openfusion-0.1.0-linux-x86_64.tar.zst.sha256`

The archive has one top-level directory named
`openfusion-0.1.0-linux-x86_64`. Its contents are the contents of the staged
install prefix; the `/opt/openfusion` path itself is not embedded.

Verify an existing staged result with:

```bash
python3 packaging/linux/create_deterministic_tarball.py verify \
  --archive /tmp/openfusion-output/openfusion-0.1.0-linux-x86_64.tar.zst \
  --manifest /tmp/openfusion-output/openfusion-0.1.0-linux-x86_64.tar.zst.manifest.json \
  --checksum /tmp/openfusion-output/openfusion-0.1.0-linux-x86_64.tar.zst.sha256
```

## Safety and reproducibility contract

Build traversal is anchored to held directory descriptors and uses
`openat`-style operations with `O_NOFOLLOW`. Accepted content is copied into a
private `0700` workspace and made read-only. The complete source tree is then
read and hashed a second time; membership, metadata, content, symlink, or root
changes fail the build. This check cannot provide an atomic filesystem
snapshot against a malicious concurrent writer, which is why a stopped
installer is an explicit precondition.

Before writing an archive, the tool also rejects empty trees, devices, FIFOs,
sockets, absolute symlinks, symlinks that lexically escape the packaged
prefix, output paths inside that prefix, and existing outputs. It rejects
sparse files and sparse tar members. Regular files and symlinks must have link
count one. Setuid, setgid, and sticky bits are rejected. All extended
attributes are rejected because this format does not preserve them; that
fail-closed rule includes POSIX ACL and Linux file-capability attributes.

Entries are ordered by UTF-8 path bytes. Archive ownership is normalized to
`root:root` with numeric UID/GID zero. Directories and executable files use
mode `0755`, other files use `0644`, and symlinks use `0777`. Every timestamp
comes from `SOURCE_DATE_EPOCH`. The manifest records each payload path, type,
normalized mode, file size and SHA-256, or symlink target.

Manifest and checksum links are installed first and the archive is linked
last as the commit marker. The companion links are directory-synced before the
archive marker is linked and synced. Any publication failure rolls back links
created by that invocation and never overwrites prior files. The checksum
covers both the archive and canonical manifest.

Verification requires exact companion basenames from one directory. It opens
each supplied file once without following symlinks, copies it within an
absolute size bound to a private directory, compares descriptor metadata
before and after the copy, and performs all subsequent work on those copies.
It bounded-decompresses the archive, streams tar members, validates every
header against the manifest, extracts through a path-safe implementation,
rescans the payload, revalidates ELF identity, and reconstructs the canonical
tar for an exact byte comparison.

Policy version 1 has these absolute ceilings:

| Resource | Limit |
| --- | ---: |
| Compressed archive | 16 GiB |
| Manifest | 256 MiB |
| Checksum file | 4 KiB |
| Payload entries | 500,000 |
| ELF program headers | 4,096 |
| UTF-8 path or symlink target | 4,095 bytes |
| One PAX extended header | 64 KiB |
| One regular file | 8 GiB |
| Total regular-file content | 32 GiB |
| Decompressed tar | 40 GiB |
| zstd working memory | 512 MiB |

The build is reproducible for identical payload bytes, paths,
`SOURCE_DATE_EPOCH`, script version, Python version, and zstd implementation.
The zstd command is invoked directly, never through a shell, single-threaded
at level 19, with sparse output disabled and a 512 MiB memory limit. The
release pipeline must pin and record the packaging toolchain before treating
byte-for-byte output across different builders as a gate.

This staging mechanism does not establish runtime dependency closure or
package usability. Those require the separately tracked installed-package
acceptance tests.

Verification deliberately favors assurance over speed. Standalone
verification needs temporary disk space of roughly three times the
uncompressed payload. Build-and-verify also retains the private snapshot and
initial tar, so it needs roughly five times the uncompressed payload in
addition to the staged input.

Run the focused tests with:

```bash
python3 -m unittest -v tests.openfusion.test_linux_tarball
```

`PurePolicyTests` and `SnapshotPolicyTests` do not require `zstd` and always
run. Only `ZstdIntegrationTests` is skipped when the system executable is not
available; the test-only architecture bypass remains inaccessible from the
packaging CLI.
