# Testing OpenFusion

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

The initial harness is tracked under `tests/openfusion/`. A missing or unsupported step is recorded as a release-blocking gap; it is never replaced with mock data.

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
