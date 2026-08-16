# codex-plus 发行版地基 — 技术设计

## Tree model

```text
official commit bb6a127 (pristine)
  -> goal-old-continuation.patch (goal-only compatibility baseline)
  -> goal-transient-continuation.patch (integrated error matrix)
  -> shadow-mind.patch (integrated extension)
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

The inherited patch remains auditable as a compatibility baseline. The integrated
patch matches concrete `CodexErrorInfo` variants and HTTP status values. Unknown,
unattributed `InternalServerError`, or permanent errors use native goal stop
behavior; only the matrix in the parent PRD keeps the goal active. A bounded
consecutive-transient counter prevents an unbounded cross-turn loop. Tests use
concrete variants rather than `Other`.

## Release boundary

The release child runs the fixed Windows x64 toolchain, tests Goal and shadow,
builds `codex-cli`, copies the root and source license/notice bundle plus a
non-official trademark statement, writes BUILD-INFO with source/patch/toolchain
hashes, computes SHA-256, and validates an output allowlist. It never downloads,
opens, or packages a VSIX.

## Rollback

Patches and tree states are independent. Rebuild from the official commit to
remove an extension. Release artifacts remain immutable; a failed allowlist or
hash check fails before publication.
