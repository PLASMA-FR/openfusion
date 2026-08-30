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
- Committed locally, but have not yet published, Qt-callback exception containment with
  exact 0/1/7 lifecycle coverage, a finite scientific-notation unittest summary
  parser, and corrections for the Windows FileInfo/offscreen failures exposed
  by the first cross-platform rerun.

### Verification

- On committed local tested implementation head
  `2f7fa2c8e940759d07698442054af0d12f222125`, based on remote head
  `51ae387b9ff3c0d1f3c894adb897717664967974`, incremental Release builds of 324
  and then four edges passed. CTest reported 1,433 registered, 1,427 enabled,
  zero failures, three skips, and six disabled tests in 90.11 seconds. CLI ran
  1,661 tests with 10 skips and no failures in 153.353 seconds. A faithful
  safe-mode GUI run reported 1,759 passes, zero failures, process exit 0, and a
  parsed count of 1,759 in 420 seconds.
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
- Draft PR #28 is terminal and red at
  `51ae387b9ff3c0d1f3c894adb897717664967974`: Linux rejected a valid scientific
  GUI duration after 1,759 passing tests; Windows passed Materials 35/35 but had
  two FileInfo assertions and three timeouts; macOS arm64 terminated on an
  exception escaping a Qt callback; macOS x86_64 reported 1,759 passing GUI
  tests but exited 1. Security failed only on the disabled Dependency Graph;
  all three CodeQL jobs passed.

### Security

- Defined private vulnerability reporting and pre-release security gates.

### Known limitations

- No OpenFusion feature milestone or binary release has been completed.
- Baseline builds, tests, package installation, and platform support remain
  unverified; see [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Releases

There are no OpenFusion releases yet. An entry is added here only after its tag,
artifacts, checksums, notices, and recorded acceptance evidence exist.
