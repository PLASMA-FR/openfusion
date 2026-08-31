# Known Issues

## Current integration and release blockers (2026-08-31)

| Area | Exact current state | Exit condition |
|---|---|---|
| Remote baseline | At published head `3f54ec58`, Linux and Windows pass every gate. Both macOS architectures pass 1,776 GUI tests and fail only below the MainWindow destructor body. Local source `ee2bc68b` adds explicit owned-MDI destruction, package identity/legal work, and a hash-bound source-policy exemption; native rerun is pending. | Publish/re-fetch the new head and retrieve every fresh matrix conclusion, log and artifact. |
| Windows | Native Windows is green: app-local locked Mesa, exact loaded module/hash/context, 1,432 CTests, TechDraw, CLI 1,674 and GUI 1,776 all pass with clean graphics logs. | Preserve this result on subsequent heads and close the residual MSVC warning separately. |
| macOS | Signal disconnect alone was insufficient. Qt base teardown began after `MainWindow` freed private state. The local fix takes/deletes the owned QMdiArea while the derived object and `d` remain valid; a 64-maximized-subwindow process regression passes locally. | Both native architectures exit 0 with owned-UI, MainWindow, application and process teardown markers. |
| Dependency Review | All complementary Security jobs are green, but Dependency Review remains fail-closed because repository Dependency Graph is disabled; tracked as issue #32. | Enable the setting and obtain a passing Dependency Review run; CodeQL/lock audit are not substitutes. |
| Security | Audit evidence found a symlink graph escape in PR #27, and the stale DTD-only hardening stack is insufficient for the complete untrusted FCStd/XML/archive threat model. Release-blocker issue #24 remains open. | Close the complete extraction, entity, path, temporary-file, and parser acceptance criteria with regression evidence. |
| Legal and assets | The 32 restricted patterns and inherited thumbnail DLL are removed. Source/index guards and the verified development tar's streaming final-payload legal scan pass, including wide/chunk/path/LFS evasions and exact shipped notices. Source archives, external LFS storage and production payload review remain. | Inspect production source/package artifacts, provide cleared replacements and complete shipped notices. |
| Product | Native `Std_CommandPalette` now provides real Ctrl+K command search with fuzzy/token ranking, recency, disabled-state enforcement, focus/keyboard/accessibility behavior, and single activation. Workspace selector/context strip, Project presentation, and functional timeline remain absent. | Implement remaining real, tested workflows in roadmap order; inherited capability and visible controls do not close them. |
| Packaging and release | A signed full-tree Linux development tar is verified at source `4e9eff50`; packaging 80/80 and legal/source guards pass. It is development-only and retains a locked-Pixi fallback RUNPATH. Production SPKI/key custody, dependency bundling, clean-machine lifecycle, runtime SBOM, signing/notarization, tag and Release are absent. | Pass every production package/install/release gate; unavailable credentials remain explicit blockers. |

Linux and Windows are green at terminal head `3f54ec58`; the new candidate is
green locally through 1,431 CTests, 1,674 CLI, 1,776 GUI and final development-package verification, but local evidence is not native macOS or production-package
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

- The last terminal matrix is mixed. Linux and Windows pass every baseline gate;
  both macOS architectures require the explicit owned-MDI teardown rerun.
- Repository submodules must be initialized recursively before a complete
  build; no submodule-free source package has been validated.
- Current binaries and many user-facing identifiers still use FreeCAD names.
  They are transitional development outputs, not OpenFusion release artifacts.
- A development-only OpenFusion `tar.zst` exists and passes build-host
  verification. No production AppImage, `tar.zst`, DEB, RPM, Windows installer,
  or macOS DMG has passed clean-machine installation and lifecycle testing.
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
