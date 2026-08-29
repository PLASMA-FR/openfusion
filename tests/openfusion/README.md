# OpenFusion regression and acceptance tests

This directory is reserved for product-level tests that cross inherited module
boundaries. Existing FreeCAD unit and module tests remain in their established
locations and continue to run.

The first automated acceptance model will create real document objects and
verify a constrained sketch, pad, hole, fillet, pattern, second component,
supported assembly relationship, drawing, save/reopen, early-feature edit,
downstream recompute, undo/redo, and STEP/STL export. Unsupported steps fail or
are reported as explicit release blockers; they are never replaced by mock
objects.

The harness has not yet been implemented. Its eventual CTest registration must
fail when no tests are discovered and must run against both the build tree and
installed packages.
