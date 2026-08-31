# OpenFusion Execution State

**Last verified:** 2026-08-31 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Re-fetch the resulting integration branch and PR #28 head, record
its exact state-update SHA/tree in the PR comment, and run/retrieve Linux,
Windows, macOS arm64, macOS x86_64, and Security. Do not predict the documentation
commit SHA or infer a native pass from local Linux evidence.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Published integration base | `8edc271bc0b39f942c26a28f6c797570edda3caa`, state tree `7d239dd15da5a1900e4d2be7a0a2180db5e75330` |
| Connector-created lifecycle implementation | Diagnostics `d89b6cbd30e81ed9b5ab402ae1ec9bff6f334d16`, tree `9d812e59`; automated propagation `a56554cc451ad73440e2a4f70d4c8736e4f93d1c`, tree `c3838e96`; Windows internal-mode last-window handling `12081664bccfb342be1f50f3a3e6d0e91a23be22`, tree `8a477f3d` |
| Integration state update | The verified implementation chain is the base accompanying this documentation update on integration. This file does not predict its own commit SHA; the exact resulting head belongs in the verified PR comment after connector re-fetch |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; all `8edc271` runs are terminal: Linux green, Windows failed one lifecycle CTest, both macOS architectures exited 1 after 1,763-test `OK` application logs, and Security failed only on disabled Dependency Graph. No native rerun exists yet for `1208166` |
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

### Internal GUI unittest diagnostics and automated exit propagation

Connector-created commit `d89b6cbd30e81ed9b5ab402ae1ec9bff6f334d16`
adds fail-closed diagnostics around the internal GUI unittest callback. Commit
`a56554cc451ad73440e2a4f70d4c8736e4f93d1c` propagates the callback result through
the existing orderly GUI exit path so nonzero results survive event-loop shutdown,
Python finalization, lock cleanup, and application teardown. Windows commit
`12081664bccfb342be1f50f3a3e6d0e91a23be22` disables Qt automatic
quit-on-last-window only for internal unittest mode; otherwise Qt could exit the
event loop before the queued callback ran. Explicit positional, successful,
failing, diagnostic, and `SystemExit` exits remain authoritative.

The diagnostic wrapper captures the original stdout/stderr objects, prints the
full original exception traceback to stderr or the FreeCAD error-log fallback,
flushes original and current streams, and rethrows the same exception. It never
turns a failed callback into success, replaces the original exception with a
flush error, masks a nonzero exit, or skips teardown. Full tracebacks can contain
filesystem paths, exception messages, and test-supplied values; CI/application
logs and retained artifacts containing these diagnostics must therefore be
handled as potentially sensitive. The mechanism is scoped to the internal GUI
unittest runner and is not a general crash-report upload channel.

Local Linux arm64 evidence at the `13edad` implementation state: the warm
affected rebuild completed all 93 effective Ninja edges (the initial graph
reported 94 before MOC pruning); the immediate repeat build was clean/no-op
except the existing version-file generator. The Windows runtime helper passed
6/6. The lifecycle regression passed positional 7, internal success 0, internal
failure 1, diagnostic failure 1, and internal `SystemExit(23)` with cleanup in
19.64 seconds. CTest registered 1,433 tests and passed all 1,427 enabled tests in
100.78 seconds, with three skipped, six disabled, and all four acceptance tests
passing. The CLI suite ran 1,667 tests with 10 skipped and zero failures in
149.782 seconds; the parser counted 1,667. The increase from historical native
totals of 1,661 is exactly the six newly registered `GuiTestRunner` diagnostic
tests. The faithful safe-mode GUI suite passed 1,769/1,769 with exit 0 in
`4.2e+02s`. These are local results; native Windows and macOS reruns remain
required.

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

## Terminal GitHub Actions evidence at published head `8edc271`

All artifacts below expire on 2026-09-29.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Linux `33340018602` | **Passed.** Release build, 1,427/1,427 enabled CTests, TechDraw GUI export, 1,661 CLI tests, and 1,763 GUI tests all passed. | Baseline `9741262458`, 6,880,134 bytes, SHA-256 `e6c4ad5bf83716f0200e253571120e44ae74ca4a8ef208eab7ae13d70e7ea6ab`; TechDraw `9741185797`, 603,861 bytes, SHA-256 `6b5c08346cb1a4b1a68ab3cf45f2136262fb31aa101a7c860271437f80a21885` |
| Windows `33340018502` | **Failed CTest.** The 6,758-edge build, native output/plugin checks, discovery, QuantitySpinBox, and DlgVersionMigrator passed. CTest passed 1,428/1,429 enabled tests; only `OpenFusion_GUI_SystemExit_Propagation` failed in 15.64 seconds. Qt automatic last-window exit preempted the queued internal callbacks, so the process returned 0 instead of required 1, wrote no callback observation, and did not finalize embedded Python. Later TechDraw/CLI/GUI gates were skipped. | Baseline `9742796772`, 748,854 bytes, SHA-256 `58ca56f820e68ef481a2ddb230d2d5751e00edc9a4acc31c47d872c91102abd7` |
| macOS arm64, run `33340018607` | **Failed at GUI process exit.** Build, 1,427/1,427 enabled CTests, TechDraw, and 1,661 CLI tests passed. The application log reported 1,763 GUI tests and `OK`, but a hidden internal callback exception left process exit 1 and normal teardown was not observed. | Baseline `9741680756`, 6,863,990 bytes, SHA-256 `f70c65d6244c2d8e5b0ccdbbbfc1621cc45cd8f34257eaeb5b145c40ccfecc58`; TechDraw `9741584722`, 594,367 bytes, SHA-256 `c920e32cf19c1b5f865276b02529bc221bdc4168511271882f2f1d41563e9a41` |
| macOS x86_64, run `33340018607` | **Failed at GUI process exit.** Build, 1,427/1,427 enabled CTests, TechDraw, and 1,661 CLI tests passed. The application log reported 1,763 GUI tests and `OK`, but a hidden internal callback exception left process exit 1 and normal teardown was not observed. | Baseline `9742174311`, 6,868,634 bytes, SHA-256 `28f744541db04b29e88150531d52aa1f348860a20e7f9737d27145e08c750508`; TechDraw `9741984725`, 594,364 bytes, SHA-256 `0c0ed6552022ec9edeb1955ffd7956e4f46fce808b397e6e329a99d45160f26b` |
| Security `33340018525` | **Failed only at Dependency Review.** CodeQL actions, C/C++, and Python all passed. Dependency Review remained fail-closed because the repository Dependency Graph is disabled. | None |

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | At `8edc271`, Linux is green; Windows fails only the internal lifecycle CTest; both macOS architectures exit 1 after 1,763-test `OK` GUI logs without observed teardown. Combined implementation through `1208166` is locally green but has no native rerun. |
| P0 | Windows native tests | Native Qt plugin discovery and both Qt tests are proven. Automatic last-window quit preempts internal callbacks, producing return 0, no observation, and no Python finalization. Commit `1208166` disables that automatic quit only in internal mode and requires a native rerun. |
| P0 | macOS matrix | Both architectures pass build, CTest, TechDraw, and CLI, then report 1,763 GUI tests and `OK` but exit 1 without observed normal teardown. Automated internal-result propagation requires both native reruns. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Re-fetch the resulting integration branch and PR #28 head and record the exact state-update SHA/tree in the PR comment without predicting it here.
2. Run and retrieve Linux, Windows, macOS arm64, macOS x86_64, and Security at that verified head before accepting M0.
3. Triage exact failing steps and preserve every artifact; do not mask nonzero results or bypass teardown.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
