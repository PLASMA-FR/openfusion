# OpenFusion Execution State

**Last verified:** 2026-08-30 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Publish locally verified candidate
`46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa`, re-fetch the resulting integration
head, and rerun the complete Linux, Windows, and macOS matrix without weakening
any gate. Linux is green at the prior published head; M0 is not complete.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Remote integration head | `8aebea6cc733fc4d16d79c2deacf1d2b1525489a` |
| Local tested candidate head | `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa`; fully green on local Linux arm64, but unpublished and not native Windows or macOS evidence |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; Linux is green at `8aebea6cc733fc4d16d79c2deacf1d2b1525489a`, while Windows and both macOS jobs are terminal and failed |
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

### Locally verified follow-up candidate awaiting publication and native reruns

| Local commit | Change |
|---|---|
| `8c7cc53` | Guard deferred Draft clone formatting against deleted Python/C++ object wrappers and make the callback regression fail on early, missing, or duplicate delivery. |
| `9cb165fc` | Harden the BIM GUI-test teardown path against document objects deleted before deferred cleanup. |
| `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa` | Add deterministic Windows Qt platform-plugin discovery and propagate the platform path to native tests and lifecycle subprocesses. |

The Draft/BIM and Windows Qt changes completed focused review. Direct Draft
regressions passed 4/4 `drafttests.test_clone_gui` and 30/30
`drafttests.test_modification`; a composed GUI set passed 31/31 across Draft GUI
(13), BIM Window (1), BIM Site (3), PathHelix (8), and PathHelix generator (6).
ArchSite save/reopen passed 1/1. Black, `py_compile`, and diff checks passed.
The Windows helper passed 5/5; synthetic CTest bootstrap, missing-`qwindows`
failure, a configure harness with fake imported `Qt6::qmake`, Python AST, YAML,
and diff checks passed. Static review found no actionable defect and confirmed
PRE_TEST discovery, CTest environments, lifecycle subprocess propagation, and
CI topology. No native Windows execution exists yet. The combined candidate
completed a 1,704/1,704 Release rebuild followed by a clean no-op build. The
runtime helper passed 5/5 and the summary parser passed 9/9. CTest registered
1,433 tests and passed all 1,427 enabled tests, with three skipped, six disabled,
and all four acceptance tests passing in 95.47 seconds. CLI ran 1,661 tests with
10 skips and zero failures; the parser counted 1,661. A faithful safe-mode GUI
run completed 1,763 tests with zero failures, exit 0, and parser count 1,763 in
`4.22e+02s`. TechDraw GUI export passed 1/1 in 2.54 seconds with exit 0, a
13,163-byte SVG, and a 298,780-byte PDF. These are local Linux arm64 results; no
native Windows pass, macOS pass, or publication is claimed.

### Exact combined-candidate commands

```bash
# Full Release rebuild, then the clean no-op repeat
pixi run build-release
pixi run build-release

.pixi/envs/default/bin/python tests/ci/test_windows_test_runtime.py -v
.pixi/envs/default/bin/python tests/ci/test_validate_unittest_summary.py -v

xvfb-run -a pixi run ctest --test-dir build/release --output-on-failure \
  --no-tests=error --parallel 2 --timeout 600

pixi run build/release/bin/FreeCADCmd --safe-mode \
  --user-cfg <profile>/user.cfg --system-cfg <profile>/system.cfg \
  --log-file <log> -t 0

LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb timeout 3600s \
  pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  build/release/bin/FreeCAD --safe-mode \
  --user-cfg <profile>/user.cfg --system-cfg <profile>/system.cfg \
  --log-file <log> -t 0

OPENFUSION_ACCEPTANCE_OUTPUT_DIR=<output> LIBGL_ALWAYS_SOFTWARE=1 \
  QT_QPA_PLATFORM=xcb pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  build/release/bin/FreeCAD --safe-mode \
  --user-cfg <profile>/user.cfg --system-cfg <profile>/system.cfg \
  --log-file <log> --python-path "$PWD/tests/acceptance" \
  --run-test OpenFusionTechDrawGuiExportAcceptance
```

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

### Previously verified local head now published as `8aebea6c`

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

