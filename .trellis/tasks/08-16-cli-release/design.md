# CLI release pipeline — 技术设计

The workflow checks out the repository, validates the integrated tree manifest and
patch hashes, installs Rust `1.95.0`, runs scoped tests, and builds `codex-cli` for
six native targets: Windows x64/ARM64, macOS x64/ARM64, and Linux musl x64/ARM64.
Every row declares its check profile: Windows/macOS use dev, while musl uses the
source-proven release profile for full Goal/Shadow tests and app-server check.
The final CLI build alone overrides Cargo release debug info to `none` and strip
mode to `symbols`, because the workspace release profile intentionally leaves
symbols for upstream packaging while this CLI-only workflow emits no symbols
artifact. The finalized binary is smoke-tested before staging.
Each job stages an allowlisted directory, copies license/notice/trademark files,
writes BUILD-INFO, computes SHA-256, verifies both positive and negative allowlist
cases, then uploads one platform archive and its checksum. A dependent audit job
downloads all six artifact bundles, rejects missing or extra platforms/paths, and
recomputes both the ZIP and embedded binary checksums while validating BUILD-INFO.

Provenance is byte-stable across runners. Repository attributes keep copied source,
patches, and the recorded manifest on LF. The verifier reads upstream symlink modes
and targets from Git objects, canonicalizes only the rebuilt checkout, preserves
the flattened source file as an explicit materialization difference, and sorts
normalized path strings inside the digest so Windows `Path` ordering cannot change
tree hashes. Stale output names differing fields. Network fetch/download operations
retry transient failures; patch, manifest, checksum, and allowlist mismatches fail
immediately.

The musl contract follows the complete source release sequence rather than only its
Cargo profile: it derives rusty_v8 `149.2.0` from the copied source, downloads the
matching archive, bindings, and checksum manifest from the official Codex release,
verifies both files, and exports Cargo's two override paths. This avoids denoland's
missing aarch64-musl asset without narrowing Goal or Shadow coverage.

Release permissions are read-only checkout plus artifact read/write through the
GitHub Actions runtime. A failed test, build, allowlist, or checksum exits before
the workflow succeeds.
