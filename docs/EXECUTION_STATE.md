# OpenFusion Execution State

**Last verified:** 2026-08-31 UTC
**Production-ready:** No
**Active milestones:** M0 macOS closure and first M1 product/release slices
**Next task:** Re-fetch the connector head created with this state update,
record its exact SHA/tree on PR #28, and run the complete native matrix. The
new run must prove both lazy optional-navlib startup and explicit MDI hierarchy
destruction on both macOS architectures; Linux and Windows must stay green.
Keep PR #28 draft and keep Dependency Review fail-closed.

Local Linux evidence is not native Windows/macOS proof. A development archive
is not a production release or clean-machine support claim.

## Source state

| Item | Verified value |
|---|---|
| Foundation | FreeCAD 1.1.3, `145529fe741292ff0b3977a01195bf0247425794` |
| Last connector-verified base head | `fc7052f95dcdad73a6476c375cb79156ece1202a`, tree `d15a6a93391653eaea76454a3d671b2161697525` |
| Local reviewed source head | `dbed09de7196096a2be73b315a3d3e3f3beb3eef`, tree `1293e90cd2fe4382720a0731683403f47b5a8d6d`, plus this truth update |
| Branch / PR | `integration/acceptance-ci`; draft PR #28; connector-created update SHA intentionally not predicted |
| Dependency lock | `pixi.lock`, SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |
| External setting blocker | Issue #32: repository Dependency Graph is disabled |

## Current implementation

- Native `Std_CommandPalette` on Ctrl+K uses live command-owned actions,
  deterministic fuzzy/token ranking, recency, disabled-state enforcement,
  focus/keyboard/accessibility behavior, and single activation.
- Native `Std_WorkspaceDesign` on Ctrl+Alt+D activates the real Part Design
  workbench, persists only successful activation, follows external/Python
  workbench changes, and fails closed when Part Design is absent or disabled.
- Windows CI stages one Pixi-locked app-local Mesa renderer and verifies the
  loaded module path/hash, OpenGL context, lock provenance, and clean logs.
- GUI exit handling is exception-neutral and first-code authoritative. The
  latest macOS candidate explicitly deletes the owned QMdiArea hierarchy while
  `MainWindow` and its private state are valid, before QMainWindow base teardown.
- The optional 3Dconnexion navlib no longer loads from a global initializer
  before `main`; a thread-safe function-local initialization loads it exactly
  once on first real navlib API use, preserving normal loader errors while
  keeping version-only execution independent of the optional framework.
- Canonical `OpenFusion` / `OpenFusionCmd` entry points and compatibility names
  are installed. Headless version grammar preserves `-v`, `--version`, optional
  `--verbose`, the `--` terminator, Unicode positional arguments, and exact
  no-display behavior.
- Linux packaging signs a domain-separated full normalized payload tree with
  Ed25519, binds release coordinates/provenance/policy, pins OpenSSL by inode,
  enforces output limits, verifies extraction, ELF/RPATH/aliases, and streams
  legal quarantine over the extracted payload.
- Thirty-two restricted patterns and the inherited thumbnail DLL are removed;
  source/index and final-payload guards cover hash/LFS/path/metadata/installer
  identities, UTF-16/UTF-32, whitespace and chunk-boundary evasions.
- Locked dependency audit deterministically covers 1,539 packages and 1,844
  platform references. Its SPDX is a source-lock inventory, not a runtime SBOM.

## Exact local Linux arm64 evidence

Environment: Ubuntu 24.04 arm64, 2 CPUs, Clang 21.1.0, CMake 4.2.1,
Ninja 1.13.2, Python 3.11.14, Qt 6.8.3, locked Pixi environment.

