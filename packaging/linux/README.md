# Deterministic Linux tar staging

This directory contains the first gated staging path for a relocatable Linux
`tar.zst`. It is not a published OpenFusion package and does not bypass the
project's identity, asset-provenance, licensing, acceptance, or clean-machine
release gates.

The tool consumes an installation that has already been produced beneath an
absolute `DESTDIR` and exact absolute install prefix. It never runs an install,
renames inherited binaries, or downloads dependencies. It does not
intentionally modify staged payload contents, modes, ownership, or non-access
timestamps; reads may update access times as documented below.

## Signed executable identity

The executable identity is a canonical JSON document signed with Ed25519. Its
signed payload binds all of the following before any archive is created:

- product `OpenFusion`, Linux, architecture, install prefix, and exact SemVer;
- development or production release channel;
- the full lowercase 40-character source revision;
- the SHA-256 of the locked `pixi.lock` dependency graph;
- canonical build provenance, including builder, generator, compiler, build
  type, descriptor-hashed CMake cache, locked OpenSSL binary/version, version,
  revision, lock digest, and `SOURCE_DATE_EPOCH`;
- canonical GUI `bin/OpenFusion` and CLI `bin/OpenFusionCmd`, including
  each executable's exact size and SHA-256.
- a domain-separated SHA-256 commitment over the packaging policy and every
  normalized staged path, type, mode, file size/digest, or symlink target.

Legacy `bin/FreeCAD` and `bin/FreeCADCmd` names are relative compatibility
symlinks only. They are not canonical identity paths. A filename, executable
bit, or matching ELF machine alone is never identity.

The trusted Ed25519 public key is an out-of-band input to both build and verify.
The packager checks the signature and fingerprint, then independently hashes
the descriptor-anchored staged executables. It never launches a staged binary.
It injects the exact signed document at
`share/openfusion/executable-identity.json` inside the private snapshot and
requires the manifest and extracted copy to match it byte for byte. There is no
test or command-line bypass.

Development builds may use an ephemeral signing key only when the signed
`release_channel` is `development` and the SemVer prerelease contains the
identifier `dev`; they must be labeled untrusted development artifacts.
Production release jobs require a protected signing key and a reviewed
public-key trust anchor. Production verification is fail-closed against the
repository's SPKI fingerprint allow-list, which is intentionally empty until
key custody is established. The repository does not contain a production
private key.

## Build and verify interface

An installation rooted at `/tmp/openfusion-stage/opt/openfusion` uses this
interface. First create canonical build provenance and an Ed25519 identity.
The example key is development-only:

```bash
mkdir -p /tmp/openfusion-output
export SOURCE_DATE_EPOCH=1787961600
openssl genpkey -algorithm ED25519 -out /tmp/openfusion-development-key.pem
openssl pkey -in /tmp/openfusion-development-key.pem -pubout \
  -out /tmp/openfusion-development-public.pem

# build-provenance.json is canonical compact JSON containing every required
# format-version-1 field and values from the exact build.
python3 packaging/linux/create_deterministic_tarball.py create-identity \
  --destdir /tmp/openfusion-stage \
  --prefix /opt/openfusion \
  --version 0.1.0-dev.1 \
  --architecture x86_64 \
  --release-channel development \
  --dependency-lock "$(pwd)/pixi.lock" \
  --build-provenance /tmp/build-provenance.json \
  --cmake-cache /absolute/build/CMakeCache.txt \
  --signing-key /tmp/openfusion-development-key.pem \
  --output /tmp/openfusion-executable-identity.json

python3 packaging/linux/create_deterministic_tarball.py build \
  --destdir /tmp/openfusion-stage \
  --prefix /opt/openfusion \
  --version 0.1.0-dev.1 \
  --architecture x86_64 \
  --output-dir /tmp/openfusion-output \
  --identity /tmp/openfusion-executable-identity.json \
  --trusted-public-key /tmp/openfusion-development-public.pem \
  --expected-key-sha256 "${DEVELOPMENT_PUBLIC_KEY_SPKI_SHA256}" \
  --expected-release-channel development \
  --expected-source-revision "${SOURCE_REVISION}" \
  --expected-lock-sha256 "${PIXI_LOCK_SHA256}" \
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

The target architecture is explicit. Every staged ELF must have the expected
class, byte order, and `e_machine`, but architecture coherence is not product
identity. The production CLI has no identity bypass. A successful development
run for the example version creates and internally verifies exactly these files:

## Locked runtime closure

Before creating build provenance or signing executable identity, close the
quiescent installed prefix from the exact Pixi environment used for the build:

```bash
python3 packaging/linux/runtime_closure.py bundle \
  --stage-prefix /tmp/openfusion-stage/opt/openfusion \
  --pixi-prefix "$(realpath .pixi/envs/default)" \
  --dependency-lock "$(realpath pixi.lock)" \
  --architecture x86_64 \
  --source-date-epoch "${SOURCE_DATE_EPOCH}"

