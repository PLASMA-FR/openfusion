# OpenFusion Execution State

**Last verified:** 2026-08-30 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Commit and publish the locally verified next-head platform fixes,
re-fetch draft PR #28, and rerun the complete Linux, Windows, macOS arm64, and
macOS x86_64 matrix. Do not advance the milestone until that matrix is green or
a precise external blocker is recorded.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Remote integration head | `51ae387b9ff3c0d1f3c894adb897717664967974` |
| Local tested implementation head | `2f7fa2c8e940759d07698442054af0d12f222125`; committed locally and awaiting publication, so not remote evidence |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; all recorded runs at `51ae387b9ff3c0d1f3c894adb897717664967974` are terminal and failed |
| Dependency lock | `pixi.lock`, SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |

### Published platform work at the remote head

| Remote commit | Change |
|---|---|
| `29975843fecf1fc6f6965ed5b4f7832385b17afc` | Pass generated Part mirror commands to Python as UTF-8. |
| `07d61bc20d3313b75a2b2abdd414e0a7e2536ca1` | Isolate FileInfo fixtures across processes. |
| `0f628e97a1f64cdc72e9f1e2d4ebdd37190368d4` | Bootstrap Windows native-test runtime paths. |
| `7551fa88e3acbe5ce02dcfdf83a8a2674555bf47` | Initial GUI event-loop exit-code and cleanup handling. |
| `001e14c26c8abbf77e40a178601cbe3c911045c9` | Verify Windows native CTest runtime discovery. |
| `51ae387b9ff3c0d1f3c894adb897717664967974` | Record the prior local and remote execution state. |

The Windows runner proved the runtime-path correction by executing all 35
Materials tests. It did not prove the complete Windows gate. The macOS arm64
runner proved that the initial SystemExit change did not contain the exception
inside Qt callbacks. No published platform change may be called accepted from
these failed workflows.

### Committed, locally verified next head awaiting publication

| Local commit | Change |
|---|---|
| `02c4cef49a29d4229f204b79117f759165a4349c` | Contain SystemExit at Qt callback boundaries and preserve lifecycle exit semantics. |
| `aa30b3adea8999b0076dde1e635cefbc1119c4a1` | Validate finite unittest summaries including scientific-notation durations. |
| `3e711e11d003f92be4316dfc11931b2a329ad43b` | Make the affected Qt GUI tests deterministic on the offscreen platform. |
| `2f7fa2c8e940759d07698442054af0d12f222125` | Exercise FileInfo WriteOnly behavior and assert the Windows readable-and-writable projection without skipping or changing the DACL. |

- Contains `SystemExit` at Qt callback boundaries, preserves first-exit-code
  semantics, and exercises exact codes 0, 1, and 7 with cleanup.
- Parses finite unittest durations in integer, decimal, and scientific notation
  instead of rejecting a valid Linux GUI summary.
- Addresses the Windows FileInfo and offscreen GUI failures observed at the
  published head.
- Resolves final-review findings for the lifecycle timeout budget and FileInfo
  test suppression: the timeout is 330 rather than 240 seconds, and FileInfo
  always executes WriteOnly while documenting and asserting the Windows
  readable-and-writable projection without a skip or DACL change.

These commits have Linux arm64 evidence only and are not yet present on GitHub.

## Local environment

| Field | Value |
|---|---|
| OS / architecture | Ubuntu 24.04 / arm64 |
| CPU / concurrency | Neoverse-N1 / 2 CPUs |
| RAM | 12,506,804,224 bytes |
| Pixi | 0.59.0 |
| Compiler | Clang 21.1.0 |
| Build tools | CMake 4.2.1; Ninja 1.13.2 |
| Runtime UI stack | Python 3.11.14; Qt 6.8.3 |

## Exact local test evidence

### Reproduced baseline

| Gate | Result |
|---|---|
| Build | 6,744/6,744 steps passed |
| Discovery | 1,428 CTest entries |
| CTest | 1,422 enabled; two FileInfo race failures; three skipped; six disabled; all three acceptance tests passed; 79.22 s |
| Race diagnosis | The relevant serial rerun passed 14/14, confirming cross-process fixture interference |
| Unicode mirror | The exact focused GUI regression failed 1/1 and exited 1 |

### Published integration implementation, tested locally

