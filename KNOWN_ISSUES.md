# Known Issues

## Current integration and release blockers (2026-08-31)

| Area | Exact current state | Exit condition |
|---|---|---|
| Remote baseline | Published diagnostic head `bf4f3e2` is running; the last terminal head `3f961895` has Linux green, Windows full-GUI OpenGL failures, and both macOS architectures failing only during post-`OK` teardown. Local candidate `860670be43` plus this update contains reviewed root-cause fixes and complete local Linux build-tree evidence, not native or package proof. | Publish/re-fetch the final connector head/tree and retrieve every fresh matrix conclusion, log, and artifact. |
| Windows | The locked Qt package ships Mesa while the GPU-less runner exposed system OpenGL 1.1. Candidate `9cffb16ddc` stages one app-local locked renderer, forces Qt desktop resolution to it, verifies Pixi/Conda ownership and loaded module/hash/context, and validates logs before failure propagation. | Real Windows completes the unchanged 1,776-test GUI gate with the positive renderer probe and no context/access-violation signatures. |
| macOS | Both architectures previously selected exit 0 after all GUI tests, then re-entered `MainWindow` through `QMdiArea::subWindowActivated` after derived state destruction. Candidate `cd0ac8d110` disconnects that exact signal first and adds six live MDI children to lifecycle coverage. | Both native architectures exit 0 with MainWindow/application/process teardown markers. |
| Dependency Review | The last CodeQL jobs were green, but Dependency Review remains fail-closed because the repository Dependency Graph is disabled. CodeQL is not a substitute. | Enable the authorized repository setting and obtain a passing Dependency Review run; retain complementary locked-dependency and SBOM auditing. |
| Security | Audit evidence found a symlink graph escape in PR #27, and the stale DTD-only hardening stack is insufficient for the complete untrusted FCStd/XML/archive threat model. Release-blocker issue #24 remains open. | Close the complete extraction, entity, path, temporary-file, and parser acceptance criteria with regression evidence. |
| Legal and assets | The integration candidate removes all 32 restricted pattern assets and `FCStdThumbnail.dll` from tracked source and recognized manifests, with material and thumbnail quarantine guards green. Final source-archive, staging-tree, LFS-object-store, and package-payload inspection remains pending. | Inspect every produced source and package payload, replace user-facing capability only with cleared assets and reviewed source, and complete shipped notices. |
| Product | Native `Std_CommandPalette` now provides real Ctrl+K command search with fuzzy/token ranking, recency, disabled-state enforcement, focus/keyboard/accessibility behavior, and single activation. Workspace selector/context strip, Project presentation, and functional timeline remain absent. | Implement remaining real, tested workflows in roadmap order; inherited capability and visible controls do not close them. |
| Packaging and release | Deterministic Linux packaging policy is integrated and 53/53 focused tests pass, but production output is fail-closed until authenticated executable identity exists. Required clean-installed packages, final checksums/SBOMs, signing/notarization, tag, and verified Release are absent. | Establish identity and pass every final package/install/release gate; unavailable credentials remain explicit blockers. |

Linux is green at terminal head `3f961895`; the combined candidate is green
locally on Linux arm64 through 1,430 CTests, 1,674 CLI, and 1,776 GUI tests, but local evidence is not a native
platform pass or a production-readiness claim. If one platform remains externally blocked,
work may continue elsewhere, but M0 cannot advance on failed or inferred
evidence.

Internal GUI unittest diagnostics retain full tracebacks in stderr or the
application error log. These logs may disclose filesystem paths, exception text,
and test-provided values; they must be handled as potentially sensitive. The
wrapper rethrows the original failure and does not mask a nonzero result.
Retained exit-state detail is Internal/lifecycle-only, emitted on the GUI thread,
and uses bounded quoted escaping. Ordinary GUI runs emit no markers, but sanitized
internal test names and paths can still appear in retained Internal logs.

**Status:** Foundation/pre-alpha

**Release blocker count:** Not yet baselined

**Production use:** Not supported

This list distinguishes known project gaps from verified product defects. An
inherited FreeCAD capability is not considered verified OpenFusion support
until its build and workflow evidence is recorded.

## Foundation blockers

