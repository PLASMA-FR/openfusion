<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
<!-- SPDX-FileCopyrightText: 2026 OpenFusion contributors -->

# OpenFusion release pipeline specification

## Status and scope

This is the target release architecture. It does not claim that the described
workflows, packages, signatures, attestations, or release gates currently
exist. The repository is not release-ready until the implementation can
produce and verify every required artifact in [`PACKAGING.md`](../../PACKAGING.md).

The design is derived from a source inspection of FreeCAD 1.1.3 and current
GitHub-hosted runner capabilities. FreeCAD's public release demonstrates that
Pixi/rattler builds for AppImage, NSIS, and architecture-specific DMGs are
feasible on hosted runners. OpenFusion adds final-package testing, Linux
tar.zst/DEB/RPM outputs, consolidated checksums, SBOMs, provenance, narrower
permissions, and an atomic publication gate.

## Release invariants

A release pipeline must satisfy all of these invariants:

- A protected `vMAJOR.MINOR.PATCH` tag identifies one immutable source commit.
- The tag version, CMake/project version, package versions, application version,
  and artifact names agree.
- Every binary comes from that source commit and the committed dependency lock.
- Build jobs cannot publish releases.
- Untrusted pull-request code cannot access signing or publishing credentials.
- Signing jobs consume build outputs only for protected release refs.
- Tests exercise final packages, not only build or staging directories.
- A platform failure prevents publication of the entire release.
- `SHA256SUMS`, SBOMs, and provenance refer to the final signed or notarized
  bytes.
- A release is created as a draft and is not made public until all gates pass.
- No release job silently converts a required signed artifact into an unsigned
  one.

## Target workflow topology

The file names below describe the intended separation of responsibility. They
are not evidence that those workflow files have been implemented.

| Workflow | Triggers | Responsibility | Default token access |
| --- | --- | --- | --- |
| `test.yml` | Pull requests, pushes to protected branches | Compile, unit/integration/GUI tests, install-tree tests, lint | `contents: read` |
| `linux.yml` | Reusable call, manual development run | Build one Linux runtime; package and test AppImage, tar.zst, DEB, RPM | `contents: read` |
| `windows.yml` | Reusable call, manual development run | Build, optionally sign, install-test, and uninstall-test Windows package | `contents: read` |
| `macos.yml` | Reusable call, manual development run | Build, optionally sign/notarize, mount-test Intel and Apple Silicon DMGs | `contents: read` |
| `release.yml` | Protected SemVer tag, manual recovery dispatch | Coordinate platform workflows, attest, create draft, upload, publish | Per-job grants |
| `codeql.yml` | Protected branches and schedule | C/C++ and Python code scanning | Read plus `security-events: write` only where needed |
| `dependency-review.yml` | Pull requests | Reject newly introduced vulnerable dependencies | `contents: read` |

The release dependency order is:

| Stage | Inputs | Outputs | Publication authority |
| --- | --- | --- | --- |
| 1. Validate | Protected tag and source checkout | Trusted version and source metadata | None |
| 2. Build | Source and frozen dependency locks | Unsigned platform staging trees | None |
| 3. Test staging | Staging trees and test models | Test reports and logs | None |
| 4. Package/sign | Tested staging trees | Final platform artifacts | Signing credentials only where required |
| 5. Test final artifacts | Final installers, archives, and DMGs | Installation and acceptance reports | None |
| 6. Audit | Final artifacts and manifests | SBOMs, license report, `SHA256SUMS`, attestations | Attestation authority only |
| 7. Publish | All successful results | Draft GitHub Release, then approved publication | `contents: write` |

Large binaries move between jobs as short-retention GitHub Actions artifacts.
They must not be committed to Git. Release assets must each remain below
GitHub's 2 GiB limit.

## Trigger and trust policy

Pull requests run without secrets using the `pull_request` event. The pipeline
must not use `pull_request_target` to build or execute pull-request content.
Fork pull requests receive a read-only token and cannot write trusted caches.

