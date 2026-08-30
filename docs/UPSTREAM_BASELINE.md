# Upstream baseline

OpenFusion starts from the latest stable FreeCAD release available when the project was initialized.

| Field | Value |
|---|---|
| Upstream repository | <https://github.com/FreeCAD/FreeCAD> |
| Release | FreeCAD 1.1.3 |
| Tag | `1.1.3` |
| Commit | `145529fe741292ff0b3977a01195bf0247425794` |
| Release date | 2026-07-25 |
| OpenFusion import date | 2026-08-29 |

The full commit hash is the trust anchor. The tag name alone is not used as an immutable input. FreeCAD 1.1.3 was selected instead of a weekly build because it is the current non-prerelease release and contains security fixes for untrusted FCStd file handling.

## Reproducible dependency baseline

The primary cross-platform baseline uses the upstream `pixi.lock`, CMake presets, and CI workflow from the pinned commit. The lock file constrains the important CAD/runtime dependencies, including Python 3.11, Qt 6.8, PySide6, and OCCT 7.8.

```bash
git clone https://github.com/PLASMA-FR/openfusion.git
cd openfusion
git submodule update --init --recursive

pixi install --locked
pixi run configure-release
pixi run build-release
pixi run test-release
pixi run install-release
```

The native Linux comparison baseline follows the pinned release's Ubuntu dependency installer and CMake release preset:

```bash
./package/ubuntu/install-apt-packages.sh
cmake --preset release
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
build/release/bin/FreeCADCmd -t 0
xvfb-run build/release/bin/FreeCAD -t 0
```

The executable names remain the upstream names until the dedicated identity and packaging migration is implemented and verified. They must not be presented as final OpenFusion packages.

## Baseline evidence

Results are updated only from completed logs. `Pending` is not a pass.

| Gate | Environment | Status | Evidence |
|---|---|---:|---|
| Source hash verification | Local checkout | Passed | `git rev-parse HEAD` matched the full pinned commit before project files were added |
| Configure | Ubuntu 24.04 / locked Pixi | Passed | Run `33260276705`, job `99120908676` |
| Compile | Ubuntu 24.04 / locked Pixi | Passed | Release build completed in run `33260276705` |
| C++ tests | Ubuntu 24.04 / locked Pixi | Failed | 1,424 discovered; two TechDraw tests segfaulted; run `33260276705` |
| CLI Python tests | Ubuntu / Pixi | Not run | Correctly skipped after the fail-closed CTest gate |
| GUI Python tests | Ubuntu / Xvfb | Pending | GitHub Actions baseline run not yet complete |
| Windows build and CLI tests | Windows Server 2022 | Pending | GitHub Actions baseline run not yet complete |
| macOS build and tests | GitHub-hosted macOS | Pending | GitHub Actions baseline run not yet complete |
| Manual launch and interaction | Representative physical systems | Pending | Requires interactive display/hardware coverage |

### First executed Linux baseline

GitHub Actions run `33260276705` tested OpenFusion commit
`62bf348bec8dd6c09bdf6c89aefd704390a34212` using the locked Pixi Release
configuration. Configure, compilation, and CTest discovery succeeded. CTest
discovered 1,424 entries and reported two failures after 52.03 seconds:

- `TestLineFormat.setQColorKeepsOpaqueColorsOpaque` — segmentation fault
- `TestLineFormat.setQColorPreservesAlphaValue` — segmentation fault

The run also reported nine non-running entries: three skipped tests and six
disabled tests. The failure artifact digest is
`sha256:42de29fd75c571162562d5985773967a81dcc950f67fefcfc3f19fb5fae70c40`.
The fail-closed workflow then skipped the CLI suite, so this run is not a
passing baseline.

Both failures used the four-argument `TechDraw::LineFormat` constructor. That
constructor derives a line number through `LineGenerator::fromQtStyle()`,
which reads application preferences even though `TechDraw_tests_run` uses
plain `gtest_main` and has no initialized application singleton. The focused
repair implements the already-declared five-argument constructor and supplies
an explicit line number in these value-conversion tests. A successful full
rerun is required before changing the C++ test gate to Passed.

## Baseline change rule

The upstream pin may change only in a focused commit that:

1. records the old and new full commit hashes;
2. reviews release and security notes;
3. runs the complete baseline and OpenFusion regression suites;
4. audits license and dependency changes;
5. documents migrations and known incompatibilities.

## Upstream remote and update policy

Every maintainer checkout must keep the OpenFusion repository as `origin` and
configure FreeCAD as a fetch-only `upstream` remote:

```bash
git remote add upstream https://github.com/FreeCAD/FreeCAD.git
git remote set-url --push upstream DISABLED
git remote -v
```

If `upstream` already exists, verify its fetch URL and reapply the disabled
push URL. Never add credentials to either remote URL.

An upstream update is prepared on a dedicated `upstream-review/<version>`
branch from the current OpenFusion integration branch. Fetch tags and the
candidate commit without changing the working branch, then verify the exact
object that will be reviewed:

```bash
git fetch --prune --tags upstream
git rev-parse --verify '<tag>^{commit}'
git switch -c upstream-review/<version>
git merge --no-commit --no-ff '<full-upstream-commit>'
```

The merge remains uncommitted until maintainers have reviewed the complete
source and submodule diff, upstream release and security notes, dependency and
license changes, FCStd compatibility risk, and OpenFusion-specific conflicts.
Abort an unsuitable candidate with `git merge --abort`; do not rewrite the
published OpenFusion history to make an upstream update appear simpler.

An accepted update is submitted as a focused pull request. Its merge commit
must retain both parents, record the old and new full upstream hashes, update
this document and the third-party notices as needed, and link the following
evidence:

- locked Linux, Windows, macOS arm64, and macOS x86_64 builds;
- the complete CTest, CLI, GUI, serialization, and acceptance results;
- representative FCStd save/reopen and STEP/STL interoperability results;
- dependency, license, CodeQL, and untrusted-input review results;
- benchmark comparisons for startup, recompute, file loading, and memory when
  the candidate materially changes those paths.

OpenFusion fixes that are suitable for FreeCAD should be kept as independently
reviewable commits so they can be proposed upstream. OpenFusion-only product
presentation, branding, and packaging changes stay in this repository and
must not be represented as FreeCAD changes.
