# Known Issues

## Current integration and release blockers (2026-08-30)

| Area | Exact current state | Exit condition |
|---|---|---|
| Remote baseline | Draft PR #28's latest native evidence is mixed at `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`: Linux is fully green; macOS arm64 exits 1 after its application log reports 1,763 GUI tests and `OK`; Windows and macOS x86_64 remain active. SectionCut implementation `11abf724213c6309ecd32f5c14507c68e5bd43fd` is the published base and this documentation update accompanies it on integration, but no native rerun exists yet. | Re-fetch the resulting branch/PR head, record its exact state-update SHA/tree in the PR comment, preserve the active-run evidence, and retrieve every fresh matrix conclusion, log, and artifact. |
| Windows | Run `33333139201` has configured and is still building. No native-output, discovery, CTest, CLI, or GUI result exists yet for the Qt plugin-path correction. | A real Windows Release runner completes every discovered native and GUI test without ad hoc DLL copying or timeout. |
| macOS | arm64 passes build, 1,427 enabled CTests, TechDraw, and 1,661 CLI tests; its application log reports 1,763 GUI tests and `OK`, but the process exits 1 because the SectionCut regression hid its only source and accepted the wrong dock state. x86_64 remains active. | Both macOS jobs validate published SectionCut correction `11abf72` and complete the GUI gate with process exit 0 and no deferred exception. |
| Dependency Review | The last CodeQL jobs were green, but Dependency Review remains fail-closed because the repository Dependency Graph is disabled. CodeQL is not a substitute. | Enable the authorized repository setting and obtain a passing Dependency Review run; retain complementary locked-dependency and SBOM auditing. |
| Security | Audit evidence found a symlink graph escape in PR #27, and the stale DTD-only hardening stack is insufficient for the complete untrusted FCStd/XML/archive threat model. Release-blocker issue #24 remains open. | Close the complete extraction, entity, path, temporary-file, and parser acceptance criteria with regression evidence. |
| Legal and assets | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain in the integration surface. | Remove or replace restricted/unverifiable material, establish provenance, rebuild permissible binaries from reviewed source, and complete shipped notices. |
| Product | There are still no OpenFusion product classes under `src/`; the workspace shell, command palette, contextual actions, Project presentation, and functional timeline are not implemented. | Implement real, tested workflows in roadmap order; inherited FreeCAD capability and visible controls do not close these gaps. |
| Packaging and release | Required clean-installed packages, checksums, SBOMs, signing/notarization evidence, release tag, and verified GitHub Release are absent. | Pass every package and release gate; unavailable credentials remain explicit pre-production blockers. |

Linux is green at tested head `fa0f3b6`; published SectionCut implementation
`11abf72` is green locally on Linux arm64, but local evidence is not a native
platform pass or a production-readiness claim. If one platform remains externally blocked,
work may continue elsewhere, but M0 cannot advance on failed or inferred
evidence.

**Status:** Foundation/pre-alpha

**Release blocker count:** Not yet baselined

**Production use:** Not supported

This list distinguishes known project gaps from verified product defects. An
inherited FreeCAD capability is not considered verified OpenFusion support
until its build and workflow evidence is recorded.

## Foundation blockers

- The published matrix is mixed. Linux passes every baseline gate. Windows
  lacks the Qt platform-plugin runtime path and fails two Qt tests plus GUI
  lifecycle. Both macOS architectures fail the GUI suite on deferred Draft
  callbacks that access deleted wrappers after their documents are closed.
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
- Thirty-two installed material-pattern files state `All rights reserved` and
  are quarantined from every source and binary release until they are removed
  or independently replaced under documented redistribution terms.
- The inherited GUI asset set has 123 SVGs and all 58 PNGs without meaningful
  embedded license markers, and upstream identity art remains wired into the
  GUI and every platform package path. Exact provenance plus original,
  cleared replacement branding is a release blocker.
- The inherited Windows installer contains a prebuilt unsigned thumbnail shell
  extension using FreeCAD's CLSID and system-directory registration. It will
  not ship unless rebuilt from reviewed source with independent identity,
  coexistence, parser, signing, and uninstall validation.
- GitHub Dependency Review is intentionally fail-closed but cannot run until a
  repository owner enables the GitHub dependency graph. CodeQL does not replace
  this dependency-change gate.
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
