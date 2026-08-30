# OpenFusion Execution State

**Last verified:** 2026-08-30 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Re-fetch the resulting integration branch and PR #28 head after
this documentation update, record its exact state-update SHA/tree in the PR
comment, and run/retrieve Linux, Windows, macOS arm64, macOS x86_64, and Security.
Preserve the terminal results from the still-active `fa0f3b6` Windows and macOS
x86_64 jobs when they complete.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Published SectionCut implementation | `11abf724213c6309ecd32f5c14507c68e5bd43fd`, tree `72cb369ca34bcdac7d7aa7fe73105a883997218a`; connector-created from locally tested `c120c0dd2e07b6eb38a2df43bbc5535a157fbba2` |
| Integration state update | SectionCut implementation `11abf72` is the published base and this documentation update accompanies it on integration. This file does not predict its own commit SHA; the exact resulting head belongs in the verified PR comment after connector re-fetch |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; latest terminal/active native evidence remains at `fa0f3b6`: Linux green, macOS arm64 GUI process exit 1 after a 1,763-test `OK` application log, Windows/macOS x86_64 still active. No native rerun exists yet for `11abf72` |
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

### Published correction head `fa0f3b6` and local verification

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
native Windows or macOS pass is claimed for this local evidence. The exact tree
was subsequently published as `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`.

### Published SectionCut implementation awaiting native rerun

Connector-created commit `11abf724213c6309ecd32f5c14507c68e5bd43fd`, tree
`72cb369ca34bcdac7d7aa7fe73105a883997218a`, maps the reviewed local commit
`c120c0dd2e07b6eb38a2df43bbc5535a157fbba2` and changes one test file. The prior
SectionCut regression placed its only box in a compound,
hid that box, and could accept a missing dock or the wrong case instead of
proving the command opened and closed the actual Section Cut dock. The reviewed
replacement uses a visible source object and asserts the dock, button box,
Close button, and deferred deletion lifecycle.

The affected Release rebuild passed 358/358 edges and the repeat build was a
clean no-op. The focused regression passed 1/1 in 0.585 seconds; current
`TestPartGui` passed 13/13 in 3.23 seconds; and the faithful safe-mode full GUI
suite passed 1,763/1,763 with exit 0 in 423 seconds and no deferred exception.
This is local Linux arm64 evidence only. The implementation is published as an
ancestor of this state update, but its native macOS rerun remains pending.

```bash
LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb timeout 600s \
  pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  build/release/bin/FreeCAD --safe-mode \
  --user-cfg <profile>/user.cfg --system-cfg <profile>/system.cfg \
  --log-file <log> -t TestPartGui.SectionCutTestCases.testOpenDialog
```

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

## Latest GitHub Actions evidence at published head `fa0f3b6`

All artifacts below expire on 2026-09-29.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Linux `33333139217` | **Passed.** Release build, 1,427/1,427 enabled CTests, TechDraw GUI export, 1,661 CLI tests, and the expanded 1,763-test GUI suite all passed. | Baseline `9739849026`, 6,879,588 bytes, SHA-256 `49a908d9394bb77be62d23beccffe66e5f87b67489d411011e8b04b3ceab3a2e`; TechDraw `9739761364`, 603,854 bytes, SHA-256 `9689e1cb5ffd7cb3d1da694ebab73fc9e239a39d5326b8b58954d1cf423d2c03` |
| macOS arm64, run `33333139229` | **Failed at GUI process exit.** Build, 1,427 enabled CTests, TechDraw, and 1,661 CLI tests passed. The application log reported 1,763 GUI tests and `OK`, but the process exited 1. Triage traced the only new exception to the invalid SectionCut regression setup and its weak dock assertion. | Baseline `9739523215`, 6,870,210 bytes, SHA-256 `a88a0a51f8c260555a852c2d8e5a3c8e5aa6f5ea70dbf39442feb9b96a49cd94`; TechDraw `9739432731`, 597,323 bytes, SHA-256 `e8ff30a63b8b7bf41b8ba8d544107bfaa3fa154045952c4c315802081fd38307` |
| macOS x86_64, run `33333139229` | **In progress.** Configure passed and the Release build is active. No later gate or artifact is claimed. | None yet |
| Windows `33333139201` | **In progress.** Configure passed and the Release build is active. No native-output, discovery, CTest, CLI, GUI, or artifact result is claimed. | None yet |
| Security `33333139224` | **Failed only at Dependency Review.** CodeQL actions, C/C++, and Python all passed. Dependency Review remained fail-closed because the repository Dependency Graph is disabled. | None |

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | PR #28's latest native evidence is mixed at `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`: Linux is green; macOS arm64 exits 1 after a 1,763-test `OK` GUI log; Windows and macOS x86_64 are still active. SectionCut implementation `11abf72` is published and Linux-green, but its native rerun is pending. |
| P0 | Windows native tests | Run `33333139201` is still building. The Qt platform-plugin correction has no completed native Windows evidence yet. |
| P0 | macOS matrix | arm64 passes build, CTest, TechDraw, and CLI but exits 1 after the GUI application log reports 1,763 tests and `OK`; x86_64 is still building. The locally green SectionCut correction requires native reruns. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Preserve the terminal results and artifacts from active Windows `33333139201` and macOS x86_64 `33333139229` when they complete.
2. Re-fetch the resulting integration branch and PR #28 head and record the exact state-update SHA/tree in the PR comment.
3. Run and retrieve Linux, Windows, macOS arm64, macOS x86_64, and Security at that verified head before accepting M0.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
