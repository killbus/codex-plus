# Cross-Platform Thinking Guide

> **Purpose**: Catch host-dependent source, toolchain, and artifact assumptions
> before a native runner matrix exposes them.

## Before Editing Cross-Platform CI

- [ ] Identify which inputs are compared as raw bytes and pin their checkout EOL.
- [ ] Inspect Git object modes, not only the working tree; Windows may materialize
      a symlink as a regular file containing its target name.
- [ ] Sort normalized string keys at manifest/hash boundaries; Windows `Path`
      ordering is case-insensitive even when every file byte is identical.
- [ ] Keep source-materialization evidence separate from normalization used to
      compare a rebuilt upstream tree.
- [ ] Verify whether native dependencies support the same Cargo profile on musl;
      change the declared profile rather than narrowing regression coverage.
- [ ] Compare the complete upstream native build sequence, including prebuilt
      artifacts and checksum overrides, not only the final Cargo command/profile.
- [ ] Read the Cargo profile comments and every post-build packaging step: a
      `--release` binary may still be a symbol-bearing intermediate. For a
      CLI-only distribution with no symbols artifact, apply symbol removal only
      to the final build instead of adding a numeric size gate.
- [ ] Configure retries where network clients run so 429, 5xx, timeout,
      disconnect, and connection failures survive. Patch, manifest, checksum,
      and allowlist mismatches remain deterministic failures.
- [ ] Run each target on its declared native architecture and audit the downloaded
      artifact set after all matrix jobs complete.

## Evidence Checklist

- [ ] Unit tests cover native and placeholder symlink checkouts.
- [ ] Manifest digest tests prove dictionary/path iteration order cannot change a
      tree hash, and stale diagnostics name the differing contract fields.
- [ ] Static tests assert every matrix target, runner, binary, and check profile.
- [ ] The fixed source/patch/toolchain hashes remain unchanged unless the input
      contract intentionally changes.
- [ ] Musl-native prebuilt inputs are source-version matched and checksum verified.
- [ ] A successful matrix is followed by checksum and exact-path artifact audit.

See [Backend Quality Guidelines](../backend/quality-guidelines.md) for the
executable release and provenance contracts.
