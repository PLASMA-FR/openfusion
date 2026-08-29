<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
<!-- SPDX-FileCopyrightText: 2026 OpenFusion contributors -->

# OpenFusion packaging

## Status

OpenFusion does not yet publish installable packages. This document defines the
packaging contract and the evidence required before any platform or artifact is
described as supported.

The required artifacts, workflows, signing configuration, and installation
tests below are targets. Their presence in this document is not evidence that
they have been implemented, built, signed, notarized, installed, or released.

## Verified upstream baseline

OpenFusion is currently based on the FreeCAD `1.1.3` tag at commit
`145529fe741292ff0b3977a01195bf0247425794`. The following upstream facts were
verified by inspecting that tag and its public GitHub release metadata:

- FreeCAD 1.1.3 was published on July 25, 2026.
- Its release workflow uses Pixi and rattler-build from
  `package/rattler-build/`.
- Its release matrix uses `ubuntu-22.04`, `ubuntu-22.04-arm`,
  `windows-2022`, `macos-15-intel`, and `macos-latest` GitHub-hosted runners.
- The public release contains Linux x86-64 and AArch64 AppImages, a Windows
  x86-64 portable archive and NSIS installer, macOS Intel and Apple Silicon
  DMGs, a source archive, and individual SHA-256 files.
- The old `FreeCAD/FreeCAD-Bundle` repository is archived; the maintained
  upstream release implementation is in the main FreeCAD repository.

This baseline proves that the corresponding upstream build approaches can run
on GitHub-hosted infrastructure. It does not prove OpenFusion branding,
OpenFusion package correctness, final-artifact installation, code-signing
status, notarization status, or the additional formats required here. The
upstream scripts primarily smoke-test their staging trees before creating the
final packages; OpenFusion must test the final packages themselves.

Relevant upstream references:

