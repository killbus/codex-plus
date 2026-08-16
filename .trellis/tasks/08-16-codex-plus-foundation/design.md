# codex-plus 发行版地基 — 技术设计

## Tree model

```text
official commit bb6a127 (pristine)
  -> goal-old-continuation.patch (goal-only compatibility baseline)
  -> shadow-mind.patch (integrated extension; Goal behavior unchanged)
```

The repository stores the integrated `codex-src/`. A small provenance script
rebuilds the other two states in temporary directories and compares ordered file
manifests plus SHA-256 hashes. The source snapshot's lockfile and Windows
symlink/materialization differences are explicit inputs, not hidden exceptions.

## Extension boundary

`ext/shadow` owns registry parsing, scheduler, per-thread state, report batching,
and management tools. The host exposes a narrow `AgentSpawner` capability for
creating a non-recursive child thread with a snapshot of model, cwd, permissions,
and sanitized trajectory. The capability returns cancellation and completion
handles; timeout, turn abort, thread stop, and new user turn cancel old runs.

The lifecycle implementation uses `on_thread_idle` as the single heartbeat edge.
`on_turn_error` and `on_turn_stop` only mark the turn complete and cancel stale
runs. A per-thread `last_scheduled_turn_id` makes duplicate lifecycle delivery a
no-op.

Reports carry the source `turn_id`/epoch. The host's injection method checks the
expected turn while holding the active-turn/input-queue lock; a stale report is
discarded before enqueue. This is stronger than checking the id before calling
`inject_if_running`.

## Goal error boundary

The inherited patch is both the auditable compatibility baseline and the final Goal
policy. Its `on_turn_error` handler returns for every error except
`UsageLimitExceeded`, leaving the Goal Active for the idle lifecycle to continue.
The integrated tree does not add a second classifier, protocol mapping dependency,
or consecutive-failure counter.

`shadow-mind.patch` has no Goal-file hunks and applies directly to the goal-only
tree. Its app-server integration coverage owns the cross-feature proof that a real
post-handshake stream disconnect still reaches idle Goal continuation while Shadow
is installed. The byte-exact inherited Goal patch remains unchanged.

## Release boundary

The release child runs the fixed `1.95.0` toolchain on native Windows x64/ARM64,
macOS x64/ARM64, and Linux musl x64/ARM64 runners. Each job tests Goal and shadow,
checks app-server, builds `codex-cli`, copies the root license/notice bundle plus
the non-official trademark statement, writes BUILD-INFO with source/patch/toolchain
hashes, computes SHA-256, and validates an exact output allowlist. A final audit job
downloads all six artifacts and rechecks platform completeness, ZIP/binary hashes,
archive paths, and BUILD-INFO provenance before the workflow can succeed.
Raw-byte provenance is fixed to LF and derives upstream symlinks from Git objects;
only the rebuilt side is canonicalized so the source's flattened-license difference
remains auditable. Musl rows use the source-proven release profile while retaining
full Goal/Shadow package tests and app-server integration checking. They also
follow the source workflow's checksum-verified official Codex `rusty_v8` override
and retry transient network failures at the client boundary. Manifest digests sort
normalized string paths so Windows and POSIX hosts produce the same tree hashes.

## Rollback

Patches and tree states are independent. Rebuild from the official commit to
remove an extension. Release artifacts remain immutable; a failed allowlist or
hash check fails before publication.
