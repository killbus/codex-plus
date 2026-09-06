# codex-plus

An unofficial, CLI-only Codex build assembled from auditable source snapshots.

## Rebuild states

```text
official rust-v0.153.4 / 3d2ee51c... (pristine)
  -> patches/goal-old-continuation.patch (goal-only, deterministic three-way apply)
  -> patches/shadow-mind.patch (integrated Goal/Shadow compatibility delta)
```

`codex-src/` is the current integrated working tree. The goal-only state is
recreated in a temporary directory by `scripts/verify_provenance.py`; no nested
Git repository is required.

The complete upstream `rust-v0.153.4` release is the authoritative baseline.
The fork delta ports only its existing Goal continuation and Shadow integration,
plus the compatibility glue those responsibilities require. The inherited Goal
behavior remains the final contract: a terminal turn error
other than `UsageLimitExceeded` leaves the Goal active so the idle lifecycle can
start another turn. This includes exhausted reconnects, dropped response streams,
HTTP 429, and HTTP 5xx, with no consecutive-failure circuit breaker. Shadow is
layered directly on that behavior and does not replace it with a narrower error
matrix.

The immutable Goal patch is applied with its recorded preimage commit, while the
Shadow patch is regenerated against the resulting `0.153.4` Goal-only state.

The release workflow uses Rust `1.95.0` and native GitHub runners for Windows
x64/ARM64, macOS x64/ARM64, and Linux musl x64/ARM64. Each platform produces a
CLI archive containing only its binary, attribution, provenance, and checksum
files. A final job downloads all six archives and independently rechecks the ZIP,
binary, allowlist, target, toolchain, and provenance records. Linux uses the pinned
musl toolchain dependencies from the source build practice, including the
source-matched official Codex `rusty_v8` archive and binding after verifying their
published checksums. Build hashes document source, patches, lockfile, toolchain,
and artifact integrity; they do not claim publisher identity or byte-identical
deterministic binaries.

See [docs/decisions.md](docs/decisions.md) and
[docs/provenance.json](docs/provenance.json) for the recorded evidence.
