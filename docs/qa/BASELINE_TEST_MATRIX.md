# Baseline test matrix

This document records the test infrastructure present in the pinned FreeCAD
source tree and defines the first OpenFusion regression and acceptance gates.
It is an inspection report and execution plan, not a test-results report.

No configure, compile, test, GUI-launch, installation, or package-validation
step was executed during this inspection. A status of **Not run** or
**Blocked** must not be interpreted as a pass.

## Immutable source baseline

| Field | Verified value |
|---|---|
| Upstream project | FreeCAD |
| Upstream repository | <https://github.com/FreeCAD/FreeCAD.git> |
| Release/tag | `1.1.3` |
| Full commit | `145529fe741292ff0b3977a01195bf0247425794` |
| Inspection platform | Ubuntu 24.04.3 LTS, Linux x86-64 |
| Inspection date | 2026-08-29 UTC |

The full commit hash, not the tag name alone, is the trust anchor. A future
baseline update must record both the old and new hashes and repeat every gate
in this document.

### Submodule state observed during inspection

The leading `-` reported by `git submodule status` means the submodule was not
initialized in the inspected checkout.

| Path | Pinned commit | State |
|---|---|---|
| `src/3rdParty/GSL` | `543d0dd3fe966ddf20e884b44e5fdbf12cb43784` | Blocked: not initialized |
| `src/3rdParty/OndselSolver` | `30e9b64e8bf881d438d4b88834f9ba3674865418` | Blocked: not initialized |
| `src/Mod/AddonManager` | `937b6877239dc78ef59eeefe8099e5f14243eda1` | Blocked: not initialized |
| `tests/lib` | `f8d7d77c06936315286eb55f8de22cd23c188571` | Blocked: not initialized |

`tests/lib` contains the bundled GoogleTest/GoogleMock source used when
`FREECAD_USE_EXTERNAL_GTEST` is disabled. Developer-test configuration cannot
succeed without either that submodule or an explicitly configured compatible
external GoogleTest installation.

## Inspection environment and execution status

| Item or gate | Observed state | Status | Evidence required to change status |
|---|---|---:|---|
| GCC | GCC/G++ 13.3.0 present | Inspected | Tool output captured during inspection |
| GNU Make | 4.3 present | Inspected | Tool output captured during inspection |
| CMake / CTest | Not installed | Blocked | Version output and successful configure |
| Ninja | Not installed | Blocked | Version output and successful generation |
| Pixi | Not installed | Blocked | Locked environment installation log |
| Xvfb | Not installed | Blocked | GUI-test launch log |
| `FreeCAD` / `FreeCADCmd` | No built or installed binary present | Blocked | Version output from built and installed trees |
| Submodule initialization | Four required submodules absent | Blocked | Clean `git submodule status` without leading `-` |
| Release configure | Not attempted | Not run | Complete CMake configure log and cache |
| Release compile | Not attempted | Not run | Successful build log |
| Debug configure/compile | Not attempted | Not run | Successful configure and build logs |
| C++/Qt tests | Not attempted | Not run | CTest inventory and result log |
| Python CLI tests | Not attempted | Not run | `FreeCADCmd -t 0` log and exit code |
| Python GUI tests | Not attempted | Not run | `FreeCAD -t 0` log and exit code under a display |
| Installed-tree tests | Not attempted | Not run | Installed binary version and test logs |
| Manual launch/workflow | Not attempted | Not run | Recorded interaction checklist |
| Linux packages | Not produced or tested | Not run | Clean-environment install and acceptance logs |
| Windows build/package | Not attempted | Not run | Native Windows build and installer evidence |
| macOS build/package | Not attempted | Not run | Native macOS build and application/DMG evidence |

## Reproducible baseline procedure

The upstream Pixi lock file and CMake presets are the preferred cross-platform
baseline. Run from the repository root in a clean checkout.

### Locked Pixi build

```bash
git submodule update --init --recursive
pixi install --locked
pixi run initialize
pixi run configure-release
pixi run build-release
```

The `conda-*-release` presets enable `ENABLE_DEVELOPER_TESTS`. Keep
`BUILD_TEST=ON`, `BUILD_GUI=ON`, `BUILD_ASSEMBLY=ON`, `BUILD_CAM=ON`, and
`BUILD_TECHDRAW=ON`; record the generated `CMakeCache.txt` so the enabled
module set is auditable.

### Native CMake comparison build

This path is useful for diagnosing a Pixi-specific failure. It is not a
substitute for the locked build.