| Gate | Result |
|---|---|
| Incremental build | 634/634 steps passed |
| Discovery | 1,429 CTest entries |
| CTest | 1,423 enabled; zero failures; three skipped; six disabled; all four acceptance tests passed; 80.86 s |
| SystemExit focus | 1/1 passed in 3.39 s; exact exit code 7 preserved and cleanup executed |
| Unicode mirror focus | 1/1 passed in 0.563 s |
| FileInfo stress | 2,000 targeted invocations and 1,400 full-fixture repetitions passed |
| Windows runtime helper | 5/5 unit tests passed locally; real Windows CTest remains pending |
| TechDraw GUI export | 1/1 passed in 2.54 s; SVG 13,163 bytes; PDF 298,780 bytes |
| CLI suite | 1,661 ran, 10 skipped, zero failures, 156.014 s |
| GUI suite | 1,759 passed, 424 s |

### Committed local next head awaiting publication

| Gate | Result |
|---|---|
| Incremental Release build | 324 edges passed; a four-edge follow-up build also passed |
| Summary parser | 9/9 unit tests passed |
| SystemExit classifier and FileInfo focus | 4/4 classifier cases plus 2/2 targeted FileInfo cases passed |
| Qt callback coverage | 2/2 targeted tests passed |
| GUI lifecycle | 1/1 CTest passed across three exact-exit scenarios: 0, 1, and 7, including cleanup; final review's timeout-budget finding was addressed by increasing the CTest timeout from 240 to 330 seconds |
| TechDraw GUI export | 1/1 passed in 2.55 s; process exit 0; SVG 13,163 bytes; PDF 298,780 bytes |
| Full CTest | 1,433 registered; 1,427 enabled; zero failed; three skipped; six disabled; 90.11 s |
| CLI suite | 1,661 ran; 10 skipped; zero failures; 153.353 s; parser count 1,661 |
| GUI suite | Faithful safe-mode run: 1,759 passed; zero failures; `4.2e+02s`; process exit 0; parser count 1,759 |

An earlier hidden-mode diagnostic run was invalid and interrupted. It is not a
product pass or failure and is excluded from the evidence totals.

## Terminal GitHub Actions evidence at the remote head

All artifacts below expire on 2026-09-29.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Security `33302508107` | Failed only because Dependency Review was fail-closed while the repository Dependency Graph was disabled. All three CodeQL jobs passed. | None |
| Linux `33302508115` | Failed after the GUI runner reported 1,759 tests and `OK`; the workflow summary parser rejected the scientific-notation duration. | Baseline `9730899331`, 6,858,545 bytes, SHA-256 `b31ee677c4cdda2780757462a65bf2da88fd4be7f485536ab844fbd02e05746d`; TechDraw `9730823771`, 603,842 bytes, SHA-256 `f5c20186b09e4f04ab805e7aaa86ea96f82cc9ad9ba8cab30ae45c75595592b5` |
| Windows `33302508110` | Failed. Materials passed 35/35 after runtime bootstrapping; FileInfo had two assertion failures; QuantitySpinBox and DlgVersionMigrator each timed out at 600 s; GUI lifecycle timed out at 90 s. | `9731537416`, 718,526 bytes, SHA-256 `055c10d61f99453da677eac40f247456c65dd01e509c187d9d1692a6de727b58` |
| macOS arm64, run `33302508113` | Failed when an uncaught `Base::SystemExitException` terminated the process at -6 instead of returning the requested code; lifecycle cleanup did not complete. | `9730507223`, 534,321 bytes, SHA-256 `b2310d67d570bacb3dada5a4bf9c9c22113c3ef3b8ee3d7845a06547a37164bc` |
| macOS x86_64, run `33302508113` | Failed after the GUI suite reported 1,759 tests and `OK`, but the process exited 1. | Baseline `9731697288`, 6,850,827 bytes, SHA-256 `fcf219297fc674ff4caa8d272f01fdd5df7c98a3be4eab3a978becdcbf7754c5`; TechDraw `9731523318`, 597,342 bytes, SHA-256 `b157fdb0172d41d1354b89d7515b5ac6a7f4b44e97a6f2bb68b87878ebed9011` |

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | PR #28 at `51ae387b9ff3c0d1f3c894adb897717664967974` is terminal and red. Green results belong to committed local head `2f7fa2c8e940759d07698442054af0d12f222125`, which awaits publication. |
| P0 | Windows native tests | Runtime discovery now executes Materials 35/35, but FileInfo assertions and three GUI/offscreen timeouts keep the Windows gate red. Local candidate fixes require a native rerun. |
| P0 | macOS matrix | arm64 terminates on an exception escaping a Qt callback, and x86_64 exits 1 after an otherwise successful GUI suite. Local containment changes require both native reruns. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Commit the verified Qt callback, lifecycle, scientific-summary, Windows FileInfo, and offscreen corrections as focused changes.
2. Publish them to `integration/acceptance-ci` without force-pushing or rewriting shared history, then re-fetch the branch and draft PR #28 and record the exact new SHA.
3. Rerun the complete Linux, Windows, macOS arm64, and macOS x86_64 matrix.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