python3 packaging/linux/runtime_closure.py verify \
  --stage-prefix /tmp/openfusion-stage/opt/openfusion \
  --architecture x86_64
```

The bundler never launches staged or Pixi binaries. It parses bounded ELF64
program and dynamic tables directly, selects the locked Python and Qt runtimes,
recursively closes their package dependencies and the non-system `DT_NEEDED`
graph, and copies every file owned by every selected package. Every copied file is attributed to its
exact `conda-meta` package URL, package SHA-256, build, version, and declared
license in `share/openfusion/runtime-closure.json`; the full payload signature
and archive manifest independently authenticate the resulting bytes.

The Linux GUI install uses a minimal ELF launcher in `bin/OpenFusion`. It
derives the package root from `/proc/self/exe`, replaces Qt, fontconfig,
Python, OpenSSL certificate, and XDG data search paths with package-internal
locations, then uses `execv` to enter `libexec/OpenFusion.real`. This is
required because the conda-forge Qt build does not honor an adjacent
`qt.conf` early enough for platform-plugin discovery. The launcher does not
fork, use a shell, or preserve host plugin search paths.

Only the architecture-specific dynamic loader and these glibc ABI names may be
resolved from the host: `libc`, `libm`, `libdl`, `libpthread`, `librt`,
`libutil`, `libresolv`, `libanl`, and `libBrokenLocale`. In particular,
`libstdc++`, `libgcc_s`, X11/GL, Qt, Python, OpenCascade, and compiler runtimes
must be bundled. Every dynamic ELF must use `DT_RUNPATH` components rooted at
`$ORIGIN`; absolute paths, empty components, escapes, legacy `DT_RPATH`,
colliding SONAMEs, system-ABI shadow files, noncanonical dynamic interpreters,
and unresolved dependencies fail both archive construction and fresh extraction
verification. Managed Python and Qt trees are exhaustive: any additional file,
directory, or symlink not committed by the closure manifest is rejected. The
closure lock digest must equal the lock digest in signed executable identity.
Locked ELF files whose package-relative path is stored as `DT_RPATH` are
normalized deterministically to `DT_RUNPATH`: the tool rewrites the dynamic tag
and replaces the existing string with an equal-length central-lib `$ORIGIN`
path, recording both source and transformed SHA-256 identities. It never grows
or relocates ELF structures and does not invoke `patchelf`.

The locked OpenVINO 2025.0.0 split packages omit their license field. Their
exact aarch64 package URLs and SHA-256 identities are bound by
`runtime_license_provenance.json` to the Apache-2.0 license and three upstream
third-party program inventories vendored under `licenses/openvino-2025.0.0`.
The evidence files are hash-validated and shipped whenever those packages are
selected. Case-distinct files owned by one exact locked package are retained;
therefore the Linux archive requires a case-sensitive extraction filesystem.

This proves dependency closure against the locked environment. It does not by
itself prove a glibc baseline or distribution compatibility. Release claims
still require native clean-container or clean-machine CLI and GUI lifecycle
acceptance on each architecture.

The policy recognizes `x86_64` and `aarch64` ELF identities. Producing an
architecture-labeled development archive is not a support claim; native
installed-package acceptance remains mandatory for each release architecture.

- `openfusion-0.1.0-dev.1-linux-x86_64.tar.zst`
- `openfusion-0.1.0-dev.1-linux-x86_64.tar.zst.manifest.json`
- `openfusion-0.1.0-dev.1-linux-x86_64.tar.zst.sha256`

The archive has one top-level directory named
`openfusion-0.1.0-dev.1-linux-x86_64`. Its contents are the contents of the staged
install prefix; the `/opt/openfusion` path itself is not embedded.

Verify an existing staged result with:

```bash
python3 packaging/linux/create_deterministic_tarball.py verify \
  --archive /tmp/openfusion-output/openfusion-0.1.0-dev.1-linux-x86_64.tar.zst \
  --manifest /tmp/openfusion-output/openfusion-0.1.0-dev.1-linux-x86_64.tar.zst.manifest.json \
  --checksum /tmp/openfusion-output/openfusion-0.1.0-dev.1-linux-x86_64.tar.zst.sha256 \
  --trusted-public-key /tmp/openfusion-development-public.pem \
  --expected-key-sha256 "${DEVELOPMENT_PUBLIC_KEY_SPKI_SHA256}" \
  --expected-release-channel development \
  --expected-version 0.1.0-dev.1 \
  --expected-architecture x86_64 \
  --expected-prefix /opt/openfusion \
  --expected-source-revision "${SOURCE_REVISION}" \
  --expected-lock-sha256 "${PIXI_LOCK_SHA256}"
