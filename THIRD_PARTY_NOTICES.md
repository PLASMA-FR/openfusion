# OpenFusion third-party notices

> **Status: incomplete — not approved for release distribution.**

This document is an initial inventory for the OpenFusion derivative of
FreeCAD 1.1.3 at upstream commit
`145529fe741292ff0b3977a01195bf0247425794`. It is not yet the complete notice
set for any source archive or binary package. Package contents differ by
platform, and the exact notices must be generated and verified from each final
artifact.

OpenFusion is based on FreeCAD and preserves FreeCAD copyright and license
notices. OpenFusion is an independent modified work; no endorsement by the
FreeCAD Project Association, Autodesk, or another third party is implied.

## Initialized source submodules

The following commits and local license files were verified in the initialized
working tree:

| Component | Path and pinned commit | Verified local license source |
| --- | --- | --- |
| Microsoft GSL | `src/3rdParty/GSL` at `543d0dd3fe966ddf20e884b44e5fdbf12cb43784` | `src/3rdParty/GSL/LICENSE` — MIT |
| OndselSolver | `src/3rdParty/OndselSolver` at `30e9b64e8bf881d438d4b88834f9ba3674865418` | `src/3rdParty/OndselSolver/LICENSE` — GNU LGPL 2.1 |
| FreeCAD Addon Manager | `src/Mod/AddonManager` at `937b6877239dc78ef59eeefe8099e5f14243eda1` | `src/Mod/AddonManager/LICENSE`; source headers commonly state LGPL-2.1-or-later |
| GoogleTest | `tests/lib` at `f8d7d77c06936315286eb55f8de22cd23c188571` | `tests/lib/LICENSE` — BSD-3-Clause |

GoogleTest is a test dependency and should not be present in normal runtime
packages. Its notice remains relevant to source and test distributions.

## Existing in-tree notice sources

The following files contain component-specific terms that must be preserved
and incorporated when the covered material is distributed:

- `src/3rdParty/PyCXX/CXX/COPYRIGHT`
- `src/3rdParty/libE57Format/LICENSE.md`
- `src/3rdParty/libE57Format/extern/CRCpp/LICENSE`
- `src/3rdParty/libkdtree/COPYING`
- `src/3rdParty/lru-cache/LICENSE`
- `src/3rdParty/salomesmesh/LICENCE.lgpl.txt`
- `src/Mod/CAM/libarea/kurve/License.txt`
- `src/Mod/Idf/Idflibs/License.txt`
- `data/examples/osifont.license`
- `src/Mod/TechDraw/Gui/Resources/fonts/osifont.license`
- `src/Mod/TechDraw/Gui/Resources/fonts/Y14.5Font.license`

These files are not collectively complete. Known missing or ambiguous items
include the Nokia Qt LGPL Exception referenced by QtColorPicker, an exact
license/version mapping for some IDF assets, unresolved template fields in the
libarea notice, and provenance/terms for SDK-derived 3Dconnexion material.
The generated `src/Doc/ThirdPartyLibraries.html.cmake` inventory covers only a
small subset of the tracked and packaged components and is not release sign-off.

## Packaged runtime dependencies

Current packaging lockfiles include platform-specific combinations of Qt,
PySide, Open CASCADE Technology, Python, Coin3D, Boost, Eigen, Xerces-C,
SMESH, OpenCAMLib, IfcOpenShell, pythonocc-core, Graphviz, CalculiX, gmsh,
ffmpeg, FreeImage, and many transitive libraries. Some are LGPL or GPL; some
carry exceptions or composite terms.

This list is descriptive only. It does not establish what is present in a
finished artifact and does not replace exact copyright notices, license texts,
source offers, or corresponding source. Packaging scripts currently copy broad
runtime trees and may remove package metadata, so final payload inspection is
mandatory.

Each released artifact must include:

- an inventory of its actual contents and exact dependency versions;
- complete applicable notices, acknowledgements, exceptions, and license
  texts;
- an SPDX or CycloneDX SBOM generated from the final payload;
- a mapping to complete corresponding source where required; and
- verified checksums and release provenance.

## Unresolved installed assets

Thirty-two installed material-pattern files explicitly state `All rights
reserved`. They are quarantined for release purposes until a redistribution
grant is documented or they are replaced or excluded. The complete set is in
`docs/legal/RELEASE_COMPLIANCE_AUDIT.md`.

## Release status

This notice file must not be used to claim license completeness. The current
release decision remains **NO-GO** until every blocker in
`docs/legal/RELEASE_COMPLIANCE_AUDIT.md` is closed and the exact final packages
are audited.
