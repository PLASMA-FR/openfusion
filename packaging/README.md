# OpenFusion packaging integration

This directory is the integration boundary for OpenFusion-specific package
metadata, validation, and release manifests. During the upstream-baseline
phase, the inherited FreeCAD implementations remain under `package/`.

Nothing in this directory currently constitutes a distributable OpenFusion
package. A format moves here only after its product identity, dependency
closure, license bundle, install/uninstall behavior, and clean-machine smoke
test are verified.

See [`../PACKAGING.md`](../PACKAGING.md) for the package plan and
[`../docs/ci/RELEASE_PIPELINE.md`](../docs/ci/RELEASE_PIPELINE.md) for release
gates.
