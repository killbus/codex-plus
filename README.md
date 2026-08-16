# codex-plus

An unofficial, CLI-only Codex build assembled from auditable source snapshots.

## Rebuild states

```text
official bb6a127b... (pristine)
  -> patches/goal-old-continuation.patch (goal-only)
  -> patches/goal-transient-continuation.patch (integrated Goal behavior)
  -> patches/shadow-mind.patch (future integrated shadow extension)
```

`codex-src/` is the current integrated working tree. The goal-only state is
recreated in a temporary directory by `scripts/verify_provenance.py`; no nested
Git repository is required.

The Goal matrix continues only transient network failures: overloaded responses,
connection/stream failures with no status, HTTP 429, or HTTP 5xx. Usage limits,
budgets, authentication, bad requests, sandbox/configuration errors, and
unattributed internal failures remain terminal. Three consecutive transient
failures trip a local stop instead of looping forever.

The first release target is a Windows x64 CLI archive. It does not contain VSIX,
desktop, marketplace, or official OpenAI branding. Build hashes document source,
patches, lockfile, toolchain, and artifact integrity; they do not claim publisher
identity or byte-identical deterministic binaries.

See [docs/decisions.md](docs/decisions.md) and
[docs/provenance.json](docs/provenance.json) for the recorded evidence.