- The last terminal matrix is mixed. Linux passes every baseline gate. Reviewed
  Windows renderer and macOS teardown fixes require the final native rerun.
- Repository submodules must be initialized recursively before a complete
  build; no submodule-free source package has been validated.
- Current binaries and many user-facing identifiers still use FreeCAD names.
  They are transitional development outputs, not OpenFusion release artifacts.
- No OpenFusion-branded AppImage, `tar.zst`, DEB, RPM, Windows installer, or
  macOS DMG has been produced and clean-install tested.
- Cross-platform Windows/macOS and installed-package support remain unverified.
  The Linux source baseline is verified, but no Linux package has passed clean
  installation. Signing/notarization credentials and hardware-specific viewport
  coverage are not established.
- The dependency, bundled-asset, and third-party-license inventory is
  incomplete. No OpenFusion binary may be released until redistribution terms,
  notices, and shipped license texts are audited.
- Thirty-two inherited material-pattern files stating `All rights reserved`
  have been removed from source and CMake install manifests. A guard rejects
  reintroduction, but final package inspection and an original, cleared
  replacement preset library remain release work.
- The inherited GUI asset set has 123 SVGs and all 58 PNGs without meaningful
  embedded license markers, and upstream identity art remains wired into the
  GUI and every platform package path. Exact provenance plus original,
  cleared replacement branding is a release blocker.
- The inherited prebuilt Windows thumbnail shell extension and its installer
  registration have been removed. Explorer thumbnail support remains absent
  until it can be rebuilt from reviewed source with independent identity,
  coexistence, parser, signing, and uninstall validation; final installer
  inspection is still required. Historical installs may retain the global
  extension, and cleanup must verify ownership before touching it.
- GitHub Dependency Review is intentionally fail-closed but cannot run until a
  repository owner enables **Settings → Security → Code security and analysis
  → Dependency graph**. The independent Pixi lock integrity audit and its
  source-lock SPDX inventory add evidence but do not replace this
  dependency-change gate or the final-package SBOM requirement.
- The source-lock SPDX JSON is deterministic and syntax-checked, but CI does
  not yet run a hash-pinned SPDX semantic/schema validator. Its metadata audit
  records the lock's asserted digests without downloading or hashing archive
  bytes. Both semantic validation and final-package byte verification remain
  release work rather than inferred evidence.
- The untrusted-input, plugin/Python, external-process, archive, temporary-file,
  and CI supply-chain security reviews are incomplete.

## Product gaps

- The integrated OpenFusion application frame, workspace selector, contextual
  command surface, and global command launcher are not implemented.
- The existing FreeCAD project tree is inherited, but the OpenFusion project
  hierarchy and inspector presentation have not been implemented or accepted.
- No functional OpenFusion feature timeline exists. Timeline work must operate
  on the actual document and Part Design dependency/order model, not a visual
  imitation or the undo stack.
- Sketcher, Part Design, Assembly, TechDraw, CAM, FEM, Surface, Mesh, Materials,
  rendering, and import/export capabilities are inherited but have not yet
  passed the OpenFusion workflow and interoperability matrices.
- No first-party Sheet Metal environment has been selected. Any external
  workbench requires license, maintenance, dependency, compatibility, and
  packaging review before integration.
- OpenFusion Dark/Light themes, original icon family, navigation profile,
  viewport quality work, accessibility review, and HiDPI matrix are not
  complete.
- The core acceptance model, representative large-project fixtures, visual
  regression set, and repeatable performance benchmarks are not complete.

## Data and compatibility risk

- There is no verified OpenFusion migration guarantee beyond the inherited
  FreeCAD baseline. OpenFusion-specific persistence changes have not been
  introduced or validated.
- Autosave, crash recovery, backup behavior, Unicode/long/network paths, large
  documents, and older FreeCAD document round trips have not completed the
  OpenFusion release matrix.
- Use copies of important FCStd and imported files, keep independent backups,
  and avoid production work with this pre-alpha tree.

## Reporting and updates

Report reproducible non-security bugs in the repository issue tracker with the
exact revision, platform, build configuration, steps, logs, and a minimal test
file when safe. Report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md).

Issues leave this file only when the corresponding code, tests, and recorded
acceptance evidence exist. The detailed area-by-area status is maintained in
[docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md).
