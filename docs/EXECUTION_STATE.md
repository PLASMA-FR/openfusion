# OpenFusion Execution State

**Last verified:** 2026-08-31 UTC
**Production-ready:** No
**Active milestones:** M0 native baseline closure and first M1 product slices
**Next task:** Publish the reviewed local candidate, re-fetch its exact connector
SHA/tree, keep PR #28 draft, and retrieve Linux, Windows, macOS arm64, macOS
x86_64, and Security. Native results must prove the Windows single-renderer
probe and macOS MDI teardown fix without weakening or skipping a gate.

This file is the resumable source of execution truth. Local Linux evidence is
not native Windows/macOS proof, an inherited FreeCAD feature is not an
OpenFusion product feature, and a build-tree binary is not an installed package.

## Source state

| Item | Verified value |
|---|---|
| Foundation | FreeCAD 1.1.3, `145529fe741292ff0b3977a01195bf0247425794` |
| Remote integration head before this update | `bf4f3e2378d0209aba81d7efe0d2ba3c2ebce810`, tree `2c14fca8d639d6c30f9f58fdcbbf4f3b1f7ed5fd` |
| Local reviewed candidate | `860670be4362f97a3efdc8d390a9e891a6b2b9c2`, tree `d2020553a3c02416bb1659e0ea03643ad026e624`, plus this truth update |
| Branch / PR | `integration/acceptance-ci`; draft PR #28; final connector SHA is intentionally not predicted here |
| Dependency lock | `pixi.lock`, SHA-256 `114a173c4f57dfc0caa4ec0f559b0ec1a7a0f762a04475b5131dca12e2683edc` |

## Integrated candidate changes

| Commit | Change |
|---|---|
| `9cffb16ddc` | Bind Windows GUI tests to one locked Mesa renderer, verify Conda/Pixi provenance, loaded module path/hash and GL context, and validate logs before propagating failures. |
| `cd0ac8d110` | Disconnect the MDI activation callback before `MainWindow` derived state is destroyed; add a six-live-window shutdown scenario. |
| `9e0951fc73`, `1682e148db` | Add and harden the native `Ctrl+K` command palette over real `CommandManager`/`QAction` state, including deterministic fuzzy search, recency, disabled state, focus, accessibility, and single activation. |
| `0954363dbd` | Add deterministic, fail-closed Linux `tar.zst` packaging policy and 53 focused tests; production output still requires the executable identity contract. |
| `eaf6a61fca`, `860670be43` | Remove/quarantine 32 restricted pattern assets and the inherited thumbnail DLL; keep material/thumbnail guards non-vacuous and recursive. |
| `748f605e34`, `b51f73254a`, `4b12ba83eb` | Add deterministic locked-dependency audit/SPDX inventory and preserve pull-request plus merge-queue Dependency Review. |

## Exact local Linux arm64 evidence

Environment: Ubuntu 24.04 arm64, 2 CPUs, Clang 21.1.0, CMake 4.2.1,
Ninja 1.13.2, Python 3.11.14, Qt 6.8.3, locked Pixi environment.

| Gate | Result |
|---|---|
| Combined Release build | CMake reconfigure plus complete 346/356-edge warm graphs passed; all new C++ translation units and linked targets built warning-clean. |
| Command palette | Linked Qt test 1/1 passed in 0.12 s; follow-up run confirmed no missing-icon diagnostic. |
| GUI lifecycle focus | Command palette plus six-scenario process lifecycle: 2/2 passed; lifecycle 24.41 s with exact exit codes, lock cleanup, Python finalization, MDI children, event-loop return, and teardown. |
| Full CTest | 1,436 registered; 1,430 enabled; zero failed; three skipped; six disabled; four acceptance tests; 107.99 s. |
| CLI suite | 1,674 ran; 10 skipped; zero failures; parser count 1,674; 157.861 s. |
| GUI suite | 1,776 ran; zero failures; parser count 1,776; exact exit 0; MainWindow, application, and process teardown complete; 439 s. |
| TechDraw GUI export | 1/1 passed in 2.62 s; SVG 13,163 bytes; PDF 297,380 bytes; exact exit 0. |
| Windows runtime/graphics helpers | 31/31 passed; locked renderer source/destination SHA-256 is checked and the native probe is fail-closed. |
| Linux packaging policy | 53/53 passed; production CLI remains blocked until authenticated executable identity exists. |
| Legal quarantine | Material 22/22, thumbnail 18/18, and live 32-identity source/index guard passed. |
| Dependency audit | 30/30 passed; two real-lock runs were byte-identical: 1,539 packages, 1,844 platform references. |
| Static gates | Black, Python compilation, Actionlint, workflow YAML, CR-aware diff, conflict-marker, and focused secret scans passed for the reviewed slices. |

