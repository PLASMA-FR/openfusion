# OpenFusion Engineering Roadmap

OpenFusion is an incremental, compatibility-conscious transformation of FreeCAD into a coherent professional CAD application. The repository currently contains the FreeCAD 1.1.3 source foundation at commit `145529fe741292ff0b3977a01195bf0247425794`. OpenFusion-specific product work has not yet passed a production release gate.

This roadmap is gate-driven. A milestone is complete only when its exit evidence is committed or linked from the repository. A build artifact, screenshot, or UI control is not evidence that its underlying workflow works.

## Current status

- Foundation: FreeCAD 1.1.3 source is present and the `upstream` remote is configured read-only.
- Active milestone: M0 — reproducible upstream baseline.
- OpenFusion workspace shell: designed, not implemented.
- OpenFusion release artifacts: not produced.
- Production readiness: **not achieved**.
- Supported-platform claims: none until clean-machine package tests pass.

## Status and priority vocabulary

| Term | Meaning |
|---|---|
| Not started | No OpenFusion implementation or accepted evidence exists. |
| In progress | Work exists, but the milestone exit gate is not satisfied. |
| Gate passed | Required code, tests, results, and documentation are present. |
| Blocked | Progress requires an identified dependency, credential, or platform resource. |
| P0 | Release-blocking correctness, data safety, build, or security work. |
| P1 | Core professional workflow or architecture work. |
| P2 | Important capability, performance, consistency, or usability work. |
| P3 | Polish or convenience work that must not displace higher priorities. |

## Non-negotiable engineering rules

1. Preserve FCStd compatibility unless a reviewed, versioned, namespaced extension is unavoidable.
2. Route document mutations through existing tested commands or explicit undo transactions.
3. Keep visible production actions functional; unavailable work remains hidden or clearly experimental.
4. Preserve legacy command, dock, workbench, Python, and addon identifiers until a compatibility plan exists.
5. Do not copy Autodesk code, artwork, icons, binaries, branding, or protected resources.
6. Do not claim a platform, format, feature, or package as supported without recorded verification.
7. Keep the branch buildable with focused commits and regression tests for significant defects.

## M0 — Reproducible upstream baseline

**Status:** In progress
**Purpose:** Establish trustworthy measurements before product refactoring.

### Work

- Record the exact source tag and commit, toolchains, dependencies, CMake options, and host details.
- Build an untouched Release configuration on Linux.
- Run the available unit and integration suites without disabling failures.
- Launch the untouched GUI and record a smoke workflow.
- Record known upstream failures separately from environment failures.
- Document the upstream update procedure and merge policy.

### Exit gate

- A clean checkout can be configured and built using documented commands.
- Test commands, totals, passes, failures, and skips are recorded.
- The GUI launches and can create, save, close, and reopen a simple FCStd document.
- Baseline startup, representative file-load, and basic recompute measurements are retained.
- No OpenFusion refactor is mixed into the baseline evidence.

## M1 — Integrated Design workspace vertical slice

**Status:** Source integration paths researched; implementation is gated on a passing baseline
**Purpose:** Prove a real workspace presentation layer without replacing modeling logic or creating a mock interface.

### Scope

- A workspace selector backed by real FreeCAD workbench activation.
- A selection-driven contextual action strip backed by real commands.
- A fuzzy command palette for live commands and registered workspaces.
- The existing `ComboView`/`TreeWidget` retained as the functional Project browser.
- Design as the first fully registered workspace; other built-in mappings appear only when their backing workbench exists.
- No timeline control in this milestone. It remains absent until M2 provides graph-backed behavior.

### Existing integration points

- `Gui::Application::activateWorkbench()` and `signalActivateWorkbench`
- `Gui::WorkbenchManager`
- `Gui::CommandManager`, `CommandManager::signalChanged`, `Command::testActive()`,
  and the command-owned `Gui::Action`/`QAction`
- `Gui::WorkbenchManipulator` immediately before real toolbar setup
- `Gui::SelectionObserver` and `Gui::SelectionFilter`
- `Gui::ComboView`, `Gui::TreeWidget`, and global selection synchronization
- Part Design `TaskWatcherCommands` selection rules

### Planned core files and classes

| Planned path | Responsibility |
|---|---|
| `src/Gui/Workspace.h/.cpp` | Curated descriptors, runtime availability, real activation commands, selector action/combo box, bidirectional synchronization, and the narrow workbench-toolbar manipulator. |
| `src/Gui/CommandSearchModel.h/.cpp` | Copied command-ID/metadata snapshots and deterministic fuzzy ranking over actions exposed by the active menu and toolbars. |
| `src/Gui/CommandPalette.h/.cpp` | Nonmodal keyboard-accessible launcher with focus restoration and execution through the real command-owned `QAction`. |
| `src/Gui/WorkspaceContext.h/.cpp` | Later M1 sub-slice: coalesced document, view, selection, and edit-mode observation plus contextual action rules. |

