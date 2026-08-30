# Changelog

All notable OpenFusion-specific changes will be recorded in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
OpenFusion intends to use [Semantic Versioning](https://semver.org/) once
versioned OpenFusion releases begin.

This changelog covers OpenFusion changes, not the complete history inherited
from FreeCAD. See FreeCAD's repository and release notes for upstream history.

## [Unreleased]

### Added

- Pinned the foundation to FreeCAD 1.1.3 commit
  `145529fe741292ff0b3977a01195bf0247425794` with an upstream remote and
  provenance documentation.
- Began the OpenFusion architecture, roadmap, gap analysis, build, testing,
  packaging, governance, security, and release-gate documentation.
- Added fail-closed locked-Pixi source-build baselines for Linux x86-64,
  Windows x86-64, macOS arm64, and macOS x86-64. The workflows inventory and
  run CTest, CLI, and GUI tests without claiming package support.
- Added initial dependency-review and CodeQL workflows for GitHub Actions,
  C/C++, and Python with read-only checkout and immutable action pins.
- Added CTest-registered acceptance workflows for constrained Part Design,
  Assembly, TechDraw, persistence, history editing, and STEP/STL round trips.

### Removed

- Removed and quarantined 32 inherited material-pattern assets for which
  downstream redistribution permission has not been established, and added a
  recursive source guard against path, blob, metadata, Git LFS pointer, and
  recognized build/package-manifest reintroduction within checked root and
  initialized-submodule Git indexes. Untracked files, Git LFS object storage,
  source archives, and final package payload inspection remain pending.
- Removed the inherited prebuilt Windows thumbnail COM server and all installer
  copy, registration, and uninstall actions pending an independently reviewed
  implementation with OpenFusion identity.

### Changed

- Established OpenFusion as the project identity for new project
  documentation. Executable names, persistent type identifiers, compatibility
  APIs, and much of the inherited UI remain unchanged pending tested migration.

### Fixed

- Implemented TechDraw's declared explicit-line-number `LineFormat`
  constructor and isolated its QColor unit tests from the uninitialized
  application preference singleton used by the legacy constructor.
- Preserved exact UTF-8 output paths in TechDraw SVG and PDF export and added
  rendered, semantic GUI acceptance coverage for both ASCII and Unicode paths.
- Passed generated Part mirror Python commands as UTF-8 rather than Latin-1,
  preserving non-Latin-1 object labels on the current local integration head.
- Preserved an exact nonzero event-loop exit code while still running GUI
  cleanup when `Base::SystemExitException` reaches the application boundary.
- Gave Base FileInfo fixtures process-unique paths so parallel CTest processes
  do not delete or replace each other's files.
- Added deterministic Windows native-test runtime-path bootstrapping and five
  helper unit tests. The native runner now proves Materials 35/35, while other
  Windows failures remain.
- Published Qt-callback exception containment with exact 0/1/7 lifecycle
  coverage, a finite scientific-notation unittest summary parser, and the
  Windows FileInfo/offscreen corrections through integration head
  `8aebea6cc733fc4d16d79c2deacf1d2b1525489a`.
- Prepared and fully verified on local Linux arm64, but have not yet published,
  focused Draft/BIM deleted-wrapper guards and deterministic Windows Qt
  platform-plugin discovery through candidate
  `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa`.

### Verification

- Published integration head `8aebea6cc733fc4d16d79c2deacf1d2b1525489a`
  passed the complete Linux workflow: 1,427/1,427 enabled CTests, TechDraw GUI
  export, 1,661 CLI tests with 10 skips, and 1,759 GUI tests. The retained
  baseline artifact is `9734764667` with SHA-256
  `1342f4fdfc0d61878bf0e8d649fd8e1d47c602836f343d8c8bbbe659b020668d`.
- Focused evidence includes exact exit code 7 plus cleanup, a passing Unicode
  mirror regression, 2,000 targeted and 1,400 full-fixture FileInfo stress
  repetitions, five passing Windows helper tests, rendered TechDraw SVG/PDF
  output, 9/9 parser tests, 4/4 SystemExit classifier cases, 2/2 targeted
  FileInfo cases, 2/2 Qt callback tests,
  and one lifecycle CTest covering exact codes 0, 1, and 7. These are local
  Linux arm64 results, not Windows or macOS evidence. An interrupted hidden-mode
  diagnostic is excluded from the results.
- The final candidate evidence also includes TechDraw GUI export 1/1 in 2.55
  seconds with exit 0, a 13,163-byte SVG, and a 298,780-byte PDF; parser counts
  of 1,661 for CLI and 1,759 for the faithful safe-mode GUI run; and exact GUI
  duration `4.2e+02s`. Final review raised timeout-budget and FileInfo test-
  suppression findings. Both were resolved: the lifecycle CTest timeout is 330
  rather than 240 seconds, and FileInfo always executes WriteOnly while
  documenting and asserting the Windows readable-and-writable projection
  without skipping or changing the DACL.
- Draft PR #28 remains mixed at `8aebea6cc733fc4d16d79c2deacf1d2b1525489a`:
  Linux is fully green; Windows builds and discovers tests but lacks the Qt
  platform-plugin runtime path and fails two Qt tests plus GUI lifecycle;
  macOS arm64 and x86_64 pass build, CTest, TechDraw, and CLI before deferred
  Draft deleted-wrapper callbacks make the GUI process exit 1. Security fails
  only at Dependency Review while the Dependency Graph is disabled; all three
  CodeQL jobs pass. The local `46d2f83` follow-up is not published and has no
  native Windows or macOS result.
- Focused unpublished-candidate evidence passed Draft 4/4 and 30/30, a composed
  Draft/BIM/Path GUI set 31/31, ArchSite save/reopen 1/1, and the existing
  Windows runtime helper 5/5. Synthetic Windows bootstrap, missing-plugin, and
  imported-qmake harnesses also passed, but no native Windows result exists.
- The combined candidate completed a 1,704/1,704 Release rebuild and clean
  no-op build; runtime helper 5/5; summary parser 9/9; 1,427/1,427 enabled
  CTests with all four acceptance tests; 1,661 CLI tests with 10 skips; 1,763
  faithful safe-mode GUI tests with zero failures and exit 0; and TechDraw GUI
  export 1/1 with the expected 13,163-byte SVG and 298,780-byte PDF. These are
  local Linux arm64 results, not publication or native Windows/macOS evidence.

### Security

- Defined private vulnerability reporting and pre-release security gates.

### Known limitations

- No OpenFusion feature milestone or binary release has been completed.
- The cross-platform baseline and installed-package acceptance remain
  unverified; the published Linux source baseline is green. See
  [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Releases

There are no OpenFusion releases yet. An entry is added here only after its tag,
artifacts, checksums, notices, and recorded acceptance evidence exist.
