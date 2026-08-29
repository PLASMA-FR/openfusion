# Initial release compliance audit

**Decision:** **NO-GO for public binary or source release**

**Audit basis:** FreeCAD 1.1.3, upstream commit
`145529fe741292ff0b3977a01195bf0247425794`

**Scope:** tracked source, initialized submodules, current Pixi packaging
metadata and release workflows

**Limitations:** this is an engineering compliance record, not a legal opinion
or a substitute for jurisdiction-specific trademark or license advice.

## Why release is blocked

1. The installed and in-app license display is internally inconsistent: the
   root `LICENSE` contains GNU LGPL 2.1, while `src/Doc/LICENSE.html`,
   `package/WindowsInstaller/License.rtf`, and embedded About-dialog text carry
   the older GNU Library GPL version 2 text.
2. `LICENSES/` and `THIRD_PARTY_NOTICES.md` are only scaffolds, `NOTICE.md` is
   absent, and `src/Doc/ThirdPartyLibraries.html.cmake` covers only a subset of
   tracked and packaged components. The repository does not yet contain the
   exact artifact-specific license and attribution closure.
3. Thirty-two material-pattern files installed by the application say
   `License: "All rights reserved"`; no downstream redistribution grant has
   been established by this audit.
4. Other terms remain incomplete or ambiguous, including the QtColorPicker
   Nokia exception, portions of the IDF asset set, a templated libarea notice,
   and SDK-derived 3Dconnexion material.
5. The final AppImage, archives, DEB, RPM, Windows, and macOS payloads have not
   been independently inventoried. Current bundle scripts copy broad runtime
   environments and can remove package metadata.
6. Complete corresponding source and relinking/replacement compliance has not
   been demonstrated for the actual binaries. The current source release job
   also references nonexistent `package/disable_git_info.patch`.
7. The `OpenFusion` name has not received a professional trademark clearance
   decision, and product-facing FreeCAD branding remains in the tree.
8. A Xerces parser used for FCStd metadata lacks the explicit external-entity
   protections used by other parsers. This is a potential, unconfirmed
   security inconsistency; it has not been demonstrated as exploitable.
9. Release download pinning, workflow permissions, compiler hardening,
   mandatory signing/notarization, SBOM generation, and vulnerability gates
   are not yet release-grade.

## Principal license and notice state

The root `LICENSE` is the authoritative GNU LGPL 2.1 text for the principal
FreeCAD-derived source. Many source headers state `LGPL-2.1-or-later`.
Individual files and components carry other licenses, exceptions, and
attribution requirements; those file-level terms remain controlling for their
material.

The following must be preserved:

- root `LICENSE` and all per-file copyright/SPDX notices;
- FreeCAD provenance and historical copyright notices;
- third-party license, exception, attribution, acknowledgement, and
  non-endorsement notices;
- conspicuous modification history for changed FreeCAD-derived files; and
- the exact corresponding source and build/install scripts required by the
  applicable copyleft terms.

`COPYING` is an overview and does not replace any license. A literal file named
`COPYING`, `LICENSES/`, or `NOTICE.md` is not by itself proof of compliance.

## Initialized submodules

| Submodule | Pinned commit | Locally verified license source | Release treatment |
| --- | --- | --- | --- |
| `src/3rdParty/GSL` | `543d0dd3fe966ddf20e884b44e5fdbf12cb43784` | `LICENSE` — MIT | Include notice if shipped or in source distribution. |
| `src/3rdParty/OndselSolver` | `30e9b64e8bf881d438d4b88834f9ba3674865418` | `LICENSE` — GNU LGPL 2.1 | Include exact source/license and preserve replacement/relinking rights as applicable. |
| `src/Mod/AddonManager` | `937b6877239dc78ef59eeefe8099e5f14243eda1` | `LICENSE`; headers commonly state LGPL-2.1-or-later | Include exact source/license; separately security-audit addon acquisition and execution. |
| `tests/lib` | `f8d7d77c06936315286eb55f8de22cd23c188571` | `LICENSE` — BSD-3-Clause | Include in source/test notices; exclude from normal runtime payload unless required. |

The release process must verify these exact commits rather than relying on the
moving heads of their upstream repositories.

## Material-pattern quarantine

Every file below identifies David Carter as author at line 6 and states
`License: "All rights reserved"` at line 7. All are listed for installation in
`src/Mod/Material/CMakeLists.txt:190-222`.

Do not include them in a public source archive or binary package until an
applicable redistribution grant is documented. Acceptable closure is a
verified grant, replacement with original appropriately licensed assets, or
exclusion from all distributed payloads. Do not silently rewrite the metadata.

```text
src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal4.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Diagonal5.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond2.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Diamond4.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Horizontal5.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Square.FCMat
src/Mod/Material/Resources/Materials/Patterns/PAT/Vertical5.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/aluminum.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/brick01.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/concrete.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cross.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/cuprous.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal1.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/diagonal2.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/earth.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/general_steel.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/glass.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45L.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hatch45R.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/hbone.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/line.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plastic.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/plus.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/simple.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/solid.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/square.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/steel.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/titanium.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/wood.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/woodgrain.FCMat
src/Mod/Material/Resources/Materials/Patterns/Pattern Files/zinc.FCMat
```

## FCStd metadata parser inconsistency

### Confirmed facts

- `src/App/ProjectFile.cpp:228-266` implements
  `ProjectFile::loadDocument()`.
- It reads `Document.xml` from an FCStd ZIP at lines 234-240 and parses it at
  lines 248-250.
