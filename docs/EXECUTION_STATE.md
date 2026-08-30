# OpenFusion Execution State

**Last verified:** 2026-08-30 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Retrieve the exact conclusions, failed steps, logs, and artifacts
from the active reruns at published integration head
`fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`: Linux `33333139217`, Windows
`33333139201`, Security `33333139224`, and macOS `33333139229`. Fix any root
cause without weakening a gate and keep PR #28 draft until the complete native
matrix is terminal and green. M0 is not complete.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Remote integration head | `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`; tree `ccfe677824336961b69843b7418adbefcf4709ad`, equal to local tested base commit `a12f145768e057839f7d8ccd2815bda21fec058f` |
| Local tested and published tree | Local commit `a12f145768e057839f7d8ccd2815bda21fec058f`, tree `ccfe677824336961b69843b7418adbefcf4709ad`, published as integration head `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`; fully green on local Linux arm64, with native reruns active but not yet accepted |
| Staged legal rebase candidate | Base `a12f145768e057839f7d8ccd2815bda21fec058f`; initial conflict-free rebase composition tree `ed32be93352c3536a8a3aacb762ccc5546b6957a`, exactly matching Git's three-way merge of that base with PR #15 head `26c7c3a87173a159a429b36a1d2f2e519e70ea1f`; subsequent review fixes remain staged and uncommitted |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`, head `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`; Linux, Windows, Security, and both macOS architecture gates are actively rerunning, so no new native conclusion is claimed |
| Dependency lock | `pixi.lock`, SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |

### Staged legal quarantine candidate

The isolated worktree `/home/ubuntu/openfusion/legal-rebase-candidate` stages
the complete PR #15 removal and quarantine hardening on integration candidate
base `a12f145768e057839f7d8ccd2815bda21fec058f`. The initial rebase index tree
was `ed32be93352c3536a8a3aacb762ccc5546b6957a`, exactly equal to Git's
independently computed three-way merge tree. Review follow-ups additionally
make a quarantined Git LFS SHA-256 sufficient for rejection even when its
pointer declares the wrong size, report both declared and quarantined sizes,
and add an SPDX marker to the Windows guard test. These follow-ups are staged
but have no commit SHA or published tree.

The exact deletion set is the 32 material-pattern identities recorded by the
guard plus `package/WindowsInstaller/thumbnail/FCStdThumbnail.dll`; there are no
other staged deletions. The pinned FreeCAD foundation recomputation matched all
32 Git OID, SHA-256, and size tuples. The removed DLL matched SHA-256
`cf9985aca43c116fe3565436a9da267de8b7f17ceed8c0cae000cfb40e69a1b0` and size
176,128 bytes. After the review follow-ups, the material suite passed 22/22 in
1.857 seconds and the thumbnail suite passed 16/16 in 5.645 seconds with
`ResourceWarning` fatal. The live material guard passed, as did three focused
thumbnail-binary, installer-action, and FCStd-association checks in 4.527
seconds. Black 25.1.0 and security-workflow YAML parsing passed. Final diff,
conflict-marker, recursive-submodule, and high-confidence secret checks also
passed; the candidate remains unpublished pending independent review.

No source archive, staging tree, installer, or package payload has been built or
inspected from this candidate. It has not run on native Windows or macOS and is
not evidence for the in-progress PR #28 native baseline rerun. The next legal
step, after that baseline is green, is independent review of the final staged
tree, a focused commit/publication without rewriting shared history, the full
security workflow, and explicit source-archive, staging, and package-payload
inspection.

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

### Locally verified follow-up tree now published; native reruns active

| Local commit | Change |
|---|---|
| `8c7cc53` | Guard deferred Draft clone formatting against deleted Python/C++ object wrappers and make the callback regression fail on early, missing, or duplicate delivery. |
| `9cb165fc` | Harden the BIM GUI-test teardown path against document objects deleted before deferred cleanup. |
| `46d2f83e6980c5a3aa4a9a84e0f4c0bd9d5b06fa` | Add deterministic Windows Qt platform-plugin discovery and propagate the platform path to native tests and lifecycle subprocesses. |