Production release jobs run only for protected tags that resolve to approved
commits on an allowed release branch. Repository rules should prevent tag
movement and restrict tag creation. Signing and publication jobs use protected
GitHub environments so that credentials are unavailable until the environment
policy is satisfied.

Manual dispatch is allowed for diagnostics and recovery, but it must require an
explicit source ref and must not weaken version, signing, testing, or
publication gates. A manual unsigned build is a development artifact, not a
production release.

## Source and dependency validation

Before compiling, the validation job must:

1. check out the exact tag with submodules recursively and with persisted Git
   credentials disabled;
2. verify the tag format and reject unsafe characters before values reach a
   shell;
3. compare the tag to every authoritative project/package version;
4. record the source commit and all submodule commits;
5. set `SOURCE_DATE_EPOCH` from the source commit;
6. require the committed Pixi lock file and run Pixi in frozen mode;
7. reject unexpected lock-file changes during the build;
8. verify every separately downloaded tool against a pinned version and
   repository-controlled checksum.

The release source archive must be generated from the same tag and must include
the submodule content required to rebuild the distributed binaries. Generated
source archives must not depend on an uncommitted mutation that cannot be
reproduced from documented steps.

## Build and test matrix

### Required continuous tests

Linux Release configuration is the minimum required pull-request gate. It must
run:

- configure and compile with warnings retained;
- FreeCAD-derived C++ test executables, including App, Base, GUI, Part,
  PartDesign, Sketcher, Assembly, CAM, Material, Measure, Mesh, Spreadsheet,
  and Qt tests where built;
- the Python and command-line suite through `OpenFusionCmd -t 0`;
- GUI-registered tests under Xvfb and software rendering;
- Coin/viewport snapshot tests in a pinned rendering environment;
- CMake installation into an isolated prefix;
- command-line and GUI tests again from the installed prefix;
- OpenFusion document save/reopen, serialization, undo/redo, STEP export, and
  STL export regressions.

Windows and macOS compile and command-line tests should run on protected branch
pushes and release candidates, and on pull requests when resources permit.
Windows C++ tests that are disabled upstream are an explicit gap to fix; they
must not be reported as passing. Likewise, an upstream-disabled Qt6 install-tree
GUI test is not evidence of GUI correctness.

Debug, sanitizer, static-analysis, and long-running large-model suites may run
on a schedule, but a known release-blocking failure in any of them must block a
release candidate.

### Required package matrix

| Artifact | Build runner | Final-artifact test environment |
| --- | --- | --- |
| AppImage | `ubuntu-22.04` | Hosted Linux runner with runtime execution and Xvfb |
| tar.zst | `ubuntu-22.04` | Fresh extraction, including a path with spaces |
| DEB | `ubuntu-22.04` | Clean supported Debian and Ubuntu containers |
| RPM | `ubuntu-22.04` | Clean supported Fedora and Rocky Linux containers |
| Windows EXE | `windows-2022` | Fresh hosted runner, silent install and uninstall |
| macOS arm64 DMG | `macos-latest` | Mount/copy/run on Apple Silicon runner |
| macOS x86-64 DMG | `macos-15-intel` | Mount/copy/run on Intel runner |

Container tests establish package-manager and headless-runtime behavior. They
do not establish GPU, desktop-shell, driver, or hardware-input compatibility.

## Final-package quality gates

Every format has to pass all applicable gates after the final archive,
installer, signature, or notarization ticket has been produced.

### Common gates

- artifact name, version, architecture, and file type match;
- artifact size is nonzero, plausible, and below 2 GiB;
- malware and secret scans report no release-blocking findings;
- expected license, notice, version, and build-manifest files are present;
- no private keys, tokens, temporary keychains, PDBs intended to remain
  private, build caches, or absolute build paths are present;
- packaged command-line launch succeeds in safe mode;
- required Python modules and Coin/Pivy import from the package rather than the
  build host;
- the full acceptance model in `PACKAGING.md` succeeds;
- saved documents reopen and representative STEP/STL exports are nonempty and
  parseable;
- package logs contain no unhandled exception, crash, or missing-runtime error.

### Linux-specific gates