These Linux arm64 results supported publication of the preceding platform
changes. They are not Windows or macOS evidence. An earlier hidden-mode
diagnostic run was invalid and interrupted and remains excluded.

## Terminal GitHub Actions evidence at published head `8aebea6c`

All artifacts below expire on 2026-09-29.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Linux `33315700516` | **Passed.** Release build completed; CTest passed 1,427/1,427 enabled tests in 65.01 s; TechDraw GUI export passed; CLI ran 1,661 tests with 10 skips and no failures in 106.942 s; GUI ran 1,759 tests with no failures in `2.67e+02s`. | Baseline `9734764667`, 6,880,803 bytes, SHA-256 `1342f4fdfc0d61878bf0e8d649fd8e1d47c602836f343d8c8bbbe659b020668d`; TechDraw `9734681765`, 603,858 bytes, SHA-256 `89a533a6ae773bd4dad1389a78604f20e002fefb2f38d5ec1e58d8da8735240c` |
| Windows `33315700534` | **Failed.** The 6,757-edge Release build, native-output/runtime checks, and discovery passed. CTest passed 1,426 of 1,429 enabled tests: QuantitySpinBox and DlgVersionMigrator timed out at 600.01 s, and GUI lifecycle failed after its internal 270 s timeout. Diagnostics identify the missing Qt platform-plugin runtime path. Later CLI/GUI gates were skipped. | Baseline `9735287481`, 725,548 bytes, SHA-256 `5afd1fcb190154af00827a7e8513a7ce03f08e196750d89094b6cfed9c68819f` |
| macOS arm64, run `33315700529` | **Failed at GUI.** Build passed; CTest passed 1,427/1,427 in 98.20 s; TechDraw passed; CLI ran 1,661 tests with 10 skips and no failures in 102.744 s. Deferred Draft callbacks then accessed deleted wrappers and the GUI process exited 1. | Baseline `9734798119`, 6,867,117 bytes, SHA-256 `6aea205942cc253eba22179d57d2cfd4e3846c8beeef283a5ad4ee7644ed7838`; TechDraw `9734714900`, 597,312 bytes, SHA-256 `710134587a57303ccb9cc8b6d79758817f509cf01928fa16896b4d8b3dd5a5bd` |
| macOS x86_64, run `33315700529` | **Failed at GUI.** Build passed; CTest passed 1,427/1,427 in 281.98 s; TechDraw passed; CLI ran 1,661 tests with 10 skips and no failures in 155.187 s. The same deferred Draft deleted-wrapper failures caused GUI exit 1. | Baseline `9735846989`, 6,872,107 bytes, SHA-256 `da1d4097afea87224668587caf1eea6f52526570ee60065518005f91074061d3`; TechDraw `9735654821`, 597,368 bytes, SHA-256 `7e1225b8aeee89e87e7dd78cae98f5a34a529a0f14cef527e0701c7560cf4256` |
| Security `33315700537` | **Failed only at Dependency Review.** CodeQL actions, C/C++, and Python all passed. Dependency Review remained fail-closed because the repository Dependency Graph is disabled. | None |

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | PR #28 is mixed at `8aebea6cc733fc4d16d79c2deacf1d2b1525489a`: Linux is green; Windows and both macOS jobs are red. Candidate `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa` is fully green on local Linux arm64 but remains unpublished and lacks native Windows/macOS proof. |
| P0 | Windows native tests | Build, runtime checks, and discovery pass, but the missing Qt platform-plugin path caused two Qt test timeouts and the lifecycle timeout. Candidate `46d2f83` is locally green and requires a real Windows rerun. |
| P0 | macOS matrix | Both architectures pass build, CTest, TechDraw, and CLI, but deferred Draft callbacks access deleted wrappers during the GUI suite and exit 1. The combined Draft/BIM candidate is Linux-green and requires both native reruns. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Publish the three locally verified focused commits through candidate `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa` to `integration/acceptance-ci` without rewriting shared history.
2. Re-fetch the branch and PR #28 and record the exact new SHA; do not treat local Linux evidence as a native platform pass.
3. Rerun Windows and both macOS architectures; rerun Linux as part of the complete matrix before accepting M0.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