- Its `XercesDOMParser` configuration at lines 241-246 does not explicitly
  disable default external entity resolution or external DTD loading.
- The main XML reader does set those controls at
  `src/Base/Reader.cpp:77-78`.
- Parameter parsing also installs an entity blocker at
  `src/Base/Parameter.cpp:1902-1910`.
- `ProjectFile::loadDocument()` is reached by recent-file/start metadata and
  thumbnail processing in `src/Mod/Start/App/DisplayedFilesModel.cpp:48-68`
  and recovery validation in `src/Gui/DocumentRecovery.cpp:566-581`.

### What is not established

No proof-of-concept test has shown that the Xerces version and build used by a
shipping OpenFusion package fetches or expands an external URI through this
path. No file disclosure or outbound connection has been observed. Therefore:

- classify this as a **potential, unconfirmed XXE/security-hardening gap**;
- do not label it a confirmed vulnerability or assign/reuse a CVE; and
- run a pre-patch regression fixture to determine whether current builds are
  exploitable.

### Minimal proposed hardening

Immediately after `setCreateEntityReferenceNodes(false)` in
`src/App/ProjectFile.cpp`, set:

```cpp
parser->setDisableDefaultEntityResolution(true);
parser->setLoadExternalDTD(false);
```

This proposed change is not part of this documentation-only scaffold. A later
refactor should centralize secure Xerces parser construction and attach a
deny-all resolver so parser policies cannot drift.

### Required regression tests

1. Extend `tests/src/App/ProjectFile.cpp` with a temporary FCStd whose
   `Document.xml` references a temporary external DTD defining a sentinel
   entity used in document metadata.
2. Run it before hardening. If the sentinel reaches `getMetadata().comment`,
   record confirmed exploitability; otherwise retain the patch as an explicit
   invariant.
3. After hardening, assert that the sentinel is never returned.
4. Add a loopback HTTP DTD fixture and assert that it receives zero
   connections.
5. Keep the existing valid `ProjectTest.FCStd` load and metadata tests green.
6. Run the tests on Linux, Windows, and macOS, with ASan/UBSan where available.
7. Separately add XML entity-expansion and ZIP entry/count/size/ratio limits,
   then test billion-laughs and ZIP-bomb inputs.

## Artifact-specific compliance requirements

The development and packaging lockfiles are evidence of intended dependency
versions, not proof of final payload contents. Linux and macOS scripts copy
broad Pixi environments; Windows copies broad DLL, Python, and share trees.
Some scripts then delete package metadata or documentation.

For every final AppImage, tar archive, DEB, RPM, Windows installer/portable
archive, and macOS application/DMG, the release record must contain:

1. a recursive payload manifest;
2. an exact component/version/license mapping;
3. all applicable canonical license texts, exceptions, notices, copyright
   statements, acknowledgements, and attribution;
4. an SPDX or CycloneDX SBOM generated from the final payload;
5. a corresponding-source mapping, including recursive submodules and build
   scripts;
6. evidence that LGPL-covered libraries can be modified/replaced or relinked
   as required;
7. vulnerability scan results and documented resolution of findings;
8. signature/notarization verification and unified SHA-256 checksums; and
9. an installation and launch smoke-test record from a clean environment.

The release must fail on an unknown license, unresolved exception, missing
source mapping, unexpected binary, or material payload drift.

## Branding and name clearance

FreeCAD copyright and provenance must remain, but FreeCAD logos, wordmarks,
desktop identifiers, installer artwork, application icons, splash/about art,
update metadata, and package identity must not brand OpenFusion as an official
FreeCAD Project Association build. Review the FPA guidance at
<https://fpa.freecad.org/handbook/process/logo.html>.

The proposed `OpenFusion` name is not cleared by this audit. Autodesk publicly
identifies `Autodesk Fusion` as a trademark and publishes restrictions on
similar or variant third-party product names. That fact does not by itself
establish infringement. Before public branding, obtain a professional search
and written clearance decision for the intended jurisdictions, goods, domain,
package identifiers, and distribution channels. Review the published guidance
at <https://www.autodesk.com/company/legal-notices-trademarks/trademarks/guidelines-for-use>.

Do not use Autodesk logos, icons, artwork, or product screenshots as
OpenFusion branding. Referential compatibility or workflow comparisons must
be accurate, subordinate to OpenFusion's own identity, and accompanied by a
clear non-affiliation statement.

## Release sign-off gates

- [ ] All source/submodule commits and release inputs are immutable and
      verified.
- [ ] Every final artifact has an exact notice inventory and SBOM.
- [ ] Canonical license and exception texts are installed and visible.
- [ ] Complete corresponding source is available beside the binaries.
- [ ] The 32-file material quarantine and all other ambiguous terms are
      resolved.
- [ ] Name and branding clearance is documented.
- [ ] The FCStd parser inconsistency has been tested and hardened.
- [ ] Archive/XML resource limits and malformed-file tests pass.
- [ ] Release downloads and GitHub Actions are digest-pinned and verified.
- [ ] Build jobs are least-privilege; release publication is isolated.
- [ ] Production Windows and macOS artifacts fail closed without valid signing
      and notarization.
- [ ] Static analysis, dependency/vulnerability, secret, and artifact scans
      pass with no unapproved critical or high finding.
- [ ] Compiler/linker hardening is verified on the produced binaries.
- [ ] Clean-machine installation, launch, modeling, save/reopen, and export
      smoke tests pass.

Until every applicable item is checked with retained evidence, the release
decision remains **NO-GO**.
