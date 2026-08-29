# Known Issues

**Status:** Foundation/pre-alpha

**Release blocker count:** Not yet baselined

**Production use:** Not supported

This list distinguishes known project gaps from verified product defects. An
inherited FreeCAD capability is not considered verified OpenFusion support
until its build and workflow evidence is recorded.

## Foundation blockers

- The untouched FreeCAD 1.1.3 configure, compile, unit, Python, GUI, and manual
  launch baseline is still pending in the supported environments.
- Repository submodules must be initialized recursively before a complete
  build; no submodule-free source package has been validated.
- Current binaries and many user-facing identifiers still use FreeCAD names.
  They are transitional development outputs, not OpenFusion release artifacts.
- No OpenFusion-branded AppImage, `tar.zst`, DEB, RPM, Windows installer, or
  macOS DMG has been produced and clean-install tested.
- Linux, Windows, and macOS support claims remain unverified. Signing and
  notarization credentials and hardware-specific viewport coverage are not
  established.
- The dependency, bundled-asset, and third-party-license inventory is
  incomplete. No OpenFusion binary may be released until redistribution terms,
  notices, and shipped license texts are audited.
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