### Initial workspace mappings

| Workspace | Backing workbench | Initial policy |
|---|---|---|
| Design | `PartDesignWorkbench` | First integrated and acceptance-tested workspace. |
| Surface | `SurfaceWorkbench` | Show only when present; detailed integration deferred. |
| Assembly | `AssemblyWorkbench` | Show only when present; detailed integration deferred. |
| Drawing | `TechDrawWorkbench` | Show only when present; detailed integration deferred. |
| Manufacturing | `CAMWorkbench` | Show only when present; detailed integration deferred. |
| Simulation | `FemWorkbench` | Show only when present; detailed integration deferred. |
| Mesh | `MeshWorkbench` | Show only when present; detailed integration deferred. |

Sheet Metal and Rendering must not be advertised until compatible implementations are available and audited.

### Initial Design context rules

- Edge: `PartDesign_Fillet`, `PartDesign_Chamfer`, `Std_Measure`.
- Single face: `PartDesign_NewSketch`, `PartDesign_Fillet`, `PartDesign_Chamfer`, `PartDesign_Draft`, `PartDesign_Thickness`, `Std_Measure`.
- Single sketch: `Sketcher_EditSketch`, `PartDesign_Pad`, `PartDesign_Pocket`, `PartDesign_Revolution`, `PartDesign_AdditiveLoft`, `PartDesign_AdditivePipe`.
- Single body: `PartDesign_NewSketch`, `Std_Properties`.
- Empty selection: `PartDesign_Body`.

Rules expose only registered commands and reuse their owned actions. Disabled
commands remain disabled. Palette execution must restore the prior focus, call
`Command::testActive()`, recheck the real action, and trigger that `QAction` so
grouped and checkable semantics are preserved. It must not use
`CommandManager::runCommandByName()`, which bypasses QAction-level gating.

### Safe implementation sequence

1. Add the curated workspace catalog, activation commands, and tests.
2. Replace only the existing toolbar selector item through
   `WorkbenchManipulator`; retain `Std_Workbench` and the legacy menu.
3. Prove UI, Python, addon, failure, and per-document-tab activation cannot
   diverge from the actual active workbench.
4. Add a copied-ID command search model over the current menu/toolbar surface;
   never retain raw command or action pointers.
5. Add the palette and its focus, enablement, grouped/checkable action, dynamic
   command removal, localization, and HiDPI tests.
6. Add contextual rule evaluation and the dynamic action widget.
7. Register and integration-test the Design rules after Part Design commands load.
8. Change only the visible `ComboView` title to Project; preserve `Std_ComboView` and object name `Model`.
9. Complete keyboard, focus, HiDPI, save/reopen, and undo/redo acceptance checks.
10. Enable the shell by default only after all M1 gates pass.

### Planned tests

- `tests/src/Gui/WorkspaceRegistry.cpp`
- `tests/src/Gui/ContextActions.cpp`
- `tests/src/Gui/CommandPalette.cpp`
- `tests/src/Gui/WorkspaceWidgets.cpp`
- `src/Mod/PartDesign/PartDesignTests/TestOpenFusionWorkspace.py`

### Exit gate

- Workspace and legacy workbench state cannot diverge during UI, Python, or per-tab activation.
- Selecting Design loads the real Part Design workbench and commands.
- Face, edge, sketch, body, and empty selections produce the specified real command sets.
- Context and palette activation trigger the enabled command-owned action after
  normal active-state checks and create no duplicate undo transaction.
- Lazy command registration updates the palette without restart.
- Escape closes the palette without changing a document and restores focus.
- Tree and viewport selections produce the same context.
- Body → sketch → pad → fillet → save → reopen → edit → undo/redo passes.
- No OpenFusion document metadata is written by the shell.

## M2 — Functional Project browser and parametric timeline

**Status:** Not started
**Purpose:** Connect hierarchy and history presentation to the real model graph.

### Sequence

1. Keep `TreeWidget` canonical while documenting its selection, rename, visibility, drag/drop, and active-object behaviors.
2. Use `Gui::Selection()` and document signals as the only browser/timeline synchronization boundary.
3. Add a workspace panel-provider interface without making `FreeCADGui` depend on `PartDesignGui`.
4. Implement `FeatureTimelineModel`, `FeatureTimelineView`, and `FeatureTimelineDock` in `src/Mod/PartDesign/Gui/`.
5. Populate the first timeline strictly from the active `PartDesign::Body::Group` and `Tip`.
6. Represent error, touched/recompute, and supported suppression states.
7. Implement click-to-select, `Std_Edit`, `Std_ToggleSuppress`, `PartDesign_MoveTip`, and guarded `Std_Delete` through existing commands.
8. Add dependency visualization from real `InList`/`OutList` relationships.
9. Defer reorder until base-feature rerouting, undo/redo, save/reopen, and downstream recompute tests pass.

### Exit gate

