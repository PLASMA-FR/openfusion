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
| Configure | Ubuntu / Pixi | Pending | GitHub Actions baseline run not yet complete |
| Compile | Ubuntu / Pixi | Pending | GitHub Actions baseline run not yet complete |
| C++ tests | Ubuntu / Pixi | Pending | GitHub Actions baseline run not yet complete |
| CLI Python tests | Ubuntu / Pixi | Pending | GitHub Actions baseline run not yet complete |
| GUI Python tests | Ubuntu / Xvfb | Pending | GitHub Actions baseline run not yet complete |
| Windows build and CLI tests | Windows Server 2022 | Pending | GitHub Actions baseline run not yet complete |
| macOS build and tests | GitHub-hosted macOS | Pending | GitHub Actions baseline run not yet complete |
| Manual launch and interaction | Representative physical systems | Pending | Requires interactive display/hardware coverage |

## Baseline change rule

The upstream pin may change only in a focused commit that:

1. records the old and new full commit hashes;
2. reviews release and security notes;
3. runs the complete baseline and OpenFusion regression suites;
4. audits license and dependency changes;
5. documents migrations and known incompatibilities.
