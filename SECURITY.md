# OpenFusion Security Policy

OpenFusion treats CAD documents, archives, meshes, drawings, scripts, addons,
post-processors, solver inputs, and imported files as potentially untrusted.
We welcome responsible reports about vulnerabilities in OpenFusion code,
packaging, CI, dependencies, or inherited FreeCAD behavior.

## Supported versions

OpenFusion has no production release and no supported binary version yet.

| Version | Security support |
|---|---|
| `main` foundation/pre-alpha | Best-effort investigation; not production-supported |
| OpenFusion binary releases | None published |
| FreeCAD releases | Report through the [FreeCAD security policy](https://github.com/FreeCAD/FreeCAD/security/policy) |

The absence of a supported OpenFusion release does not reduce the importance of
responsible disclosure. Fixes may be developed on `main` and proposed upstream
when the affected code is inherited and a shared fix is appropriate.

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting flow:

<https://github.com/PLASMA-FR/openfusion/security/advisories/new>

Do not file a public issue for a vulnerability or include sensitive proof of
concepts, malicious files, credentials, or personal data in public discussions.
If GitHub reports that private vulnerability reporting is unavailable, contact
a repository maintainer through a non-public channel and ask for a secure
reporting path without disclosing technical details publicly.

Include, when safe and available:

- the affected revision, platform, build type, and dependency environment;
- the attack surface and required user interaction;
- reproducible steps or a minimal non-sensitive test case;
- expected and observed behavior;
- potential confidentiality, integrity, availability, or user-data impact; and
- suggested mitigations or related upstream reports.

Use synthetic data. Never include secrets or a real user's proprietary CAD
files. If a reproducer itself is dangerous, describe it first and wait for a
maintainer to arrange safe transfer.

## Response process

Maintainers will attempt to acknowledge a private report, reproduce and
classify it, coordinate with affected upstream or dependency maintainers, and
prepare a regression test and fix. Response time is best effort during the
pre-alpha phase; no service-level agreement or bounty program is currently
offered.

Please allow coordinated remediation before disclosure. A report may be
classified as an OpenFusion regression, inherited FreeCAD issue, external
dependency issue, platform issue, or unsupported configuration. That
classification does not justify ignoring a reproducible risk.

## Security release gates

Before an OpenFusion binary release is supported, the project must document and
review at least:

- untrusted file and archive parsing, including path traversal and entity
  resolution;
- temporary files, permissions, Unicode and long paths, and external process
  invocation;
- Python execution, macros, addons, post-processors, URL handlers, and plugin
  loading boundaries;
- dependency provenance, license inventory, hashes, SBOMs, and known
  vulnerabilities;
- least-privilege, pinned CI workflows and secret handling;
- compiler and linker hardening appropriate to each platform; and
- tested update, installer, uninstall, crash-recovery, and diagnostic paths.

Telemetry and crash upload must remain off unless a future implementation uses
clear informed opt-in and documents exactly what is collected and transmitted.

## Scope boundaries

FreeCAD websites, forums, infrastructure, and official FreeCAD binaries are not
operated by OpenFusion. Report issues affecting those systems to the FreeCAD
project. Vulnerabilities in a third-party dependency may also need coordinated
reporting to that dependency's security team; OpenFusion maintainers can help
route an inherited finding without claiming ownership of the upstream system.