```bash
cmake -S . -B build/baseline-release -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TEST=ON \
  -DENABLE_DEVELOPER_TESTS=ON \
  -DBUILD_GUI=ON \
  -DBUILD_ASSEMBLY=ON \
  -DBUILD_CAM=ON \
  -DBUILD_TECHDRAW=ON

cmake --build build/baseline-release --parallel
```

### Inventory before execution

Capture the binary configuration and discovered test inventory before running
the suites. Unexpected reductions in test count must fail CI.

```bash
build/release/bin/FreeCADCmd --version --verbose
build/release/bin/FreeCADCmd --dump-config
build/release/bin/FreeCADCmd --safe-mode -t
pixi run ctest --test-dir build/release --show-only=json-v1
```

### C++ and Qt tests

`tests/CMakeLists.txt` registers GoogleTest cases with CTest. Running CTest is
the source of truth; hand-maintained lists of executables can silently omit or
misroute suites. The complete Linux run should use a display because the
`QuantitySpinBox_Tests_run` and `DlgVersionMigrator_Tests_run` Qt tests create
a `QApplication`.

```bash
env LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb LC_ALL=C.UTF-8 TZ=UTC \
  pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  ctest --test-dir build/release \
    --output-on-failure --no-tests=error --parallel 2
```

Useful focused executables include:

```bash
pixi run build/release/tests/App_tests_run
pixi run build/release/tests/Base_tests_run
pixi run build/release/tests/Sketcher_tests_run
pixi run build/release/tests/PartDesign_tests_run
pixi run build/release/tests/Assembly_tests_run
pixi run build/release/tests/TechDraw_tests_run
pixi run build/release/tests/Mesh_tests_run
pixi run build/release/tests/MeshPart_tests_run
pixi run build/release/tests/Zipios_tests_run
```

The executables accept `--gtest_list_tests`, `--gtest_filter=...`, and
`--gtest_output=json:<path>`.

Focused persistence and compatibility filters are:

```bash
build/release/tests/Base_tests_run \
  --gtest_filter='ReaderTest.*:WriterTest.*'

build/release/tests/App_tests_run \
  --gtest_filter='ProjectFileTest.*:BackupPolicyTest.*:DocumentTest.*'

build/release/tests/Sketcher_tests_run \
  --gtest_filter='ConstraintPointsAccess.*'

build/release/tests/PartDesign_tests_run \
  --gtest_filter='BackwardCompatibilityTest.*'
```

### Python CLI tests

`FreeCADCmd -t` lists registered units, `-t 0` runs all registered units, and
`-t module.class.method` runs a focused unittest. `src/App/FreeCADTest.py`
returns a process exit status based on `unittest` success.

Use a new profile directory for every invocation because existing suites
modify preferences and sometimes use fixed temporary filenames.

```bash
baseline_profile="$(mktemp -d)"

build/release/bin/FreeCADCmd \
  --safe-mode \
  --user-cfg "$baseline_profile/user.cfg" \
  --system-cfg "$baseline_profile/system.cfg" \
  --log-file "$baseline_profile/freecad-cli.log" \
  -t 0
```

Critical focused CLI suites are:

```bash
build/release/bin/FreeCADCmd --safe-mode -t Document
build/release/bin/FreeCADCmd --safe-mode -t UnicodeTests
build/release/bin/FreeCADCmd --safe-mode -t TestSketcherApp
build/release/bin/FreeCADCmd --safe-mode -t TestPartDesignApp
build/release/bin/FreeCADCmd --safe-mode -t TestAssemblyWorkbench
build/release/bin/FreeCADCmd --safe-mode -t TestTechDrawApp
build/release/bin/FreeCADCmd --safe-mode -t TestCAMApp
build/release/bin/FreeCADCmd --safe-mode -t MeshTestsApp
build/release/bin/FreeCADCmd --safe-mode -t TestDraft
```

### Python GUI tests

Use the GUI binary, not `FreeCADCmd`. Running all registered tests with the GUI
initialized catches GUI-dependent branches hidden inside App-named suites.

```bash
gui_profile="$(mktemp -d)"

env LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb LC_ALL=C.UTF-8 TZ=UTC \
  pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  build/release/bin/FreeCAD \
    --safe-mode \
    --user-cfg "$gui_profile/user.cfg" \
    --system-cfg "$gui_profile/system.cfg" \
    --log-file "$gui_profile/freecad-gui.log" \
    -t 0
```