- desktop file and AppStream metadata validate;
- MIME and icon installation locations are correct;
- recursive dynamic-library inspection reveals no unintended build-host paths;
- AppImage runtime execution and extract-and-run execution both work;
- DEB and RPM install, upgrade where applicable, and remove cleanly;
- package scripts are idempotent and do not access the network;
- package removal preserves user documents and preferences.

### Windows-specific gates

- the installer supports a non-administrative current-user install;
- Start menu, uninstall, publisher, version, icon, and optional association
  entries are correct;
- installed binaries run from the installed location;
- the uninstaller completes and removes application-owned files;
- for production tags, `signtool verify /pa` succeeds on critical EXE, DLL,
  PYD, and installer files;
- a configured signing failure cannot fall back to an unsigned release.

### macOS-specific gates

- the DMG mounts and detaches without filesystem errors;
- the copied app runs outside the build directory and mounted image;
- bundle identifier, version, architecture, document types, icons, and minimum
  deployment target are correct;
- for production tags, strict `codesign` verification, Gatekeeper `spctl`
  assessment, notarization status, and `stapler validate` all succeed;
- release entitlements contain no debug-only capabilities.

## Supply-chain controls

### Workflow dependencies

Every external `uses:` reference must be pinned to a full 40-character commit
SHA verified to belong to the intended upstream repository. Version comments
may accompany the SHA for maintenance. Repository policy should enforce SHA
pinning, and Dependabot should propose reviewed updates for GitHub Actions.

Prefer local audited scripts and GitHub-provided actions over additional
Marketplace actions. Use the GitHub CLI for release creation and upload rather
than adding a release action. Any required third-party tool, including Pixi,
appimagetool, an SBOM generator, or a package generator, must have both an
exact version and an integrity check.

Runner hardening should begin with outbound-network audit mode. After the
required endpoints are understood, release jobs should use an explicit egress
allowlist where practical. A runner-hardening action is itself a privileged
dependency and must also be SHA-pinned.

### Token permissions

The workflow-level default is:

```yaml
permissions:
  contents: read
```

Additional permissions are granted only to the job that needs them:

| Job | Additional permission | Reason |
| --- | --- | --- |
| Code scanning upload | `security-events: write` | Upload SARIF |
| Windows OIDC sign-in | `id-token: write` | Short-lived Azure identity |
| Artifact attestation | `id-token: write`, `attestations: write` | Sigstore-backed provenance/SBOM attestation |
| Release publisher | `contents: write` | Create draft and upload assets |

The publisher does not compile or execute untrusted source. Build jobs do not
receive `contents: write`. Apple credentials are exposed only to the protected
macOS signing job. Long-lived cloud client secrets should be replaced by OIDC
federation where the provider supports it.

### Cache isolation

Release builds must not restore caches written by fork pull requests. Cache
keys include platform, compiler/toolchain, configuration, and lock-file hash.
Untrusted jobs may restore a read-only trusted dependency cache but must not
overwrite it. Release builds should disable build-output caches when provenance
or reproducibility cannot be established.

### SBOM, notices, checksums, and provenance

Generate an SPDX JSON SBOM for each platform staging tree with a pinned tool
before Conda/Pixi metadata is pruned. Retain the exact package manifest and
collect bundled license texts. Automated license detection must be reviewed;
it is not a substitute for `THIRD_PARTY_NOTICES.md` or license obligations.

The final sequence is security-sensitive:

1. assemble package payload;
2. sign Windows binaries and installer or sign/notarize/staple macOS bundle;
3. run final-package acceptance;
4. hash final bytes;
5. generate one sorted `SHA256SUMS` covering release assets and SBOMs;
6. generate GitHub artifact provenance and associate the relevant SBOM;
7. verify attestations before upload;
8. upload to a draft release.

Changing, signing, or stapling an artifact after hashing invalidates the
checksum and attestation and requires them to be regenerated.

## Publication procedure

The coordinating release workflow should perform these steps:

1. Validate the protected tag and exact source commit.
2. Run the complete source test matrix.
3. Build all platform staging artifacts independently.
4. Sign and package through protected platform jobs.
5. Run final installation and acceptance tests for every artifact.
6. Download successful short-retention artifacts into an isolated aggregation
   job.
