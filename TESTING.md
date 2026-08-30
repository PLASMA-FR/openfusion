# Testing OpenFusion

## Verified local integration evidence (2026-08-30)

The tables below record completed local logs only. They do not replace remote
PR checks or clean-installed package tests.

### Environment

| Field | Value |
|---|---|
| Remote commit | `51ae387b9ff3c0d1f3c894adb897717664967974` |
| Local tested implementation head | `2f7fa2c8e940759d07698442054af0d12f222125`; committed locally, awaiting publication, and not remote CI evidence |
| Host | Ubuntu 24.04 arm64; Neoverse-N1; 2 CPUs; 12,506,804,224 bytes RAM |
| Environment | Pixi 0.59.0; `pixi.lock` SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |
| Toolchain | Clang 21.1.0; CMake 4.2.1; Ninja 1.13.2; Python 3.11.14; Qt 6.8.3 |

### Baseline reproduction before the fixes

| Gate | Result | Time / detail |
|---|---|---|
| Release build | 6,744/6,744 steps | Passed |
| CTest discovery | 1,428 total; 1,422 enabled | Six disabled |
| CTest execution | Two FileInfo race failures; three skipped; all three acceptance tests passed | 79.22 s |
| Serial FileInfo confirmation | 14/14 passed | Confirmed a cross-process fixture race rather than a deterministic functional failure |
| Unicode mirror GUI regression | 0/1 passed; exact process exit 1 | Reproduced the Latin-1 generated-command defect |

### Published integration implementation, tested locally

| Gate | Result | Time / detail |
|---|---|---|
| Incremental Release build | 634/634 steps | Passed |
| CTest discovery | 1,429 total; 1,423 enabled | Six disabled |
| CTest execution | Zero failures; three skipped; all four acceptance tests passed | 80.86 s |
| SystemExit focus | 1/1 passed | 3.39 s; preserved exact code 7 and ran cleanup |
| Unicode mirror focus | 1/1 passed | 0.563 s |
| FileInfo stress | 2,000 targeted invocations and 1,400 full-fixture repetitions passed | Process-unique fixture isolation |
| Windows runtime helper unit tests | 5/5 passed | Local helper coverage only; native Windows execution pending |
| TechDraw GUI export | 1/1 passed | 2.54 s; SVG 13,163 bytes; PDF 298,780 bytes |
| CLI Python suite | 1,661 ran; 10 skipped; zero failures | 156.014 s |
| GUI Python suite | 1,759 passed | 424 s |

### Committed local next head awaiting publication

| Gate | Result | Time / detail |
|---|---|---|
| Incremental Release build | 324 edges, then a four-edge follow-up | Both passed |
| Unittest summary parser | 9/9 passed | Accepts finite integer, decimal, and scientific durations while rejecting malformed summaries |
| SystemExit classifier and FileInfo focus | 4/4 classifier cases plus 2/2 targeted FileInfo cases passed | FileInfo always executes WriteOnly and documents/asserts the Windows readable-and-writable projection without a skip or DACL change |
| Qt callback tests | 2/2 passed | Callback-boundary containment |
| GUI lifecycle CTest | 1/1 passed | Three scenarios preserve exact codes 0, 1, and 7 and execute cleanup; final review's timeout-budget finding was addressed by increasing the timeout from 240 to 330 seconds |
| TechDraw GUI export | 1/1 passed; process exit 0 | 2.55 s; SVG 13,163 bytes; PDF 298,780 bytes |
| Full CTest | 1,433 registered; 1,427 enabled; zero failed; three skipped; six disabled | 90.11 s |
| CLI Python suite | 1,661 ran; 10 skipped; zero failures; parser count 1,661 | 153.353 s |
| GUI Python suite | Faithful safe-mode run: 1,759 passed; zero failures; process exit 0; parser count 1,759 | `4.2e+02s` |

An earlier hidden-mode diagnostic run was invalid and interrupted. It is not a
product pass or failure and is not included above.

### Terminal draft PR #28 evidence at remote head

All four workflow runs are terminal at
`51ae387b9ff3c0d1f3c894adb897717664967974`. All retained artifacts expire on
2026-09-29.

| Platform / run | Result | Retained artifacts |
|---|---|---|
| Security `33302508107` | Failed solely because Dependency Review was fail-closed with the repository Dependency Graph disabled; all three CodeQL jobs passed. | None |
| Linux `33302508115` | GUI reported 1,759 tests and `OK`; the workflow failed because its decimal-only parser rejected the scientific-notation duration. | Baseline `9730899331`, 6,858,545 bytes, SHA-256 `b31ee677c4cdda2780757462a65bf2da88fd4be7f485536ab844fbd02e05746d`; TechDraw `9730823771`, 603,842 bytes, SHA-256 `f5c20186b09e4f04ab805e7aaa86ea96f82cc9ad9ba8cab30ae45c75595592b5` |
| Windows `33302508110` | Failed. Materials passed 35/35 after runtime bootstrapping. FileInfo had two assertion failures; QuantitySpinBox and DlgVersionMigrator each timed out at 600 s; lifecycle timed out at 90 s. | `9731537416`, 718,526 bytes, SHA-256 `055c10d61f99453da677eac40f247456c65dd01e509c187d9d1692a6de727b58` |
| macOS arm64 `33302508113` | Failed: uncaught `Base::SystemExitException`, process -6 instead of the requested code, and incomplete lifecycle cleanup. | `9730507223`, 534,321 bytes, SHA-256 `b2310d67d570bacb3dada5a4bf9c9c22113c3ef3b8ee3d7845a06547a37164bc` |
| macOS x86_64 `33302508113` | GUI reported 1,759 tests and `OK`, but the process exited 1. | Baseline `9731697288`, 6,850,827 bytes, SHA-256 `fcf219297fc674ff4caa8d272f01fdd5df7c98a3be4eab3a978becdcbf7754c5`; TechDraw `9731523318`, 597,342 bytes, SHA-256 `b157fdb0172d41d1354b89d7515b5ac6a7f4b44e97a6f2bb68b87878ebed9011` |