If runtime requires suites to be split, use an explicit reviewed manifest that
includes at least:

```text
Workbench
Menu
GuiDocument
TestSketcherApp
TestPartDesignGui
TestAssemblyWorkbench
TestTechDrawGui
TestCAMGui
TestImportGui
```

Do not infer GUI coverage only from names containing `Gui`.
`TestSketcherApp` conditionally loads GUI placement tests, and
`TestAssemblyWorkbench` contains a GUI class skipped by `FreeCADCmd`.

### Installed-tree repetition

A build-tree pass can conceal missing resources or incorrect runtime paths.
Repeat CTest where applicable and the CLI/GUI suite against the installed
tree.

```bash
pixi run install-release
pixi run FreeCADCmd --safe-mode -t 0
env LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb \
  pixi run xvfb-run -a -s "-screen 0 1920x1080x24" \
  FreeCAD --safe-mode -t 0
```

The executable names remain the upstream names until the identity migration
is implemented and verified. These commands do not constitute OpenFusion
package validation.

## Existing source-level coverage matrix

The entries below describe code and registered tests found by inspection.
They do not assert that the tests currently pass.

| Area | Existing entry points | Coverage found | Material gap |
|---|---|---|---|
| CLI/core | `BaseTests`, `UnitTests`, `Document`, `Metadata`, `UnicodeTests`; `App_tests_run`, `Base_tests_run`, `Misc_tests_run`, `Zipios_tests_run` | Documents, properties, transactions, persistence, reader/writer and backup policy | No OpenFusion product workflow or installed-package acceptance |
| GUI/core | `Workbench`, `Menu`, `GuiDocument`; `Gui_tests_run` and standalone Qt tests | Core commands, menus and GUI document behavior | No coherent workspace, project-browser, timeline, command-search or keyboard-flow acceptance |
| Serialization | `Document`, `UnicodeTests`; App/Base/Zipios C++ tests | FCStd save/restore, Unicode, property persistence, archive handling, undo/redo primitives | No complete parametric model save/reopen/edit/recompute workflow across supported versions and paths |
| Sketcher | `TestSketcherApp`, `TestSketcherGui`, `Sketcher_tests_run` | Solver, fillet, expressions, validation, carbon copy and constraint serialization | Registered `TestSketcherGui.py` is effectively empty; no end-user geometry/constraint interaction or solver-status acceptance |
| Part Design | `TestPartDesignApp`, `TestPartDesignGui`, `PartDesign_tests_run` | Pad, pocket, hole, revolution, pipe, loft, patterns, booleans, dress-ups, topological naming and older model fixtures | No single early-feature-edit workflow proving downstream recompute, timeline and undo/redo coherence |
| Assembly | `TestAssemblyWorkbench`, `Assembly_tests_run` | Basic assembly/joint-group creation, grounding, placement and one solve scenario | C++ suite contains one object-construction test; no persisted multi-component joint/motion/undo workflow |
| TechDraw | `TestTechDrawApp`, `TestTechDrawGui`, `TechDraw_tests_run` | Basic views, projection group, hatch, annotation, symbols, sections, detail and dimension objects | C++ suite has only two line-format tests; no drawing-to-PDF/DXF acceptance; GUI tests use fixed waits |
| CAM | `TestCAMApp`, `TestCAMGui` | Broad Path/CAM core, operations, tool assets/libraries, posts and GUI widgets | No C++ suite or complete setup-to-simulation/post/package acceptance; `TestPathDressupArray.py` is not registered |
| Import | `TestImportGui` | One GUI STEP export/import test preserving per-face colors | No CLI STEP matrix, representative imported models, assembly hierarchy validation or format-wide roundtrip |
| Mesh | `MeshTestsApp`, `Mesh_tests_run`, `MeshPart_tests_run` | Mesh algorithms, STL write/reload, OBJ and 3MF import | No clean 3D-print workflow or Part Design to mesh export/reimport acceptance |
| Draft formats | `TestDraft` | Real DXF import regression for `Issue24314.dxf` | DXF export test calls a fake function and automatically passes; SVG suite is not registered and its import/export tests are placeholders |

## Interoperability coverage matrix

“No dedicated test found” means no meaningful roundtrip test was identified in
the inspected registered suites and C++ test entry points.