| Gate | Result |
|---|---|
| Build / entry points | Reviewed combined build passed; final runtime-only changes were compiled/relinked from the exact source. `OpenFusion` and `FreeCAD` pairs are byte-identical, as are CLI pairs. |
| Full CTest | 1,437 registered; 1,431 enabled; zero failed; three skipped; six disabled; five acceptance tests; 138.73 s. |
| CLI suite | 1,674 ran; 10 skipped; zero failures; parser count 1,674; 156.092 s. |
| GUI suite | 1,776 ran; zero failures; parser count 1,776; exact exit 0 and complete teardown; 426 s. |
| Final MDI lifecycle | Six process scenarios, including 64 repeatedly maximized live subwindows, passed in 23.95 s with ordered owned-UI, MainWindow, application, Python-finalization, lock-cleanup and process markers. |
| Headless identity | GUI and CLI report exact configured OpenFusion versions without loading QPA; option grammar regression passed. |
| Design workspace | Linked `WorkspaceSelector_Tests_run` passed 1/1 in 0.17 s; real enabled/disabled/unregistered availability, activation, persistence, external synchronization, focus and accessibility are covered. |
| Lazy navlib | `NavlibLazyLoad.ConcurrentFirstUseLoadsExactlyOnce` passed 1/1 in 21 ms from the linked `Gui_tests_run`; the C and C++ implementation compiled warning-clean in isolated review. |
| Packaging / legal | Packaging 80/80, thumbnail source quarantine 19/19, material quarantine 24/24, dependency audit 30/30, live 32-identity guard, Actionlint/YAML/diff/secret checks passed. The reviewed policy exemption is exact-path and exact-SHA-bound. |

## Verified Linux development artifact

Path:
`/home/ubuntu/openfusion/artifacts/openfusion-final-4e9eff50/package/openfusion-1.1.3-dev.4e9eff50-linux-aarch64.tar.zst`

| Item | Evidence |
|---|---|
| Archive | 88,811,040 bytes; SHA-256 `3ca8688c6e0a94644eea7843d4377214af8f5f19690ddf0fbe3bacce350179ac` |
| Manifest | 626,879 bytes; SHA-256 `ff3d494f6e9b4812c463598f70a969f9f1999604cf6eb32afa140b5daba15616` |
| Checksum file | 250 bytes; SHA-256 `a7c6d29f724e1b26b34696119db33fa52a7f1ac279799f7be31bbaf49a7f239e` |
| Signed payload | 3,879 entries, 329,190,108 file bytes, tree SHA-256 `ba4b3e70284fd760bf814bd034e423ca5d958863b5a78bb909576cad2c978da5` |
| Verification | Internal and standalone verification, fresh extraction, full-tree recomputation, corrected legal quarantine, aliases, RPATH/`ldd`, GUI/CLI version smokes, and private-key exclusion passed. |

This artifact is development-only. It uses an ephemeral development SPKI and
retains a locked-Pixi absolute fallback RUNPATH; the host smoke is not a clean
machine or relocatable-runtime claim. Production SPKI allow-list/key custody,
artifact signing, runtime SBOM, and clean install/uninstall remain blockers.

## Terminal native matrix at published head `3f54ec58`

All baseline/TechDraw artifacts expire 2026-09-30.