The Draft/BIM and Windows Qt changes completed focused review and their combined
tree is published as `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`. Direct Draft
regressions passed 4/4 `drafttests.test_clone_gui` and 30/30
`drafttests.test_modification`; a composed GUI set passed 31/31 across Draft GUI
(13), BIM Window (1), BIM Site (3), PathHelix (8), and PathHelix generator (6).
ArchSite save/reopen passed 1/1. Black, `py_compile`, and diff checks passed.
The Windows helper passed 5/5; synthetic CTest bootstrap, missing-`qwindows`
failure, a configure harness with fake imported `Qt6::qmake`, Python AST, YAML,
and diff checks passed. Static review found no actionable defect and confirmed
PRE_TEST discovery, CTest environments, lifecycle subprocess propagation, and
CI topology. Native runs `33333139217`, `33333139201`, `33333139224`, and
`33333139229` are active; none is accepted before its terminal evidence is
retrieved. The combined candidate
completed a 1,704/1,704 Release rebuild followed by a clean no-op build. The
runtime helper passed 5/5 and the summary parser passed 9/9. CTest registered
1,433 tests and passed all 1,427 enabled tests, with three skipped, six disabled,
and all four acceptance tests passing in 95.47 seconds. CLI ran 1,661 tests with
10 skips and zero failures; the parser counted 1,661. A faithful safe-mode GUI
run completed 1,763 tests with zero failures, exit 0, and parser count 1,763 in
`4.22e+02s`. TechDraw GUI export passed 1/1 in 2.54 seconds with exit 0, a
13,163-byte SVG, and a 298,780-byte PDF. These are local Linux arm64 results.
Publication is established at `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`,
but no new native Windows or macOS pass is claimed while the reruns are active.

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

## Historical terminal GitHub Actions evidence at prior head `8aebea6c`

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
| P0 | Remote integration evidence | PR #28 remains draft at published head `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`. Linux run `33333139217`, Windows run `33333139201`, Security run `33333139224`, and macOS run `33333139229` are active; queued or running gates are not passes. |
| P0 | Windows native tests | Prior evidence showed the missing Qt platform-plugin path causing two Qt test timeouts and the lifecycle timeout. The corrected tree is published, but Windows run `33333139201` must finish and its exact evidence must be retrieved before acceptance. |
| P0 | macOS matrix | Prior evidence showed deferred Draft callbacks accessing deleted wrappers during both GUI suites. The corrected tree is published, but both architectures in macOS run `33333139229` must finish and their exact evidence must be retrieved before acceptance. |
| P0 | Dependency Review | Security run `33333139224` is active. Dependency Review remains expected to fail closed while the repository Dependency Graph is disabled; CodeQL is not a replacement, and no conclusion is claimed before the run is terminal. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | The staged, unpublished legal candidate removes the 32 restricted patterns and inherited thumbnail DLL from tracked source and recognized manifests. Published integration still contains them, and provenance, cleared replacements, complete notices, source-archive inspection, staging inspection, and final package-payload inspection remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Retrieve Linux run `33333139217`, Windows run `33333139201`, Security run `33333139224`, and both architectures from macOS run `33333139229` at published head `fa0f3b6d3e9d8437db8a403a25d4bbfb2ba63720`.
2. Record every terminal job result, exact failed step, log, and artifact; do not summarize a queued, running, cancelled, or skipped gate as passed.
3. Fix root causes and repeat the complete affected native matrix without weakening any gate; keep PR #28 draft.
4. Document the disabled Dependency Graph as the exact external setting blocker if Dependency Review again fails closed; do not substitute CodeQL.
5. After the reproducible native baseline is green, independently review and publish the staged legal quarantine candidate, then run its security and artifact-level gates.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