| Format | Existing automated evidence | Required OpenFusion addition |
|---|---|---|
| FCStd | Core document, Unicode and some module save/reopen tests | Full acceptance model, old-version fixtures, early edit, recompute, undo/redo, Unicode/space/long-path cases |
| STEP | One GUI color-per-face export/import test | Representative solids and assemblies; import, edit, save, reopen, export, reimport and semantic comparison |
| IGES | No dedicated roundtrip test found | Solid/surface import and export matrix with validity and tolerance checks |
| STL | C++ mesh exporter writes and reloads meshes | Part Design export, mesh validation, reopen and 3D-print workflow |
| OBJ | C++ importer fixture | Export/reimport, groups/material behavior and geometry checks |
| DXF | One real import regression | Real sketch/drawing export and independent parse/reimport validation |
| SVG | Registered aggregate excludes the SVG suite; import/export methods are placeholder passes | Real drawing/sketch export, parse/reimport and rendering checks |
| PDF | No dedicated export test found | TechDraw PDF generation, page-size/content checks and clean-package execution |
| 3MF | C++ import fixture | Export/reimport, units, components and mesh validity |
| glTF | No dedicated roundtrip test found | Export/reimport or independent parser validation where the build enables support |
| BREP | BREP algorithm fixtures and Part tests exist | Dedicated model export/reimport and topology/geometry comparison |

Representative existing fixtures include:

- `src/Mod/Sketcher/SketcherTests/TestSketchCarbonCopyReverseMapping.FCStd`
- `tests/src/Mod/PartDesign/App/TestModels/*.FCStd`
- `src/Mod/PartDesign/PartDesignTests/Fixtures/*.FCStd`
- `src/Mod/Part/parttests/TestTangentMode3-0.21.FCStd`
- `tests/src/Mod/Part/App/brepfiles/*.brep`
- `src/Mod/CAM/CAMTests/*.fcstd` and `src/Mod/CAM/CAMTests/Tools/`
- `src/Mod/TechDraw/TDTest/TestTemplate.svg` and associated image/symbol fixtures
- `data/tests/mesh.3mf`, `data/tests/mesh.obj`, and `data/tests/Step/`
- `src/Mod/Draft/drafttests/Issue24314.dxf`

Fixtures promoted into OpenFusion acceptance tests must have documented
provenance and licensing.

## Headless and platform constraints

- `FreeCADCmd` is suitable for App-level tests, but it cannot prove view
  providers, viewport rendering, focus, mouse/keyboard interaction, modal
  dialogs, or other QApplication behavior.
- Linux GUI tests should use `FreeCAD`, Xvfb, a 24-bit screen, the XCB Qt
  backend, and Mesa software rendering. `QT_QPA_PLATFORM=offscreen` is not a
  dependable replacement for X11/GLX in Coin3D/OpenGL tests.
- Existing tests mutate preferences and sometimes use fixed names in the
  system temporary directory. Use a fresh config and artifact directory for
  each process, and do not parallelize the Python suites until collisions are
  audited and removed.
- Fix locale, timezone, fonts, theme, screen size, device-pixel ratio, camera,
  and renderer for visual baselines. Mask known nondeterministic regions and
  use tolerances.
- Xvfb validates Linux headless behavior only. It does not prove GPU-driver
  compatibility, Wayland behavior, native Windows/macOS input, or package
  integration.
- `QT_SCALE_FACTOR` runs can detect some scaling defects but do not replace
  native 100%, 125%, 150%, 175%, and 200% display checks.
- Visual comparison supplements, and never replaces, geometry, persistence,
  recompute and undo/redo assertions.

## Existing CI gaps requiring correction

These are source-inspection findings, not CI execution results.

1. `.github/workflows/CI_master.yml` invokes `sub_buildPixi.yml` without
   `testOnBuildDir`; its default is `false`, so build-tree Python CLI and GUI
   tests do not run in that path.
2. Installed-tree GUI testing in `sub_buildPixi.yml` is hard-disabled with
   `if: false` and documented as broken for the Qt 6 build.
3. The Pixi workflow omits C++ tests on Windows.
4. `.github/scripts/run_gui_tests.py` filters registered suite names by the
   substring `Gui`, missing GUI-dependent branches in App-named suites, and
   returns success when it discovers no tests.
5. `.github/workflows/actions/runCPPTests/runAllTests/action.yml` routes three
   entries to the wrong binaries: Measure runs Material, MeshPart runs Mesh,
   and Spreadsheet runs Sketcher.
6. The same custom C++ action omits TechDraw, Zipios and standalone Qt tests.
   Use CTest discovery instead of duplicating its inventory.
