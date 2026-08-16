# CLI release pipeline — 技术设计

The workflow checks out the repository, validates the integrated tree manifest and
patch hashes, installs Rust `1.95.0`, runs scoped tests, and builds `codex-cli` for
Windows x64. It stages an allowlisted directory, copies license/notice/trademark
files, writes BUILD-INFO, computes SHA-256, verifies the allowlist, then uploads one
archive and its checksum to the release channel.

The workflow never references the source VSIX workflow or its download URL. Release
permissions are read-only checkout plus release upload. A failed test, build,
allowlist, or checksum exits before publication.