```

## Safety and reproducibility contract

Build traversal is anchored to held directory descriptors and uses
`openat`-style operations with `O_NOFOLLOW`. Accepted content is copied into a
private `0700` workspace and made read-only. Before publication, the source is
scanned again and the tool compares entry membership, object identity,
regular-file contents, symlink targets, and the non-access-time metadata
recorded by its policy. A source access-time-only change is outside this
comparison and is not guaranteed to fail the build; reads may update access
times, and the tool deliberately does not rely on the privileged and
filesystem-dependent `O_NOATIME` flag. This comparison cannot provide an
atomic filesystem snapshot against a malicious concurrent writer, which is
why a stopped installer is an explicit precondition.

Before writing an archive, the tool also rejects empty trees, devices, FIFOs,
sockets, absolute symlinks, output paths inside the prefix, and existing
outputs. Symlinks are resolved against the complete payload graph rather than
checked one at a time: composed escapes, cycles, dangling targets, traversal
through non-directories, and chains longer than 40 hops are rejected by both
the builder and verifier. A policy-versioned global budget of 2,000,000
resolution steps bounds aggregate work across shared chains. It rejects sparse
files and sparse tar members. Regular files and symlinks must have link count
one. Setuid, setgid, and sticky bits are rejected. All extended attributes are
rejected because this format does not preserve them; that fail-closed rule
includes POSIX ACL and Linux file-capability attributes.

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

Policy version 3 has these absolute ceilings:

| Resource | Limit |
| --- | ---: |
| Compressed archive | 16 GiB |
| Manifest | 256 MiB |
| Signed executable identity | 1 MiB |
| Checksum file | 4 KiB |
| Payload entries | 500,000 |
| UTF-8 path or symlink target | 4,095 bytes |
| Symlink resolution | 40 hops |
| Aggregate symlink resolution | 2,000,000 steps |
| One PAX extended header | 64 KiB |
| One regular file | 8 GiB minus 1 byte |
| Total regular-file content | 32 GiB |
| Decompressed tar | 40 GiB |
| zstd working memory | 512 MiB |
| `SOURCE_DATE_EPOCH` | 8,589,934,591 |

The build is reproducible for identical payload bytes, paths,
`SOURCE_DATE_EPOCH`, script version, Python version, and zstd implementation.
The zstd command is invoked directly, never through a shell, single-threaded
at level 19, with sparse output disabled and a 512 MiB memory limit. The
release pipeline must pin and record the packaging toolchain before treating
byte-for-byte output across different builders as a gate.

Runtime closure is a necessary packaging gate, not proof of package usability.
Installed-package acceptance remains mandatory.

Verification deliberately favors assurance over speed. Standalone
verification needs temporary disk space of roughly three times the
uncompressed payload. Build-and-verify also retains the private snapshot and
initial tar, so it needs roughly five times the uncompressed payload in
addition to the staged input.

Run the focused tests with:

```bash
python3 -m unittest -v tests.openfusion.test_linux_tarball
python3 -m unittest -v tests.openfusion.test_linux_runtime_closure
```

The complete suite requires `zstd` and OpenSSL with Ed25519 support. Their
absence is a hard failure, not a skip, because otherwise a release gate could
appear green without exercising archive construction, signature
authentication, and verification.