| Platform / run | Result | Artifacts |
|---|---|---|
| Linux `33384592180` | **Success.** 1,430 enabled CTests, TechDraw, CLI 1,674 (10 skipped), GUI 1,776 and complete teardown passed. | Baseline `9757734924`, 6,914,474 B, SHA-256 `0ca62ac387ba0e10a5d01182d1c4acd0314091d63bb7c9dd8231e63244ccb3e9`; TechDraw `9757503040`, 601,451 B, SHA-256 `7203aafa1f67565003c3c181b77be073908a8a425bd7da7db128a77d40b45c45` |
| Windows `33384592193` | **Success.** 1,432 enabled CTests, locked Mesa/OpenGL 3.0 positive probe, TechDraw, CLI 1,674 and GUI 1,776 passed with clean graphics logs and teardown. | Baseline `9759839393`, 7,200,974 B, SHA-256 `beecb9ddb504b37b8a30bf4a3c59129e3d15a3aab069dfe19fd7c2b444436309`; TechDraw `9759439722`, 681,518 B, SHA-256 `75274b1ee59e1ae9b4c588665359d0da9626a95cf40c70de72226a7db046ac32` |
| macOS arm64 `33384592174` | **Failed only after successful GUI tests.** Build, 1,430 CTests, TechDraw, CLI 1,674 and GUI 1,776 `OK` passed, then process exited 1 after MainWindow destructor body end and before `run-returned`. | Baseline `9758211299`, 6,898,461 B, SHA-256 `6eb96902b458e7f2708878b759fe6b59e0703e74973ca8b833c558d02c831c6a`; TechDraw `9758013054`, 594,566 B, SHA-256 `d8f98282b939f01cd6ce1c8d447dcbde5681ac6693a6cdf4d2950732f6804388` |
| macOS x86_64 `33384592174` | **Same teardown-only failure.** 1,430 CTests, TechDraw, CLI 1,674 and GUI 1,776 `OK` passed before the identical boundary. | Baseline `9759775856`, 6,907,640 B, SHA-256 `79ee270d4563875b9d93838cd47245f9f9945a5b1a83e8dea019aed8de6bc6ee`; TechDraw `9759355332`, 594,575 B, SHA-256 `a68d2756dc2f64160b1b898c1fe14444928abed731aef8da6c8924fec4938c24` |
| Security `33384592150` | Restricted guards, locked audit and all CodeQL jobs passed. Dependency Review alone failed because Dependency Graph is disabled. Lock artifact `9755067638`, 170,355 B, SHA-256 `6b7356f037e5dbf451ccadee64f162ae02d2af59375cf6a7d8257ca5478e60ee`, expires 2026-09-14. | No other artifacts |
| Packaging `33384592155` | **Success.** Policy suite 53/53. | None |

## Superseded partial rerun at base head `fc7052f9`

Security run `33401416385` passed restricted-asset quarantine, locked metadata,
and CodeQL for C/C++, Python, and Actions. Dependency Review alone failed on
the unchanged disabled-Dependency-Graph blocker; lock artifact `9761380724` is
170,356 bytes with SHA-256
`de5502957da3fa3749a3f7b63551e7a3af75e8d8371c34f7f9f2984834fb72e7`.

macOS arm64 job `99518932720` built successfully and passed 1,430 of 1,431
enabled CTests. The sole failure was `OpenFusion_GUI_HeadlessVersion`: the
version-only process returned through the new parser but the eager global
3Dconnexion initializer had already written a missing optional-framework error
to stderr. The lifecycle test itself passed in 25.14 s. Baseline artifact
`9764761228` is 592,504 bytes with SHA-256
`3c8222855877bfdd5d9ef8f6e7ec4cb213043b9b24ff3376eb3c62fff1aeda8c`.
The local lazy-load fix above addresses that exact failure; this partial run did
not reach the full GUI teardown gate and is not a macOS pass.

## Active blockers

1. Native macOS arm64/x86_64 must validate headless version output, explicit
   owned-QMdiArea destruction, and complete teardown at the new head. No stderr
   suppression, skipped gate, or exit-code masking is acceptable.
2. Repository owner must enable Dependency Graph and close issue #32 with a
   passing Dependency Review run.
3. Issue #24's untrusted FCStd/XML/archive atomic-restore architecture remains
   open; the rejected destructive preflight prototype is not merged.
4. Production package trust requires reviewed SPKI/key custody, artifact
   signing/notarization, runtime dependency closure, final runtime SBOM,
   clean-machine install/workflow/uninstall, and downloaded-release verification.
5. The Design workspace selector is implemented locally; native matrix proof,
   context strip, Project presentation, graph-backed timeline, consolidated
   settings and remaining product workflows are open.

## Resume sequence

1. Re-fetch the connector-fast-forward created with this update; record its
   exact resulting SHA/tree and fresh run IDs on PR #28.
2. Keep the PR draft. Retrieve every native/log/artifact result; queued,
   cancelled, skipped, build-only or Linux-only evidence is not a pass.
3. If macOS passes, advance to clean-machine runtime/package closure and the
   M1 Design workspace spine. If it fails, fix the exact retained boundary.

## Update rule

After every substantial iteration, replace stale state here with exact SHAs,
trees, commands, counts, failures, skips, artifacts, blockers and next action.
Never predict a connector-created state-update SHA.
