# OpenFusion Execution State

**Last verified:** 2026-08-30 UTC
**Production-ready:** No
**Active milestone:** M0, reproducible upstream baseline
**Next task:** Push the local integration head, re-fetch draft PR #28, run the
full cross-platform matrix, and retrieve every conclusion, log, and artifact.
Do not advance the milestone until it is green or a precise external blocker is
recorded.

This file records resumable execution truth. A local pass is not a remote CI
pass, an inherited FreeCAD feature is not an OpenFusion product feature, and a
built artifact is not a tested package.

## Source state

| Item | Verified value |
|---|---|
| FreeCAD foundation | 1.1.3, commit `145529fe741292ff0b3977a01195bf0247425794` |
| Tested implementation head | `403e72f24303ab6d7a91d29a35648ef2f0d2cc05` |
| Remote integration head | `1a27d1f46030c9e42aff67bc1d90cb5c6114ea03` |
| Active integration PR | Draft PR #28, `integration/acceptance-ci`; old red runs remain current until push and re-fetch |
| Dependency lock | `pixi.lock`, SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |

### Five local commits not yet reflected by PR #28

| Commit | Change |
|---|---|
| `598c653f6cbb0e03bf23c832293f264df2900777` | `fix(part): pass mirror commands to Python as UTF-8` |
| `e0cfba726feeec2784d6390501740fb17a253d2e` | `test(base): isolate FileInfo fixtures across processes` |
| `02bfcfb403829eeeea4ae49d407b434041242557` | `fix(test): bootstrap Windows native runtime paths` |
| `06b547f6dcaefc11ac58b9acceb45ef153cdf628` | `fix(gui): preserve event-loop exit codes and cleanup` |
| `403e72f24303ab6d7a91d29a35648ef2f0d2cc05` | `ci(windows): verify native CTest runtime discovery` |

Handoff branches and draft PR #30 are review inputs, not accepted evidence at
this local head. Re-fetch their refs and checks before any merge decision. Do
not infer that the UTF-8, SystemExit, or Windows helper fixes passed their
native operating systems from the local Linux results.

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

### Fixed local head

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

## Active blockers

| Priority | Blocker | Current truth |
|---|---|---|
| P0 | Remote integration evidence | PR #28 is still at the old head with old red runs. None of the local results are GitHub Actions evidence yet. |
| P0 | Windows native tests | Runtime-path logic has local unit coverage only. Real Windows discovery and execution, including Materials, are pending. |
| P0 | macOS matrix | macOS x86_64 UTF-8 and macOS arm64 exit-propagation reruns are pending. |
| P0 | Dependency Review | Last CodeQL jobs were green, but Dependency Review is fail-closed while the repository Dependency Graph is disabled. CodeQL is not a replacement. |
| P0 | Untrusted input | Audit evidence found PR #27's symlink graph escape; the stale DTD-only stack is insufficient. Release-blocker issue #24 remains unresolved. |
| P0 | Legal / provenance | Restricted material-pattern assets, inherited identity/provenance gaps, and a prebuilt Windows thumbnail DLL remain unresolved. The legal audit is NO-GO. |
| P0 | Packaging | No required package has passed clean install, acceptance, upgrade/uninstall, checksum, SBOM, or downloaded-release verification. |
| P1 | Product architecture | No OpenFusion product classes exist under `src/`. The workspace shell, selector, command palette, context surface, Project presentation, and functional graph-backed timeline are not implemented. |

## Resume sequence

1. Push the five implementation commits and this documentation update to `integration/acceptance-ci` without force-pushing or rewriting shared history.
2. Re-fetch the branch and draft PR #28; record the exact published SHA and verify that tested implementation head `403e72f24303ab6d7a91d29a35648ef2f0d2cc05` is its ancestor.
3. Run the complete Linux, Windows, macOS arm64, and macOS x86_64 matrix.
4. Retrieve every job result, exact failed step, log, and artifact; do not summarize a queued or skipped gate as passed.
5. Fix root causes and repeat until green, or document the exact external setting blocker.
6. Only then select the next roadmap slice. Highest priority remains safety, correctness, and baseline integrity before UI work.

## Commit update rule

After each substantial verified iteration, replace stale state here with the
new head SHA, commands, totals, failures, skips, platform, toolchain, blockers,
and next task. Commit and publish that update with the coherent change so the
next agent does not need conversation memory.
