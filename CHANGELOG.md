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
  cleanup when `Base::SystemExitException` crosses the application boundary.
- Gave Base FileInfo fixtures process-unique paths so parallel CTest processes
  do not delete or replace each other's files.
- Added deterministic Windows native-test runtime-path bootstrapping and five
  helper unit tests. Real Windows runner validation remains pending.

### Verification

- On local head `403e72f24303ab6d7a91d29a35648ef2f0d2cc05`, an incremental Release build
  completed 634/634 steps and CTest reported 1,423 enabled tests, zero failures,
  three skips, six disabled tests, and four passing acceptance tests in 80.86
  seconds. CLI ran 1,661 tests with 10 skips and no failures; GUI reported
  1,759 passes.
- Focused evidence includes exact exit code 7 plus cleanup, a passing Unicode
  mirror regression, 2,000 targeted and 1,400 full-fixture FileInfo stress
  repetitions, five passing Windows helper tests, and rendered TechDraw SVG/PDF
  output. These are local Linux arm64 results, not Windows or macOS evidence.
- Draft PR #28 and `integration/acceptance-ci` still point to
  `1a27d1f46030c9e42aff67bc1d90cb5c6114ea03`; their existing red runs remain
  current remote truth until the local commits are pushed and the matrix is
  re-fetched.

### Security

- Defined private vulnerability reporting and pre-release security gates.

### Known limitations

- No OpenFusion feature milestone or binary release has been completed.
- Baseline builds, tests, package installation, and platform support remain
  unverified; see [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Releases

There are no OpenFusion releases yet. An entry is added here only after its tag,
artifacts, checksums, notices, and recorded acceptance evidence exist.
