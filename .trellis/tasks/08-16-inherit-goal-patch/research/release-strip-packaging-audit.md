# Research: Release strip and packaging audit

- Query: Why are the CLI release binaries/archives 1 GiB+, and what upstream packaging contract is missing?
- Scope: mixed
- Date: 2026-08-17

## Findings

### Root cause

The workflow uploads only a ZIP and checksum, not Cargo's `target/` tree, so this is
not an `upload-artifact` glob mistake. The oversized bytes originate in the binary
copied into the stage: `.github/workflows/cli-release.yml:194-212` builds and smoke
tests the raw Cargo release binary, then copies it directly; `:243-253` compresses
and uploads that stage.

That raw binary is deliberately not a distribution-ready binary. The vendored
release profile keeps line-table debug information, disables split debug info, and
sets `strip = false` (`codex-src/codex-rs/Cargo.toml:539-545`). Its comment says
packaging must archive sidecar symbols and strip the binaries. The local workflow
copied the upstream Cargo build but omitted that post-build packaging phase.

This is the Ponytail/first-principles lesson: the deliverable contract is the bytes
after the complete upstream release pipeline, not the output of the last familiar
build command. A release profile can intentionally produce an intermediate with
diagnostic material; inspect every transformation between build and publication.

### Exact upstream semantics

- macOS sets `CARGO_PROFILE_RELEASE_SPLIT_DEBUGINFO=packed` so Cargo produces dSYM
  bundles (`codex-src/.github/workflows/rust-release.yml:69-72`). The symbol helper
  copies each dSYM, then mutates the product binary with `strip -S -x`
  (`codex-src/.github/scripts/archive-release-symbols-and-strip-binaries.sh:67-83`).
- Linux extracts a `.debug` sidecar with `objcopy --only-keep-debug`, runs
  `strip --strip-debug --strip-unneeded`, then adds the `.gnu_debuglink` back to the
  product binary (`archive-release-symbols-and-strip-binaries.sh:85-99`).
- Windows debug data is a PDB sidecar. The helper archives the PDB and does not
  strip/mutate the EXE (`archive-release-symbols-and-strip-binaries.sh:101-110`).
  Upstream's build stage explicitly carries EXE and PDB (`rust-release-windows.yml:
  116-142`), while the final product stage copies only EXEs (`:263-272`).
- On Unix, upstream runs the helper immediately after Cargo build and before
  staging/signing/package construction (`rust-release.yml:238-287`, `:289-348`).
  Therefore all downstream hashes/signatures/archives cover the transformed bytes.

### Selected patch shape

Keep the source profile unchanged. This CLI-only workflow deliberately publishes no
symbols artifact, so its final CLI build uses Cargo's supported workflow-local
`CARGO_PROFILE_RELEASE_DEBUG=none` and `CARGO_PROFILE_RELEASE_STRIP=symbols`
overrides. This applies the upstream pipeline's final symbol-removal intent without
creating dSYM/PDB/`.debug` sidecars only to discard them. Goal/Shadow tests and the
app-server check keep their existing profiles; the resulting CLI is smoke-tested
before staging and hashing.

No numeric binary/archive threshold is used. The existing exact six-file allowlist
continues to exclude PDB/dSYM/`.debug` sidecars, and the dependent audit continues to
verify hashes and exact ZIP paths. `tests/test_release_workflow.py` scopes the two
overrides to the unconditional final CLI build and proves they do not leak into the
three validation steps.

## Files Found

- `.github/workflows/cli-release.yml` - current six-target build, stage, checksum, upload, and audit flow.
- `codex-src/codex-rs/Cargo.toml` - release profile intentionally retains symbolication data.
- `codex-src/.github/workflows/rust-release.yml` - upstream macOS/Linux build-to-strip-to-stage ordering.
- `codex-src/.github/workflows/rust-release-windows.yml` - upstream PDB separation and EXE-only final stage.
- `codex-src/.github/scripts/archive-release-symbols-and-strip-binaries.sh` - authoritative per-target symbol/strip operations.
- `scripts/check_release_allowlist.py` - exact product-stage allowlist already rejects sidecars.
- `scripts/audit_release_artifacts.py` - downstream exact-path and two-layer checksum audit.
- `tests/test_release_workflow.py` - static release contract tests to extend.

## External References

- Rust/Cargo toolchain is pinned to 1.95.0 by `.github/workflows/cli-release.yml:60-64`.
- Cargo profile reference (`debug`, `split-debuginfo`, `strip`): https://doc.rust-lang.org/cargo/reference/profiles.html
- Evidence is based on vendored upstream source at provenance commit
  `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb` (`docs/provenance.json:24`).

## Related Specs

- `.trellis/spec/backend/quality-guidelines.md` requires the complete upstream native
  build sequence and exact staged allowlist, but should be updated after implementation
  to state that packaging finalization precedes smoke tests, hashes, and upload.
- `.trellis/spec/guides/cross-platform-thinking-guide.md` already warns to compare
  the complete upstream sequence rather than only the Cargo profile/command.

## Caveats / Not Found

- No large artifact was downloaded and no local Rust command was run.
- The current run's actual binaries were not available locally, so this audit proves
  the missing transformation from source/workflow contracts rather than measuring a
  particular run.
- Research-role isolation prohibited reading `implement.jsonl` and `check.jsonl`;
  PRD, design, implementation plan, specs, workflows, scripts, and tests were read.
- Numeric size limits were intentionally excluded per user direction.
