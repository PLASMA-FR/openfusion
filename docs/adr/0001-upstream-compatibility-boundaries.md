# ADR 0001: Preserve Upstream Compatibility Boundaries

- Status: Accepted
- Date: 2026-08-29
- Decision owners: OpenFusion engineering
- Upstream baseline: FreeCAD `1.1.3`, commit
  `145529fe741292ff0b3977a01195bf0247425794`

## Context

OpenFusion is derived from FreeCAD and intends to deliver a coherent,
professional CAD experience without discarding FreeCAD's mature modeling,
persistence, scripting, and addon ecosystem.

The visible FreeCAD interface exposes workbench and implementation structure
that OpenFusion intends to reorganize. The same codebase also contains
high-value contracts that are difficult to replace safely:

- FCStd document serialization and restore;
- document transactions, dependency ordering, and recomputation;
- App property and runtime type systems;
- Python module and object APIs;
- ViewProvider, Coin3D, and selection paths;
- Sketcher solver indices and external geometry references;
- Part Design Body order, Tip, BaseFeature chain, and topological references;
- cross-document links and Assembly solver updates;
- CAM postprocessors and FEM external-solver execution.

Changing those contracts as part of a shell redesign would combine UX work
with document-migration, geometry-correctness, addon-compatibility, and data-
loss risks. A clean-looking rewrite would not justify that risk.

## Decision

OpenFusion will use an incremental presentation-layer architecture.

The first product layer will compose existing Qt commands, workbenches,
documents, ViewProviders, selection, properties, and module operations. It may
replace how those capabilities are presented, but it will not initially
replace their authoritative model or persistence contracts.

Specifically:

1. `App::Application`, `App::Document`, and `App::DocumentObject` remain the
   sole owners of CAD document state.
2. `Gui::Application`, `Gui::MainWindow`, `Gui::Document`, and `Gui::MDIView`
   retain application, window, GUI-document, and view lifecycle ownership.
3. `Gui::CommandManager` command IDs and command active state are the primary
   execution boundary for the shell, workspaces, contextual tools, shortcuts,
   and command search.
4. `Gui::SelectionSingleton` remains the sole selection and preselection
   authority across the viewport, project browser, inspector, and timeline.
5. The timeline is derived from semantic feature ownership and dependencies,
   especially Part Design Body order and Tip. The undo stack is not a feature
   timeline.
6. Existing `FreeCAD` and `FreeCADGui` Python imports, document TypeIds, and
   FCStd object schemas remain supported. OpenFusion may add facade APIs and
   namespaced metadata without removing those compatibility names.
7. OpenFusion-specific persistent metadata must be namespaced and versioned,
   optional where possible, and ignored safely by readers that do not know it.
8. Branding, original assets, theme tokens, workspace definitions, command
   search, contextual presentation, and new Qt models are preferred early
   extension seams.

## Protected boundaries

| Boundary | Existing authority | Rule |
| --- | --- | --- |
| Document persistence | `App::Document`, properties, TypeIds, `Document.xml`, `GuiDocument.xml` | No incompatible schema or type-name change without migration fixtures and upstream round-trip analysis. |
| Transactions and recompute | `App::Document` transaction and dependency APIs | Every modeling mutation is one named, undoable transaction and uses normal recompute signaling. |
| Python compatibility | `FreeCAD`, `FreeCADGui`, generated wrappers, Python features | Add aliases or facade APIs; do not remove or silently change established APIs during the compatibility period. |
| Command compatibility | `Gui::CommandManager`, stable command IDs, `Gui::Action` | Discover and invoke commands through the registry; do not duplicate implementations or bypass active state. |
| Selection | `Gui::SelectionSingleton` and subelement paths | Do not maintain a second selected-object list or translate Face/Edge/Vertex paths into an incompatible form. |
| GUI object representation | `Gui::Document`, ViewProviders, `claimChildren()`, Coin roots | Presentation models observe and adapt these contracts; they do not take ownership from them. |
| Viewport | Coin3D, Quarter, `View3DInventorViewer`, ViewProvider scene nodes | Improve locally; renderer replacement requires a separate compatibility program. |
| Sketcher | `SketchObject`, geometry/constraint indices, PlaneGCS | UI changes must preserve indices, solver semantics, persistence, undo, and external-geometry references. |
| Part Design history | Body Group order, Tip, BaseFeature, dependency and topology references | Timeline mutations are capability-gated and feature-specific; no generic arbitrary reorder. |
| Assembly | Links, dynamic joint properties, OndselSolver placement updates | Preserve schemas and transact solver-driven multi-object changes atomically. |
| CAM and FEM | Operation proxies, postprocessors, solver runners, parsers | Treat generated machine instructions and external execution as safety/security boundaries. |
| Addons | Module discovery, `Init.py`, `InitGui.py`, `package.xml` | Preserve discovery and loading unless a documented security or compatibility migration supersedes it. |