- [FreeCAD 1.1.3 release](https://github.com/FreeCAD/FreeCAD/releases/tag/1.1.3)
- [FreeCAD 1.1.3 release workflow](https://github.com/FreeCAD/FreeCAD/blob/1.1.3/.github/workflows/build_release.yml)
- [FreeCAD 1.1.3 rattler-build packaging](https://github.com/FreeCAD/FreeCAD/tree/1.1.3/package/rattler-build)
- [FreeCAD Windows installer](https://github.com/FreeCAD/FreeCAD/tree/1.1.3/package/WindowsInstaller)

## Required release set

`${VERSION}` is the SemVer version without the leading `v`. Release file names
must be generated centrally so that packages, checksums, documentation, and
GitHub Release assets cannot disagree.

| Platform | Required artifact | Initial architecture | Current status |
| --- | --- | --- | --- |
| Linux | `OpenFusion-${VERSION}-x86_64.AppImage` | x86-64 | Planned; not built |
| Linux | `openfusion-${VERSION}-linux-x86_64.tar.zst` | x86-64 | Planned; not built |
| Debian-family Linux | `openfusion_${VERSION}_amd64.deb` | x86-64 | Planned; not built |
| RPM-family Linux | `openfusion-${VERSION}.x86_64.rpm` | x86-64 | Planned; not built |
| Windows | `OpenFusion-${VERSION}-Windows-x86_64.exe` | x86-64 | Planned; not built |
| macOS | `OpenFusion-${VERSION}-macOS-arm64.dmg` | Apple Silicon | Planned; not built |
| macOS | `OpenFusion-${VERSION}-macOS-x86_64.dmg` | Intel | Planned; not built |
| All | `SHA256SUMS` | N/A | Planned; not generated |
| Source | `openfusion-${VERSION}-source.tar.zst` | N/A | Planned; not generated |
| All | SPDX JSON SBOMs | Per platform | Planned; not generated |

The requested `den` format is interpreted as `deb`. Architecture-specific
macOS DMGs are the initial policy. A universal DMG must not be advertised until
Qt, Python, OpenCASCADE, every native Python extension, and every bundled
library have been built and tested as universal binaries.

Additional architectures may be introduced only after their complete package
and acceptance matrices pass. An artifact name must never imply support for an
architecture that was not built natively or by a validated cross-build.

## Canonical packaging model

All Linux formats should be produced from one audited, relocatable runtime
staging tree. Rebuilding OpenFusion independently for AppImage, tar.zst, DEB,
and RPM would increase drift and make failures harder to compare.

The staging tree must contain:

- the OpenFusion GUI and command-line binaries;
- the runtime libraries and Python environment required by enabled modules;
- original OpenFusion desktop, AppStream, MIME, icon, and launcher metadata;
- license texts, copyright notices, and third-party notices;
- a machine-readable build manifest;
- the release version and source commit;
- no compiler outputs, headers, caches, credentials, or developer-only tools
  unless a runtime feature demonstrably requires them.

All user-visible and platform identifiers must be migrated deliberately. This
includes executable names, desktop IDs, AppStream IDs, MIME registrations,
icons, file associations, macOS bundle identifiers, Windows registry keys,
Start menu entries, publisher fields, uninstaller entries, update metadata,
and crash-log locations. Renaming only the archive is not valid OpenFusion
packaging.

### Linux AppImage

The AppImage should adapt FreeCAD's proven AppDir approach while using original
OpenFusion metadata and assets. `appimagetool` must be pinned to an immutable
release or commit and its downloaded binary must be verified against a
repository-controlled SHA-256 value. A moving `continuous` download without
verification is not acceptable for a release build.

Before release, the final AppImage must:

- pass desktop and AppStream validation;
- execute its packaged command-line binary;
- execute under Xvfb with software rendering;
- run the packaged acceptance model;
- work through the AppImage runtime on the hosted runner, using
  `--appimage-extract-and-run` only as an additional no-FUSE test;
- remain below GitHub's 2 GiB per-release-asset limit.

### Linux tar.zst

The tarball should contain the same relocatable runtime and a top-level
OpenFusion launcher. It must be deterministic where practical: sorted entries,
numeric ownership, a fixed modification time derived from
`SOURCE_DATE_EPOCH`, and fixed zstd options.

The final archive must be extracted into at least a normal temporary path and
a path containing spaces. Tests must run the extracted copy without relying on
the build directory or a system-wide installation.

### DEB and RPM

The initial GitHub Release packages should wrap the audited runtime under
`/opt/openfusion`, install a small launcher under `/usr/bin`, and place desktop,
AppStream, MIME, and icon metadata in the platform-standard shared locations.
They are standalone bundled packages, not claims of acceptance into Debian,
Ubuntu, Fedora, or another distribution.

The package definitions must declare only dependencies proven necessary by
recursive binary inspection and clean-container tests. Maintainer scripts must
be idempotent, must not execute network downloads, and must correctly refresh
desktop, MIME, and icon caches where the target distribution requires it.

FreeCAD's in-tree Fedora spec is useful historical input but is not the
upstream release path and must not be copied unchanged. Debian's maintained
FreeCAD packaging is external to the FreeCAD source repository and is useful
as a policy and metadata reference. OpenFusion's bundled release packages have
a different portability goal.

The final DEB must be installed, exercised, and removed in clean Debian and
Ubuntu containers. The final RPM must be installed, exercised, and removed in
clean Fedora and Rocky Linux containers. Package removal must not delete user
documents or preferences.

### Windows installer

The required Windows artifact is an NSIS-based 64-bit installer adapted from
the proven FreeCAD installer architecture. It must support a current-user
installation without administrative privileges, a Start menu entry, original
OpenFusion icons, a registered uninstaller, clean upgrades where supported,
and optional file associations that do not silently override user choice.

The final installer, not merely its staging directory, must be tested on a
fresh `windows-2022` runner by performing a silent current-user installation,
running command-line and acceptance checks from the installed location,
validating registered metadata, uninstalling silently, and checking that the
installed application files were removed. Interactive installer UX, UAC, and
GPU-backed GUI behavior require additional dedicated Windows test
infrastructure.

Tagged production installers and their executable, DLL, and PYD payloads must
be Authenticode-signed and timestamped. If signing is required for the release,
any signing or signature-verification failure is fatal. Unsigned development
artifacts must be labeled as such and must not be presented as production
releases.

### macOS DMGs

Apple Silicon and Intel application bundles should be built on their native
GitHub-hosted runner architectures. Each final DMG must be mounted, its `.app`
copied to a clean destination, exercised from that destination, detached, and
verified independently.

Tagged production bundles require a Developer ID Application signature,
hardened runtime, successful Apple notarization, a stapled ticket, and passing
`codesign`, `spctl`, and `stapler` verification. Release entitlements must not
contain debugging permissions such as `com.apple.security.get-task-allow`.
Broad permissions such as disabled library validation require a documented
runtime need and security review.

An ad-hoc-signed or unsigned DMG is useful for development CI but is not a
notarized production artifact.

## Package acceptance gate

Every final package must run the same release acceptance model from its
installed or extracted location:

1. Start OpenFusion and create a new document.
2. Create and activate a component and body.
3. Create a rectangle sketch on the XY plane.
4. Add dimensions and fully constrain the sketch.
5. Extrude it, then add a hole, fillet, and pattern.
6. Add another component and an assembly relationship.
7. Save, close, and reopen the document.
8. Edit an early parametric feature and recompute dependent features.
9. Exercise undo and redo around core modeling changes.
10. Create a drawing and export representative STEP and STL files.
11. Validate the saved document and exported outputs.
12. uninstall or remove the package where applicable.

The command-line smoke test, internal unit tests, and a successful compiler
exit are necessary but do not replace this gate. A test must fail the job when
the operation fails; recording a failure marker while returning success is not
acceptable.

Detailed release orchestration and security boundaries are defined in
[`docs/ci/RELEASE_PIPELINE.md`](docs/ci/RELEASE_PIPELINE.md).

## Licensing and package contents

Each package must preserve FreeCAD and third-party license obligations and
include the OpenFusion `COPYING`, `NOTICE.md`, and reviewed third-party notices
appropriate to the bundled contents. The source archive must include the exact
source and submodule revisions used for the binary release.

Each platform staging tree must be scanned with a pinned SBOM tool before
package-manager metadata is removed. At least one SPDX JSON SBOM per platform
must be attached to the release. Automated SBOM generation does not replace
human review or the inclusion of required license texts and notices.

The final order is:

1. build and test the runtime;
2. assemble and audit the package;
3. sign and notarize where applicable;
4. test the final signed package;
5. generate checksums and attestations over the final bytes;
6. publish only after every release gate succeeds.

## External blockers

The following are not available merely because the source repository exists:

- Windows production signing requires Azure Trusted Signing configuration or
  another valid Authenticode certificate and secure signing process.
- macOS production signing and notarization require an Apple Developer account,
  Developer ID credentials, notarization credentials, and any provisioning
  profiles needed by bundled app extensions.
- Optional GPG signing for RPMs, AppImages, repository metadata, or
  `SHA256SUMS` requires a protected private signing key.
- Representative GPU, Wayland/X11, HiDPI, multi-monitor, SpaceMouse, and
  driver-specific validation requires dedicated physical or self-hosted
  systems; standard hosted runners do not prove these behaviors.
- Compatibility with older supported macOS and Windows versions requires
  runners or virtual machines for those exact systems.

Until the workflows, credentials, final-package tests, and release artifacts
exist and pass, OpenFusion must report packaging as incomplete.