7. Current bundle scripts only run `freecadcmd --safe-mode --version` as a
   smoke test. They do not install, launch the GUI, model, persist, export, or
   uninstall.

## Proposed OpenFusion acceptance harness

Place the initial suite under `tests/openfusion/acceptance/` and make it
runnable against both the build tree and installed application. During the
identity migration the invocation can use the upstream executable name:

```bash
FreeCADCmd \
  --python-path tests/openfusion/acceptance \
  -t TestOpenFusionAcceptance
```

After the executable migration, run the identical tests through
`OpenFusionCmd`. Register every test process with CTest and make zero-test
discovery, a reduced inventory, an unexpected skip, and a nonzero exit status
hard failures.

### Acceptance cases

| ID | Workflow | Minimum assertions |
|---|---|---|
| OF-ACC-001 | Core parametric model | New document/component/body; XY rectangle with zero remaining DOF; pad/extrude; second sketch; hole; fillet; pattern; valid final solid |
| OF-ACC-002 | Early feature edit | Change an early sketch dimension; recompute; downstream shape, volume or bounds change predictably; no invalid features or broken dependencies |
| OF-ACC-003 | Undo/redo | Every modeling action is transactional; undo and redo restore geometry, tree, active component and timeline state |
| OF-ACC-004 | Persistence | Save, close and reopen FCStd; verify namespaced metadata, links, expressions, constraints, feature order and geometry on Unicode/space/long paths |
| OF-ACC-005 | Assembly | Add a second component, ground one component, create a supported joint, solve, save/reopen and verify placements |
| OF-ACC-006 | Drawing | Create a page, base/projected view and dimension; recompute; export a real PDF and supported vector format |
| OF-ACC-007 | Manufacturing | Create setup, stock, WCS, tool/controller and representative operation; calculate and post; validate nonempty path/G-code without claiming unavailable strategies |
| OF-ACC-008 | Interoperability | Export/reimport every enabled required format; independently or semantically validate solids, meshes, units, bounds and metadata |
| OF-ACC-009 | GUI workflow | Use Qt test input on real actions/widgets for workspace, command search, tree/viewport synchronization, timeline edit, shortcuts, focus and cancellation |
| OF-ACC-010 | Recovery | Exercise autosave and abnormal child-process termination with a disposable profile; verify discoverable recovery without corrupting the original |
| OF-ACC-011 | Package | From final artifact bytes: clean install/extract, launch, execute core acceptance, save/reopen, STEP/STL export and uninstall where applicable |

Geometry assertions should use semantic tolerances: shape validity, solid and
shell counts, volume, area, bounding box, feature state, dependency order,
mesh facet count and manifold/orientation checks. Do not compare FCStd, STEP,
mesh exports or screenshots byte-for-byte when their serialization contains
nondeterministic ordering or metadata.

GUI acceptance must use actual Qt input and observable widget/application
state. Calling `FreeCADGui.runCommand()` alone does not prove keyboard, mouse,
focus, menus, task panels, dialogs or accessibility.

### Execution lanes

| Lane | Required scope | Frequency |
|---|---|---|
| Pull request | Affected C++ tests, critical CLI suites, serialization checks and OF-ACC-001 through OF-ACC-004 | Every change |
| Nightly | Full CTest, complete CLI/GUI inventory, interoperability matrix, recovery and visual regression | Daily |
| Performance | Startup, file load, recompute, selection, viewport and memory benchmarks on versioned representative documents | Scheduled and before performance-sensitive merges |
| Release candidate | Debug and Release; installed/package acceptance on native Linux, Windows and macOS; manual GPU/HiDPI/input checks | Every release candidate |

## Baseline evidence and change policy

For each completed run, retain a machine-readable manifest containing:

- source commit and every submodule commit;
- `pixi.lock` hash and complete CMake cache;
- OS image, architecture, compiler, CMake, Qt, PySide, OCCT and Python versions;
- exact commands, environment overrides and test inventory;
- start/end time, duration, exit code, pass/fail/error/skip counts and failing
  test names;
- logs, crash dumps and generated acceptance artifacts;
- classification of every failure as OpenFusion regression, upstream FreeCAD
  bug, dependency issue, platform issue or unsupported functionality.

Commit a concise baseline summary and retain raw logs as CI artifacts. Do not
convert an incomplete run, zero-test discovery, timeout, unexpected skip, or
known upstream failure into a pass. A pre-existing upstream defect may be
classified separately, but crashes, corruption and broken core undo/redo
remain release blockers.