## Approved first-slice seams

The following changes are inside the decision and do not require another
architecture decision when implemented as adapters:

- install an OpenFusion top frame and docks in `Gui::MainWindow`;
- expose coherent workspaces through `Gui::WorkbenchManager` and curated
  command IDs;
- index `Gui::CommandManager::getAllCommands()` for fuzzy command search,
  rebuilding on `signalChanged`;
- derive contextual commands from `Gui::SelectionSingleton`, edit state, and
  the underlying command active state;
- present a `QAbstractItemModel` project browser backed by GUI documents,
  ViewProviders, and `claimChildren()`;
- present a read-only timeline backed by Part Design Body order, Tip, document
  dependencies, and recompute state;
- add timeline mutations incrementally through existing commands and explicit
  App transactions;
- add OpenFusion theme parameter sets and QSS using the existing
  StyleParameters machinery;
- add a navigation profile through the existing NavigationStyle interface.

## Incremental migration rules

1. Preserve one source of truth. UI models hold presentation state only.
2. Prefer adapters around public or already-shared contracts over edits to
   document, solver, kernel, or serialization internals.
3. Land one independently testable behavior per focused change. Do not mix a
   shell migration with persistence or geometry rewrites.
4. Keep the legacy surface available until the replacement passes behavioral
   parity tests for selection, activation, editing, undo/redo, save/reopen,
   keyboard access, and localization.
5. Capability-gate UI. A command is visible as production functionality only
   when its backing operation exists and its active state allows execution.
6. Use feature-specific mutation policies for timeline delete, suppress,
   rollback, and reorder. Unsupported operations remain absent rather than
   simulated.
7. Namespace and version all new persisted metadata. Readers must tolerate
   missing and unknown OpenFusion metadata.
8. Maintain representative upstream-created FCStd fixtures and test
   open, recompute, save-copy, reopen, undo/redo, STEP export, and STL export.
9. Preserve `FreeCAD`/`FreeCADGui` compatibility in automated Python and addon
   smoke tests.
10. Measure startup, recompute, viewport, and memory effects when a change
    crosses a hot path; presentation polish does not justify a large
    regression.

## Changes requiring a new ADR

The following are intentionally outside this decision:

- renaming or removing the `FreeCAD` or `FreeCADGui` Python modules;
- changing persisted TypeIds, property semantics, or FCStd archive structure;
- replacing `App::Document` transactions or recompute scheduling;
- introducing an independent selection model;
- replacing Coin3D/Quarter or ViewProvider scene contracts;
- rewriting the Sketcher solver or changing persisted geometry/constraint
  indexing;
- changing general Part Design history or topological naming semantics;
- replacing Assembly link or joint persistence;
- changing CAM postprocessor semantics or FEM process-execution policy;
- bundling an external workbench, including Sheet Metal, before license and
  dependency review.

A follow-up ADR for one of these changes must state the compatibility window,
migration and rollback path, affected file formats and APIs, test fixtures,
performance impact, and upstream contribution strategy.

## Consequences

### Positive

- OpenFusion can modernize the primary workflow while retaining proven CAD
  behavior and document compatibility.
- Early changes are smaller, reviewable, and more likely to remain compatible
  with future FreeCAD updates.
- Existing commands, macros, addons, translations, preferences, and tests
  remain useful.
- UI replacement can be evaluated independently from geometry correctness.

### Costs

- Some legacy classes and compatibility names remain visible internally.
- Adapters must account for lazy Python command registration and module-specific
  behavior.
- The project browser and timeline require a staged coexistence period with
  legacy views.
- Not every requested workflow can be generalized immediately; unsupported
  operations must remain absent or explicitly experimental.

These costs are accepted because data integrity, modeling correctness, and
ecosystem compatibility take priority over a rapid internal rename or rewrite.

## Verification

Compliance with this decision is demonstrated by tests that prove:

- existing FCStd fixtures open, recompute, save as copies, and reopen;
- core modeling operations remain undoable and redoable;
- OpenFusion browser/timeline selection is identical to viewport selection;
- command search invokes the same command object and respects active state;
- workspaces do not replace the active document or corrupt edit mode;
- supported timeline mutations preserve Body order, Tip, downstream
  recomputation, and save/reopen behavior;
- `FreeCAD` and `FreeCADGui` imports and representative addon commands still
  work;
- no new OpenFusion metadata is required to read an otherwise compatible
  document.
