# License text collection status

This directory is the intended home for canonical license and exception texts
distributed with OpenFusion source and binary artifacts.

It is deliberately incomplete. Its presence does **not** mean that the
repository or any package has passed a license audit. Do not publish a release
until the artifact-specific inventory described below has been completed.

## Current authoritative sources

- The principal FreeCAD-derived source license text is the root `LICENSE`
  file (GNU LGPL version 2.1).
- `COPYING` explains the mixed-license structure but does not replace any
  license text.
- Existing vendored license files remain authoritative for their respective
  components.
- Exact license files for initialized submodules remain in each submodule:
  - `src/3rdParty/GSL/LICENSE`
  - `src/3rdParty/OndselSolver/LICENSE`
  - `src/Mod/AddonManager/LICENSE`
  - `tests/lib/LICENSE`

No external license text has been copied into this directory merely from a
package label or web page. Each future addition must be taken from the exact
source or binary dependency version used to build the relevant artifact and
must be reviewed before commit.

## Candidate texts and exceptions to assemble

The tracked source and current packaging lockfiles indicate that the final
collection may need, at minimum, exact versions of:

- LGPL 2.0, 2.1, and 3.0;
- GPL 2.0 and 3.0 where GPL programs are shipped;
- MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, BSL-1.0, Zlib, ISC,
  Artistic-2.0, MPL-2.0, EPL-1.0, EUPL-1.2, and the FreeType License;
- applicable Creative Commons and font licenses;
- the Open CASCADE Technology LGPL exception;
- the Nokia Qt LGPL Exception referenced by QtColorPicker, if that licensing
  option is used; and
- component-specific acknowledgements, exceptions, and non-endorsement terms.

This is a candidate list, not a declaration that every listed license occurs
in every package.

## Release collection procedure

For each AppImage, tar archive, DEB, RPM, Windows installer/portable archive,
and macOS application/DMG:

1. inventory the files actually present in the finished artifact;
2. map every binary, library, script, asset, font, and embedded component to
   its exact source version and license;
3. copy the verified canonical texts and exceptions into the package;
4. generate `THIRD_PARTY_NOTICES.md` and an SPDX or CycloneDX SBOM from that
   payload rather than from the development environment alone;
5. verify corresponding-source and relinking/replacement obligations;
6. fail the release on an unknown, ambiguous, missing, or incompatible term;
   and
7. retain the resulting inventory, SBOM, notices, sources, and checksums with
   the release record.

The known blockers and unresolved assets are recorded in
`docs/legal/RELEASE_COMPLIANCE_AUDIT.md`.