## Last terminal native matrix

Head `3f961895a3eb0017ee94201395a2c8782ddad1e5`; all artifacts expire
2026-09-30.

| Platform / run | Terminal result | Artifacts |
|---|---|---|
| Linux `33363811020` | Passed build, 1,427 CTests, TechDraw, 1,667 CLI, and 1,769 GUI tests with orderly exit. | Baseline `9750186214`, SHA-256 `531ed6a131dab28e2b898039a5ce59932524d518eb706fced7a5b2efbcac8972`; TechDraw `9750003836`, SHA-256 `c431237a65cadb0c1ef5786b5bf260e12dff7c8387af7e393e8bafc1a9c15a77` |
| Windows `33363810971` | Build, helper, all 1,429 CTests, TechDraw, and 1,667 CLI passed. Full GUI ran 1,769 tests with 59 OpenGL 1.1/context access-violation errors. | Baseline `9752389917`, SHA-256 `e3961e1ce8e859283e10f0a1e08e118da13d810021725788384f59b8c3fd880b`; TechDraw `9752179141`, SHA-256 `94d71dce24d1a64b2842b6828e771fb4241e8a38b94e7423ccfcb27e8326cad6` |
| macOS arm64 `33363811070` | Build, 1,427 CTests, TechDraw, CLI, and 1,769-test `OK` result passed; process exited 1 while unwinding after selected code 0. | Baseline `9750200075`, SHA-256 `85a31a42d726ed04b2371139e60d120a0363e368b315f05b8cc4fabe32675f53`; TechDraw `9750017210`, SHA-256 `ea15f430614070d90603c88f47fabc144218b50c0575c603552b53428f1f4f1b` |
| macOS x86_64 `33363811070` | Same full-GUI-teardown-only failure after all pre-GUI gates and successful unittest result. | Baseline `9752565135`, SHA-256 `a4c582af8afcb5ae8ffeafb5b7eab940ff429ec3a4cabc8d4f0c09c83dc66c6e`; TechDraw `9752126729`, SHA-256 `e3965a5a8c149d881f97ba483972a0d2e511bcf7a373bf3642e767546f0cf94a` |
| Security `33363810919` | All three CodeQL jobs passed. Dependency Review alone failed because repository Dependency Graph is disabled. | None |

The intermediate diagnostic head `bf4f3e2` has runs `33379568379` (Linux),
`33379568373` (Windows), `33379568381` (macOS), and `33379568387`
(Security). They were still building/analyzing at the last snapshot and are not
accepted as passes; the final candidate supersedes them.

## Active blockers

| Priority | Blocker | Exit condition |
|---|---|---|
| P0 | Native baseline | Final-head Linux, Windows, macOS arm64, and macOS x86_64 jobs pass every unchanged gate with retained logs/artifacts. |
| P0 | Dependency Review | Repository owner enables Dependency Graph and a fresh Dependency Review job passes; CodeQL/lock audit do not substitute. |
| P0 | Untrusted FCStd/XML/archive input | Issue #24's immutable named-entry source, strict semantic participants, safe prepare/commit/abort architecture, and adversarial regressions are completed. The rejected preflight/double-load prototype is not merged. |
| P0 | Packages | Authenticated OpenFusion executable identity, final package SBOM/checksums, clean install/start/workflow/uninstall, signing/notarization, and downloaded-release verification pass. |
| P0 | Legal/provenance | Final source archives, LFS storage, staging trees, and package payloads are inspected; missing icon/branding provenance and cleared replacements are resolved. |
| P1 | Product | Command palette is implemented. Workspace selector/context strip, Project presentation, graph-backed timeline, consolidated settings, and remaining target workflows still require implementation and acceptance. |

## Resume sequence

1. Commit this truth update and create the connector commit on top of
   `bf4f3e2378d0209aba81d7efe0d2ba3c2ebce810` without force.
2. Re-fetch and comment the exact resulting head/tree and fresh run IDs; keep
   PR #28 draft.
3. Retrieve every terminal job, exact failed step, log, and artifact. Do not
   call queued, cancelled, skipped, build-only, or Linux-only evidence a pass.
4. Fix root causes and repeat affected native gates without relaxing tests.
5. In parallel, finish executable identity/package installation and the M1
   workspace spine; neither can substitute for M0 native closure.

## Update rule

After each substantial iteration, replace stale state here with exact SHAs,
trees, commands, totals, failures, skips, platform/toolchain, artifacts,
blockers, and next action. Never predict a connector-created state-update SHA.
