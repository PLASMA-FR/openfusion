# OpenFusion Execution State

**Last verified:** 2026-08-31 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Re-fetch the integration branch and PR #28 after publishing the
bounded teardown diagnostics, record the exact head/tree in the PR comment, and
run/retrieve Linux, Windows, macOS arm64, macOS x86_64, and Security. Use that
native evidence to finish the Windows OpenGL and macOS teardown root causes;
do not predict this documentation commit SHA or infer native proof from Linux.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Published integration evidence base | `3f961895a3eb0017ee94201395a2c8782ddad1e5`, tree `30fadacae4d212c852053dd4c58f2a542b656c3c` |
| Connector-created diagnostic implementation | Bounded teardown diagnostics `6edc44ee874e3242605f73d6a76bacca06e2733d`, tree `d2f486b388b5ec97b003a1ed279165a9210028ca`; earlier retained-state chain `23a82e5` / `01ed5b6` / `77dc952`; Windows cross-step Qt export `b022722` |
| Integration state update | The verified implementation chain is the base accompanying this documentation update on integration. This file does not predict its own commit SHA; the exact resulting head belongs in the verified PR comment after connector re-fetch |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; at `3f961895`, Linux is fully green, both macOS architectures pass every pre-GUI gate and log 1,769 GUI tests `OK` before teardown exits 1, Windows passes build/CTest/TechDraw/CLI but reports 59 full-GUI OpenGL/access-violation errors, and Security fails only on disabled Dependency Graph. Native teardown diagnostics `6edc44e` accompany this update and require rerun |
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

### Retained exit-state diagnostics and hostile-fixture isolation

Connector-created commit `23a82e5033c0f6111c5a7266aa4ba3f7de8d5cff`
retains enough internal-runner state to distinguish a requested code from the
first authoritative code and the event loop's raw return from any stored and
selected code. Internal-mode logs record `requested`, `authoritative`, `first`,
dispatch mode, `raw`, `stored_present`, `stored_code`, and `selected`. Gated
lifecycle stage markers prove run return, stream restoration, application
destruction, and main return without changing the selected exit value.

Commit `01ed5b671f5aadabdcaec1b23b092e5c1e15520e` isolates hostile diagnostic
fixtures so injected test identity cannot contaminate later scenarios. Active
test detail is emitted only for the internal runner and is enclosed in quotes,
limited to 512 input code units, truncated with an ellipsis, and escaped for
backslashes, quotes, control/format/surrogate characters, and line/paragraph
separators. This bounds and neutralizes log injection; it does not make the
content non-sensitive. Retained CI/application logs can still reveal sanitized
internal test names and filesystem paths and must be handled accordingly. The
diagnostics observe selection only: they do not override first-code authority,
mask a failure, or bypass teardown.

Commit `77dc9527f937f7d7f8e28f7eae65ee281cf12cad` removes off-thread access to
mutable application Config and QObject detail. Worker callers touch only
primitive mutex-protected exit state. Only SystemExit request detail is moved
into a context-bound GUI-thread lambda. Event-loop raw/stored/selected state is
emitted synchronously on the GUI thread after `QApplication::exec`, and lifecycle
stages are emitted by `MainGui` on the main thread. All Config/QObject reads and
all marker emissions therefore occur on the GUI/main thread. Every marker is
gated to Internal/lifecycle mode and the reporting path is `noexcept`. Ordinary
GUI execution emits none of this detail.

Local Linux arm64 evidence at the `4da` implementation state: the warm affected
rebuild/relink passed 76 edges. The helper passed 6/6; all five lifecycle outcomes
(7, 0, 1, diagnostic 1, and `SystemExit(23)`) passed with cleanup in 20.54 seconds.
An ordinary hidden GUI run exited 0 and a marker scan found none of the Internal
request, event-loop state, active-test, or lifecycle diagnostics. CTest registered
1,433 tests and passed all 1,427 enabled tests in 103.96 seconds, with three
skipped, six disabled, and all four acceptance tests passing. The CLI code path
is unchanged; its current retained result remains 1,667 tests with 10 skips and
zero failures. The faithful safe-mode GUI suite passed 1,769/1,769 with exit 0 in
`4.22e+02s`. Native Windows and macOS reruns remain required.

### Windows cross-step Qt environment export