Committed local head `2f7fa2c8e940759d07698442054af0d12f222125`
addresses the observed Qt callback, scientific-summary, Windows FileInfo, and
offscreen failures, but it is not published. Native reruns remain mandatory.

OpenFusion treats geometry correctness, document compatibility, undo/redo, and installability as release gates. Compilation alone is not acceptance evidence.

## Upstream regression suites

After configuring a release build:

```bash
ctest --test-dir build/release --output-on-failure
build/release/bin/FreeCADCmd -t 0
xvfb-run build/release/bin/FreeCAD -t 0
```

With the locked Pixi environment:

```bash
pixi run test-release
pixi run build/release/bin/FreeCADCmd -t 0
pixi run xvfb-run build/release/bin/FreeCAD -t 0
```

The installed tree is tested again. Passing only in the build directory can conceal missing files or incorrect runtime paths.

## Focused module suites

The upstream Python runner accepts suite names. Important baseline suites include:

```bash
build/release/bin/FreeCADCmd -t TestSketcherApp
build/release/bin/FreeCADCmd -t TestPartDesignApp
build/release/bin/FreeCADCmd -t TestAssemblyWorkbench
build/release/bin/FreeCADCmd -t TestTechDrawApp
build/release/bin/FreeCADCmd -t TestCAMApp
build/release/bin/FreeCADCmd -t TestMaterialsApp
```

GUI suites run with the GUI binary and a real or virtual display. A virtual display proves basic headless behavior, not GPU-driver quality or complete interaction fidelity.

## OpenFusion acceptance workflow

The release acceptance project must exercise, with real commands and persisted objects:

1. create a document and root component/body;
2. create and fully constrain a rectangular sketch;
3. pad/extrude it;
4. create a second sketch and hole;
5. fillet and pattern geometry;
6. create another component and a supported assembly relationship;
7. save, close, and reopen;
8. edit an early feature and recompute downstream features;
9. undo and redo each core modeling operation;
10. create a drawing;
11. export STEP and STL;
12. reopen or independently validate the exports.

The executable acceptance project is registered from `tests/acceptance/`.
`OpenFusion_Core_Acceptance` creates two real Part Design bodies, fully
constrained sketches, a pad, through hole, fillet, and linear pattern;
saves/reopens FCStd; edits an early named dimension; verifies downstream
recompute plus undo/redo; and exports and reimports spatially distinct solids
through STEP and STL.

Two fixture-dependent slices extend that model:

- `OpenFusion_Assembly_Acceptance` creates linked component occurrences, a
  grounded occurrence, and a fixed joint; perturbs the moving occurrence;
  requires the real solver to restore it; and repeats the proof after
  save/reopen.
- `OpenFusion_TechDraw_Acceptance` creates a real A4 drawing and projected
  view, verifies finite geometry and SVG output, edits the early sketch width,
  proves drawing propagation through undo/redo, and repeats the checks after
  save/reopen.

Run it directly after a configured build:

```bash
ctest --test-dir build/release \
  -R '^OpenFusion_(Core|Assembly|TechDraw)_Acceptance$' \
  --output-on-failure \
  --no-tests=error
```

The platform GUI workflows then open the persisted TechDraw fixture with the
real desktop executable and export full-page SVG and PDF files. The validator
parses SVG structure, rasterizes PDF through the locked PDFium binding, checks
page size, metadata, contrast, and projected geometry, and repeats both export
formats with a non-ASCII filename. A successful headless export alone does not
satisfy this GUI gate.

The generated FCStd, STEP, STL, TechDraw SVG, application logs, and isolated
configuration remain under
`build/release/Testing/OpenFusionAcceptance/` for diagnostics. The headless
TechDraw slice does not claim GUI PDF-export coverage, and none of these source
tests substitutes for installed-package acceptance. A missing or unsupported
release step is recorded as a release-blocking gap and is never replaced with
mock data.

## Package smoke tests

Every final artifact is tested from its packaged bytes, not merely from its staging directory. Each platform test must install or extract into a clean environment, launch, execute the core acceptance model, save/reopen, export, and uninstall where applicable.

## Manual coverage

Automated GUI tests are supplemented by manual checks for:

- X11 and Wayland where supported;
- Windows and macOS native input conventions;
- 100%, 125%, 150%, 175%, and 200% scaling;
- viewport navigation and selection on representative GPUs;
- large models, dense sketches, assemblies, drawings, and CAM jobs;
- crash recovery and autosave behavior.

## Reporting results

Record exact revision, dependency lock hash, OS image, compiler, configuration, test command, duration, and failing test names. Do not summarize a partially executed suite as passed.