7. Reject missing, duplicate, misnamed, oversized, or unexpected files.
8. Validate versions, architectures, license payloads, and SBOMs.
9. Generate and verify `SHA256SUMS` and provenance attestations.
10. Create a draft GitHub Release for the existing tag.
11. Upload the complete source archive, packages, checksums, SBOMs, and release
    notes.
12. Retrieve or inspect the uploaded asset list and compare it to the expected
    manifest.
13. Publish only after the protected release-environment approval and final
    verification.

A failed upload leaves a draft, not a public partial release. Re-running a
release must compare existing asset digests and refuse an unexplained mismatch.
Replacing a published binary under the same version is prohibited; create a
new patch version instead.

## Reproducibility policy

The dependency graph, compiler/tool versions, Pixi version, Pixi lock, package
tools, and action commits must be pinned. Archive ordering, ownership, locale,
timezone, and timestamps should be normalized. Compiler flags should remove
workspace paths where the toolchain supports it.

Signed Windows artifacts and notarized/stapled macOS artifacts contain
timestamped external material and are not expected to be byte-for-byte
reproducible. Reproducibility should be measured on the unsigned staging output
before signing, while final signed bytes are protected by checksums and
provenance. No reproducibility claim may be made until independent rebuilds
have been compared.

## Credential blockers

### Windows

Production Authenticode signing needs one of:

- Azure Trusted Signing account, certificate profile, endpoint, tenant, and a
  federated workflow identity with the minimum signing role; or
- an appropriately protected code-signing certificate, its password, and a
  secure signing mechanism.

The pipeline can produce an unsigned development installer without these
credentials, but it cannot declare that installer a signed production release.

### macOS

Production signing and notarization need:

- active Apple Developer Program membership;
- a Developer ID Application identity and protected certificate material;
- team and signing identity values;
- notarization credentials, preferably an App Store Connect API key or an
  Apple ID app-specific password;
- provisioning profiles when included app extensions require them.

Without these, CI may create an ad-hoc development DMG only. It must not report
notarization success or publish the DMG as a production artifact.

### Optional package signatures

GPG signatures for AppImages, RPMs, repository metadata, or `SHA256SUMS`
require a separately protected signing key. SHA-256 files and GitHub artifact
attestations do not require that external key.

## Hosted-runner and hardware limits

The upstream FreeCAD 1.1.3 release demonstrates that its current build fits
the named GitHub-hosted runners, with Linux disk-space cleanup. OpenFusion may
grow beyond that baseline. Standard hosted jobs have finite disk and a six-hour
execution limit; the pipeline must measure build duration, peak disk, and peak
memory and move only the affected job to a larger or self-hosted runner when
necessary.

Standard hosted runners do not provide representative professional CAD GPU or
desktop hardware. They cannot complete the release evidence for:

- NVIDIA, AMD, and Intel driver-specific viewport rendering;
- real Wayland and X11 desktop integration across supported distributions;
- Windows and macOS GPU-backed GUI behavior;
- 100%, 125%, 150%, 175%, and 200% HiDPI visual inspection;
- multi-monitor behavior, SpaceMouse devices, and vendor input drivers;
- large-assembly viewport FPS and hardware-dependent rendering benchmarks;
- every older supported Windows or macOS release.

These checks require dedicated physical systems, self-hosted runners, or an
external VM/device service. Their absence must remain a documented release
limitation rather than being inferred from headless Xvfb success.

## Failure policy

Compilation, tests, packaging, signing, notarization, installation, acceptance,
license audit, SBOM generation, checksum generation, attestation, or asset
verification failures fail the release. Release-critical tests may not be
skipped, converted to warnings, or hidden behind `continue-on-error`.

When an external signing or notarization service is unavailable, the workflow
may retain unsigned development artifacts for diagnosis, but production
publication remains blocked. Known critical bugs, data-corruption risks,
broken undo/redo, package launch failures, and incomplete final-artifact tests
are release blockers.
