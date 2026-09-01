# OpenFusion Windows portable development package

The Windows baseline workflow creates a deterministic, unsigned portable ZIP
after all native tests pass. Its name is:

```text
OpenFusion-<version>-Windows-x86_64-unsigned.zip
```

The archive contains the CMake-installed OpenFusion product plus only runtime
files owned by packages in the active locked Pixi environment. The packager
structurally parses the locked `win-64` closure, rejects credentialed or
stateful URLs, downloads every package into a SHA-addressed cache, authenticates
the archive bytes by locked size/hash, and derives ownership only from the
archive's immutable `info/index.json` and `info/paths.json`. Prefix-relocated
files are reconstructed from authenticated payload bytes before comparison. It
parses PE32+ import and delay-import tables and resolves every dependency to
the package `bin` directory or an explicit System32/API-set policy.

The completed ZIP is checked by the same authoritative legal verifier used by
Linux: all 32 FCMat identities, exact notices, ARR metadata, LFS pointers, and
thumbnail-provider text, GUID, path, and hash identities. Windows paths also
reject NFKC/casefold aliases, trailing dots/spaces, DOS devices, alternate
separators, reparse points, junctions, and anchor escapes. Manifest schemas,
ZIP flags/comments/extras, member order, PE evidence, and relocation paths are
exact, local System32/ApiSet shadows are forbidden, the Windows Server 2022
host's version-6 `ApiSetSchema.dll` contract set is parsed and bound into the
manifest, and existing output paths are never replaced.

CI extracts the ZIP with the Pixi/Conda environment removed, then exercises
the shipped `.cmd` launchers, packaged Python, `_ssl`, OpenSSL configuration and
provider directory, PySide/Qt offscreen, a real `qwindows` desktop OpenGL context
with exact app-local module/hash evidence, and a Part document save-close-reopen
round trip. PE import closure covers load-time and delay-load tables; dynamic
coverage claims are limited to those explicitly exercised plugins and the
locked helper set actually shipped on Windows (`ccx`, `dot`, and `unflatten`).
OpenSSL uses its built-in default provider with an original app-local config;
no external legacy provider is claimed. Download the GitHub Actions artifact
whose name starts with `OpenFusion-Windows-x86_64-portable-unsigned`, extract
it, and launch `OpenFusion.cmd` or `bin\OpenFusion.exe`.

This is an unsigned development artifact, not the required production NSIS
installer. Production remains blocked on OpenFusion installer branding,
Authenticode credentials, timestamping, silent install/uninstall acceptance,
and release-key custody. The `unsigned` marker must not be removed or renamed
until those gates pass.
