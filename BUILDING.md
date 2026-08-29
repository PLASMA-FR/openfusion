# Building OpenFusion

OpenFusion is currently in its foundation phase. The tree is based on FreeCAD 1.1.3 and deliberately preserves its build system while OpenFusion-specific targets and package identities are introduced incrementally.

## Supported development baseline

- CMake 3.22 or newer
- A C++20 compiler: GCC 11.2+, Clang 14+, Apple Clang supplied by a supported Xcode toolchain, or MSVC from Visual Studio 2022
- Git with submodule support
- The dependency versions resolved by the committed `pixi.lock`

Do not regenerate `pixi.lock` as part of an unrelated change.

## Cross-platform Pixi build

Pixi is the preferred reproducible developer path because it is also used by the pinned upstream cross-platform CI.

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

For a debug tree:

```bash
pixi install --locked
pixi run configure-debug
pixi run build-debug
pixi run test-debug
```

Consult `pixi.toml` for the authoritative task names available at the checked-out revision.

## Native Ubuntu build

The pinned FreeCAD release provides the dependency installer used by its native Ubuntu CI:

```bash
sudo apt-get update
sudo apt-get install -y build-essential git
./package/ubuntu/install-apt-packages.sh

cmake -S . -B build/release -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_DEVELOPER_TESTS=ON
cmake --build build/release --parallel
ctest --test-dir build/release --output-on-failure
```

The script targets Ubuntu's available Qt 5/PySide2 dependency set. Do not mix that native environment with the Qt 6 Pixi environment in one build directory.

## Launching an uninstalled build

During the upstream-baseline phase the binary names are still:

```bash
build/release/bin/FreeCADCmd --version
build/release/bin/FreeCAD
```

This naming is transitional. A build does not qualify as an OpenFusion release until the executable, desktop metadata, application identifiers, resources, and installers have all passed the identity and packaging gates.

## Clean builds

Use separate build directories for each toolchain and configuration. Remove only the exact build directory you intend to recreate; never clean the source tree with a broad recursive command.

```bash
cmake --fresh -S . -B build/release -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_DEVELOPER_TESTS=ON
```

## Platform notes

- Windows production builds use MSVC and the audited dependency bundle or locked Pixi environment. The installer is built and tested separately from the application tree.
- macOS production builds use separate Apple Silicon and Intel jobs until every native dependency has a verified universal build. Signing and notarization require external Apple credentials.
- Linux release artifacts are derived from one audited relocatable staging tree, then packaged and tested independently as AppImage, `tar.zst`, DEB, and RPM.

See [PACKAGING.md](PACKAGING.md), [TESTING.md](TESTING.md), and [docs/UPSTREAM_BASELINE.md](docs/UPSTREAM_BASELINE.md).
