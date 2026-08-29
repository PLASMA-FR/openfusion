# OpenFusion

OpenFusion is an independent, open-source effort to build a coherent,
professional parametric CAD application on the mature FreeCAD codebase. The
project is preserving FreeCAD's document model, geometry kernel integrations,
Python interfaces, and file compatibility while incrementally introducing an
integrated workspace and workflow layer.

> [!WARNING]
> OpenFusion is in its foundation/pre-alpha phase. There is no verified
> OpenFusion binary release, installer, or supported-platform matrix yet. The
> current build configuration still uses transitional FreeCAD executable names
> and user-facing identity. Do not treat this repository as a production-ready
> OpenFusion release.

OpenFusion is not affiliated with, endorsed by, or sponsored by Autodesk, Inc.
It does not include Autodesk source code, binaries, trademarks, icons, or
artwork. Product and company names mentioned in design research belong to their
respective owners.

## Foundation

The immutable upstream baseline is FreeCAD `1.1.3`, tag `1.1.3`, commit
`145529fe741292ff0b3977a01195bf0247425794`. The upstream repository is
<https://github.com/FreeCAD/FreeCAD>.

FreeCAD is a powerful cross-platform parametric modeler built with Open
CASCADE, Coin3D, Python, and Qt. OpenFusion inherits substantial CAD capability
from FreeCAD, but an inherited feature is not automatically an accepted or
supported OpenFusion workflow. Claims are added only after build, functional,
compatibility, and packaging evidence is recorded.

## Current status

The project is establishing its reproducible upstream baseline, architecture,
governance, testing strategy, and release gates before large refactors begin.
The initial product direction is:

- a coherent workspace layer over existing FreeCAD modules;
- selection-aware commands and a global command launcher backed by real
  registered commands;
- a functional parametric timeline derived from the actual document and Part
  Design feature graph;
- modern project-browser, inspector, viewport, Sketcher, modeling, Assembly,
  Drawing, Manufacturing, and other workflows without duplicating CAD state;
- compatibility-preserving, incremental migration with tests for document
  persistence, recompute, and undo/redo;
- original OpenFusion branding, themes, and iconography; and
- tested, installable cross-platform packages with checksums and license
  notices before any production-support claim.

The implementation and verification gap is tracked in
[ROADMAP.md](ROADMAP.md), [docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md), and
[KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Building and testing

Clone with submodules and follow the reproducible instructions in
[BUILDING.md](BUILDING.md):

```bash
git clone https://github.com/PLASMA-FR/openfusion.git
cd openfusion
git submodule update --init --recursive
```

The preferred cross-platform dependency path uses the committed `pixi.lock`.
Native platform instructions and the current transitional binary names are
documented separately. See [TESTING.md](TESTING.md) for the required upstream,
OpenFusion, GUI, persistence, and package test layers.

No downloadable artifact should be described as an OpenFusion release unless
it appears in this repository's Releases area with matching test evidence,
release notes, checksums, and required notices. No such release exists yet.

## Architecture and compatibility

[ARCHITECTURE.md](ARCHITECTURE.md) documents the inherited FreeCAD subsystems
and OpenFusion migration boundaries. In particular:

- existing `FreeCAD` and `FreeCADGui` Python imports remain compatibility APIs;
- FreeCAD type identifiers and FCStd persistence contracts are not casually
  renamed;
- user-visible mutations use the established document transaction and command
  systems; and
- OpenFusion-specific metadata must be namespaced, versioned, and safely
  ignorable where possible.

Opening valuable CAD data always carries risk in pre-alpha software. Work on
copies, keep backups, and do not rely on this tree for production data until a
release explicitly states otherwise.

## Contributing

Contributions are welcome after reading [CONTRIBUTING.md](CONTRIBUTING.md),
[ARCHITECTURE.md](ARCHITECTURE.md), [TESTING.md](TESTING.md), and
[SECURITY.md](SECURITY.md). Changes should be focused, licensed compatibly,
tested at the appropriate layers, and preserve attribution and document
compatibility.

## Licensing and attribution

OpenFusion is derived from FreeCAD and retains the notices, authorship, and
license obligations of FreeCAD and its third-party dependencies. Copyright in
individual files remains with their respective authors. The repository-level
license text is in [LICENSE](LICENSE); file headers and component-specific
licenses continue to apply.

The dependency and asset audit for an OpenFusion binary distribution is still
in progress. [NOTICE.md](NOTICE.md) records the initial attribution statement;
a complete `THIRD_PARTY_NOTICES.md` and `LICENSES/` inventory are release
gates, not claims made by this pre-alpha tree.