- No decorative or inert timeline item exists.
- Browser, viewport, and timeline selection remain synchronized during deletion, undo, redo, document close, and recompute.
- Rollback changes the real Body Tip and is undoable.
- Suppression changes actual output geometry where supported and persists through save/reopen.
- Timeline order is never misrepresented as a universal dependency graph.

## M3 — Sketcher and solid-modeling workflow hardening

**Status:** Not started

### Scope

- Solver-state presentation, dimensional entry, inferred constraints, conflict diagnosis, snapping, and keyboard workflows.
- High-value Part Design operations, preview/task flow, cancellation, invalid-geometry handling, and parametric editing.
- Audit every core operation for undo, redo, recompute, tree state, timeline state, and save/reopen.

### Exit gate

- The core acceptance model passes through sketch, constraints, pad/extrude, hole, fillet, pattern, early-feature editing, and downstream recompute.
- No known P0 defect remains in the modified Sketcher or Part Design paths.
- Dense-sketch and 100-feature reference models have retained performance measurements.

## M4 — Professional workspace integration

**Status:** Not started

Integrate, test, and document Surface, Assembly, Drawing, Manufacturing, Mesh, Simulation, Materials, and Rendering in separate reviewable milestones. Sheet Metal requires a separate license and technical audit before inclusion.

### Exit gate per workspace

- Commands shown in the workspace are functional or explicitly experimental.
- A representative create/edit/save/reopen/export workflow is recorded.
- Context actions, Project browser behavior, properties, and workspace switching are consistent.
- Known unsupported operations are documented rather than simulated.

## M5 — Viewport, navigation, and direct manipulation

**Status:** Not started

### Scope

- Rendering quality, overlays, selection outlines, construction visuals, grids, origin/work-plane presentation, section and measurement overlays.
- Configurable professional-CAD navigation preset without removing existing FreeCAD navigation methods.
- Cross-platform, HiDPI navigation cube and smooth camera transitions.
- Precise manipulators for selected operations, always paired with numeric input.

### Exit gate

- Navigation and selection tests pass on Linux, Windows, and macOS targets.
- 100%, 125%, 150%, 175%, and 200% scale checks are recorded where the platform supports them.
- Representative viewport FPS and selection latency do not regress beyond an approved measured budget.

## M6 — Reliability, security, and performance hardening

**Status:** Not started

### Scope

- Autosave, recovery, backups, Unicode and long paths, large files, older FCStd files, and untrusted input handling.
- Plugin loading, Python execution boundaries, external processes, URLs, archives, temporary files, parser surfaces, and compiler hardening.
- Repeatable benchmarks under `tools/benchmarks/` for startup, load, recompute, selection, viewport, assemblies, and memory.

### Exit gate

- Core data-loss and crash scenarios have regression coverage.
- Security review findings are triaged; release-blocking findings are closed.
- Performance results include before/after evidence and representative models.
- Crash-report locations and opt-in policy are documented.

## M7 — Packaging and cross-platform release engineering

**Status:** Not started

### Required artifacts

- `OpenFusion-VERSION-x86_64.AppImage`
- `openfusion-VERSION-linux-x86_64.tar.zst`
- `openfusion_VERSION_amd64.deb`
- `openfusion-VERSION.x86_64.rpm`
- `OpenFusion-VERSION-Windows-x86_64.exe`
- `OpenFusion-VERSION-macOS-arm64.dmg` and/or a verified universal DMG
- `SHA256SUMS` and feasible SBOM output

### Exit gate

- Each artifact is produced by a least-privilege pinned CI workflow.
- Clean environments install, launch, execute the acceptance workflow, save/reopen, export STEP/STL, and uninstall where applicable.
- Architecture and signing/notarization claims match reality.
- Missing Apple or Windows credentials are documented as blockers; success is never simulated.

## M8 — Convergence and release candidate

**Status:** Not started

### Exit gate

- Linux, Windows, and macOS build gates pass.
- All required packages pass clean-machine smoke tests.
- Core workflow, UI shell, Project browser, timeline, command search, and primary themes pass acceptance.
- Known critical bugs are zero; unresolved high-severity bugs block release.
- License notices, dependency audit, checksums, SBOMs, release notes, tags, source, and downloadable artifacts are verified.
- Artifacts are downloaded from the release and smoke-tested after upload.

## Release evidence policy

Every milestone report must answer:

1. What behavior was implemented?
2. What was only visual?
3. Which workflow became faster or safer?
4. What regression risk was introduced?
5. Which automated and manual tests passed?
6. What remains incomplete?
7. What is the largest remaining product gap?
8. Is any visible action nonfunctional?
9. Can the change endanger user data?
10. Would the modified area be trusted for real CAD work, and why?

The corresponding evidence belongs in `TESTING.md`, `KNOWN_ISSUES.md`, benchmark results, CI logs, and `docs/GAP_ANALYSIS.md`; it must not exist only in a release announcement.