Terminal Windows evidence proved that CTest's per-test Qt environment does not
persist into later GitHub Actions steps. Connector-created commit
`b022722d50e463dd4d4aefbeedd2c5e340670d5a` extends the runtime helper to resolve
and validate the exact `qwindows`/`qwindowsd` and `qoffscreen`/`qoffscreend`
plugin identities for the active configuration, reject aliases that do not
resolve to the same file, preserve non-ASCII paths, and reject newline or GitHub
command-file injection. It appends runtime directories to `GITHUB_PATH` and
writes only the exact `QT_PLUGIN_PATH` and `QT_QPA_PLATFORM_PLUGIN_PATH`
assignments to `GITHUB_ENV` before CTest, TechDraw, CLI, and GUI steps. It
neither copies DLLs nor hardcodes a package layout.

Local helper evidence at the `a6e` state passed 15/15 unit tests, Black, Python
syntax, workflow YAML parsing, and diff checks. The affected native execution
remains proven only by the preceding `4da` Linux build/lifecycle/CTest/GUI
evidence until the new full native matrix completes.

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

## GitHub Actions evidence at published head `3f961895`

All assigned runs are terminal. Artifacts expire on 2026-09-30.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Linux `33363811020` | **Passed.** Build, 1,427/1,427 enabled CTests, TechDraw, 1,667 CLI tests with 10 skips, and 1,769 GUI tests all passed with orderly teardown. | Baseline `9750186214`, 6,900,671 bytes, SHA-256 `531ed6a131dab28e2b898039a5ce59932524d518eb706fced7a5b2efbcac8972`; TechDraw `9750003836`, 601,429 bytes, SHA-256 `c431237a65cadb0c1ef5786b5bf260e12dff7c8387af7e393e8bafc1a9c15a77` |
| Windows `33363810971` | **Failed only at the full GUI gate.** Build, runtime helper 15/15, all 1,429 enabled CTests, lifecycle, TechDraw, and 1,667 CLI tests passed. Full GUI ran 1,769 tests but produced 59 errors after OpenGL 1.1 context and `QOpenGLWidget` framebuffer failures led to access violations. | Baseline `9752389917`, 7,236,106 bytes, SHA-256 `e3961e1ce8e859283e10f0a1e08e118da13d810021725788384f59b8c3fd880b`; TechDraw `9752179141`, 682,320 bytes, SHA-256 `94d71dce24d1a64b2842b6828e771fb4241e8a38b94e7423ccfcb27e8326cad6` |
| macOS arm64 `33363811070` | **Failed only during full-GUI teardown.** Build, 1,427 CTests, TechDraw, and 1,667 CLI tests passed. The application log recorded all 1,769 GUI tests `OK`, requested/raw/stored/selected exit code 0, and event-loop return before process exit 1. | Baseline `9750200075`, 6,888,450 bytes, SHA-256 `85a31a42d726ed04b2371139e60d120a0363e368b315f05b8cc4fabe32675f53`; TechDraw `9750017210`, 594,535 bytes, SHA-256 `ea15f430614070d90603c88f47fabc144218b50c0575c603552b53428f1f4f1b` |
| macOS x86_64 `33363811070` | **Failed only during full-GUI teardown.** Build, all 1,427 enabled CTests, TechDraw, and 1,667 CLI tests passed; the full GUI process exited 1 after the suite completed without a failed unittest result. | Baseline `9752565135`, 6,892,847 bytes, SHA-256 `a4c582af8afcb5ae8ffeafb5b7eab940ff429ec3a4cabc8d4f0c09c83dc66c6e`; TechDraw `9752126729`, 594,550 bytes, SHA-256 `e3965a5a8c149d881f97ba483972a0d2e511bcf7a373bf3642e767546f0cf94a` |
| Security `33363810919` | **Failed only at Dependency Review.** CodeQL actions, C/C++, and Python passed; Dependency Review is unsupported until Dependency Graph is enabled. | None |

## Historical GitHub Actions evidence at head `021591f`

Actions checked out and tested PR merge commit
`64bc9a7d39f077156ed00fac4fca85cc46ea5604`. Connector comparison proves it is
exactly one merge commit ahead of published head
`021591fa24907546691ab9f1fd5650fa94055bd4` with zero file differences. Artifact
metadata continues to identify `head_sha` as
`021591fa24907546691ab9f1fd5650fa94055bd4`.

All artifacts below expire on 2026-09-30.

