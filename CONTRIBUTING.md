# Contributing to OpenFusion

OpenFusion is an incremental, compatibility-conscious evolution of FreeCAD.
Contributions should improve real CAD workflows while protecting geometry
correctness, user data, licensing obligations, and the ability to review
upstream changes.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in
this document are used as described by RFC 2119.

## Before starting

1. Read [ARCHITECTURE.md](ARCHITECTURE.md), [ROADMAP.md](ROADMAP.md),
   [TESTING.md](TESTING.md), and [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
2. Search existing issues and pull requests before opening a duplicate.
3. For substantial behavior, persistence, dependency, or architecture changes,
   open an issue or design discussion first.
4. Identify whether the problem is an OpenFusion regression, an inherited
   FreeCAD issue, an external dependency issue, a platform issue, or an
   intentionally unsupported capability.
5. Report suspected vulnerabilities through the private process in
   [SECURITY.md](SECURITY.md), not a public issue.

Help requests and upstream FreeCAD questions are best directed to the
[FreeCAD community resources](https://www.freecad.org/community.php). OpenFusion
issues should contain enough information to reproduce a problem without
requiring readers to consult a separate conversation.

## Contribution principles

- Submit one focused, reviewable change per pull request.
- Prefer reuse of stable FreeCAD functionality and small migration seams over
  duplicated geometry, document, selection, command, or persistence state.
- Do not add a visible production command unless it works. Experimental
  behavior must be labeled and must fail safely.
- Preserve FCStd and Python/addon compatibility unless an approved migration
  explicitly documents the break and its recovery path.
- User-visible model changes MUST participate correctly in transactions,
  recompute, undo/redo, save, close, and reopen.
- Do not substitute screenshots, mock data, disabled tests, or skipped release
  gates for working behavior.
- Do not add telemetry or network communication without an approved design,
  informed opt-in, data minimization, and security review.
- Avoid unrelated formatting or mechanical churn, especially in inherited
  upstream files that may receive future FreeCAD updates.

Changes that also make sense in FreeCAD should be structured so they can be
proposed upstream when practical. Preserve upstream authorship when carrying or
adapting a patch.

## Development setup

Initialize all submodules, then use the locked dependency environment or a
documented native toolchain:

```bash
git submodule update --init --recursive
pixi install --locked
pixi run configure-debug
pixi run build-debug
pixi run test-debug
```

See [BUILDING.md](BUILDING.md) for supported compiler baselines and native
platform instructions. Never mix incompatible dependency environments in one
build directory.

## Tests and evidence

Every pull request MUST describe the exact commands run and their results.
Select evidence based on risk:

- C++ and Python unit tests for changed logic;
- regression tests for every significant bug fix;
- document load/save, recompute, and undo/redo tests for modeling changes;
- relevant GUI and keyboard/focus tests for interface changes;
- representative import/export round trips for format changes;
- before/after measurements for performance-sensitive changes; and
- clean packaged-artifact installation and launch tests for packaging changes.

Run formatting and lint checks applicable to changed files, inspect the final
diff, and remove debug output and generated artifacts before committing. A
passing compile alone is not sufficient evidence. If a required test cannot be
run, state that limitation prominently; do not report it as passed.

## Pull requests and commits

- Work on a focused branch and open a pull request against `main`.
- Keep `main` buildable; do not push feature work directly to it.
- Each commit SHOULD compile with its preceding commits and explain one
  coherent change.
- Use concise conventional subjects where useful, for example
  `fix(document): reject unsafe external entities` or
  `feat(ui): add contextual command search`.
- Include screenshots or recordings for visible UI changes, but pair them with
  functional test evidence.
- Call out persistence, undo/redo, dependency, platform, performance, security,
  accessibility, localization, and addon-compatibility effects.
- Link the issue being resolved and update `CHANGELOG.md`, `ROADMAP.md`,
  `docs/GAP_ANALYSIS.md`, or `KNOWN_ISSUES.md` when the change affects them.

Maintainers may request that broad work be split into smaller pull requests.
Release and security gates are not waived merely because a bug exists in the
upstream baseline.

## Licensing, provenance, and original assets

This repository contains code and assets under multiple licenses. The root
[LICENSE](LICENSE), file headers, module metadata, and third-party notices all
apply. Contributors retain copyright in their work unless they separately
assign it; OpenFusion currently requires no copyright assignment.

Contributions MUST:

- use a license compatible with the file and repository context;
- preserve existing copyright, attribution, and license headers;
- identify the source, author, license, and modifications for third-party
  material;
- avoid adding a dependency or asset until its redistribution and binary
  packaging terms have been reviewed; and
- be the contributor's original work or material they are authorized to
  contribute under compatible terms.

Do not submit proprietary CAD application source, extracted resources, icons,
logos, binaries, artwork, confidential information, or material obtained by
circumventing technical protections. Publicly observable workflow patterns may
inform interoperability and usability work, but OpenFusion implementation and
assets must be original.

## Conduct

Be precise, constructive, and respectful. Technical disagreement is expected;
personal attacks, harassment, discrimination, and attempts to obscure safety
or licensing concerns are not acceptable. Maintainers may moderate discussions
or contributions that prevent productive, inclusive collaboration.

## Upstream credit

OpenFusion exists because of the work of FreeCAD's contributors and ecosystem.
Do not remove their credits or imply that inherited work was authored by
OpenFusion contributors. Relevant FreeCAD contributor records remain under
`src/Doc/` and in the repository history.