| Workflow run | Terminal result | Artifacts |
|---|---|---|
| Linux `33351364928` | **Passed.** Release build, 1,427/1,427 enabled CTests, TechDraw GUI export, 1,667 CLI tests, and 1,769 GUI tests all passed. | Baseline `9745744628`, 6,900,224 bytes, SHA-256 `69eb527f23cbd774f02e475cde67d22bb783da18ddf6e16e0aa6880db1e069a3`; TechDraw `9745630312`, 601,249 bytes, SHA-256 `a5a97892953b756dfd409468ae0e2790b6b7faca75719f657781d3621c3c4e76` |
| macOS arm64, run `33351364926` | **Failed at GUI process exit.** Build, 1,427/1,427 enabled CTests, TechDraw, and 1,667 CLI tests passed. The application log reported 1,769 GUI tests and `OK`, but the process exited 1 without the retained exit-state diagnostic needed to locate the hidden post-suite exception. | Baseline `9745511552`, 6,890,234 bytes, SHA-256 `39f7f33fef2c5ceeb5872f8ecb6137c3e94246f161c4583ce0e06a9ff2cb598c`; TechDraw `9745373685`, 594,366 bytes, SHA-256 `017a0fa04cf696ecfa163ce67ff45ec7e851e47c15758f6c7fe06af8d386b475` |
| macOS x86_64, run `33351364926` | **Failed only at GUI process teardown.** Build and pre-GUI gates passed. CTest registered 1,433 and passed all 1,427 enabled tests in 293.73 seconds; lifecycle passed in 41.37 seconds; TechDraw passed; CLI ran 1,667 tests with 10 skips and parser count 1,667 in 130.752 seconds. The application log reported 1,769 GUI tests in `3.72e+02s`, `OK`, and `Finish: Event loop left`, then the process exited 1 without normal teardown or the required retained-state diagnostic. | Baseline `9746276420`, 6,891,562 bytes, SHA-256 `2594b6fbaf51e8834f5ed5b16192f241b631780848f9ea2b266b7e6528c648e7`; TechDraw `9746115713`, 594,362 bytes, SHA-256 `89dde10370793508de834061704e10f9fd20abc2b03082ea0803023c23bb3de7` |
| Windows `33351364927` | **Failed only at the post-CTest TechDraw step.** The 6,760-edge build passed. Runtime helper tests passed 5/5 and registered 23 runtime directories containing 46 artifacts. Discovery found 1,435 tests; all 1,429 enabled CTests passed in 118.89 seconds, including lifecycle in 25.29 seconds. The next workflow process could not find the qwindows platform plugin because CTest-scoped Qt variables did not cross the step boundary, then timed out at exactly 10 minutes. CLI and GUI were skipped. | Baseline `9746931991`, 780,724 bytes, SHA-256 `bc9783b668f0b3061d40302093a8114863856a2ed558db9fd8c6994935d4b69f`; TechDraw diagnostics `9746931185`, 4,065 bytes, SHA-256 `11edd50daec20541938ce3ccb473f75f3cf677eb3dacbd0350a1e73e44349e58` |
| Security `33351364935` | **Failed only at Dependency Review.** CodeQL actions, C/C++, and Python all passed. Dependency Review remained fail-closed because the repository Dependency Graph is disabled. | None |

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | At `3f961895`, Linux is green; Windows fails only its full GUI gate with 59 OpenGL/access-violation errors; both macOS architectures exit 1 during teardown after successful 1,769-test application logs. Diagnostic commit `6edc44e` is Linux-green locally and requires native rerun. |
| P0 | Windows native tests | Build, runtime discovery, native Qt tests, lifecycle, all 1,429 enabled CTests, TechDraw, and CLI are proven. The full GUI gate must complete without the OpenGL 1.1 framebuffer failures and access violations; tests remain fail-closed. |
| P0 | macOS matrix | Both architectures pass build, CTest, TechDraw, CLI, and the unittest result itself, then exit 1 while unwinding the main window. Bounded destructor/catch/top-level-widget diagnostics `6edc44e` require native rerun before a teardown correction is accepted. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Re-fetch the resulting integration branch and PR #28 head and record the exact state-update SHA/tree in the PR comment without predicting it here.
2. Run and retrieve Linux, Windows, macOS arm64, macOS x86_64, and Security at that verified head before accepting M0.
3. Triage exact requested/authoritative/raw/stored/selected state and preserve every artifact; do not mask nonzero results or bypass teardown.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
