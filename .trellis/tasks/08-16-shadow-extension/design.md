# shadow-extension — 技术设计

## Runtime boundary

`ShadowExtension` owns global registry/config and installs thread state through
`ThreadLifecycleContributor`, `TurnLifecycleContributor`, `ToolContributor`, and
the `/shadow` command integration. It receives a host-owned `AgentSpawner` capability
at installation; the extension never reaches through private `ThreadManager` APIs.

The spawner creates a child session with `SessionSource::SubAgent` metadata marking
the shadow id, a frozen cwd/model/permission snapshot, sanitized trajectory, and a
cancel handle. Child sessions do not install the shadow scheduler. Completion returns
at most one report or silence and always releases the semaphore slot.

## Scheduling and epochs

`on_thread_idle` calls `schedule_once(main_turn_id, trajectory_snapshot)`. An atomic
per-thread `last_scheduled_turn_id` makes error/stop/idle duplication harmless. The
runtime keeps `epoch` and active run records. New user input increments epoch and
cancels old runs; timeout/abort/thread stop do the same. Each report carries epoch
and expected active turn id.

The host adds `inject_if_running_for_turn(expected_turn_id, items)`: it checks the
active turn and enqueues while holding the same lock. A failed precondition discards
the items. Idle delivery uses the same expected-turn check before starting a regular
turn, so no report can cross a user-task boundary.

## Registry and writes

Resolve `codex_home` from the effective host config, never from a hard-coded home.
Reads scan only top-level `.md` files. Writes use temp-file + rename and a process
lock; stale/invalid files remain visible as errors and are not auto-corrected.
Agent mutation tools produce a host approval request containing a field/body diff;
only an explicit approval commits the atomic rename. Manual `/shadow` edits use the
same validator and do not bypass the host sandbox.

## Context and tools

Build a bounded, sanitized trajectory from the main session. Preserve system/project
instructions, omit secrets and oversized items, and append the shadow definition and
minimal report protocol. Tool set is read-only defaults plus validated explicit names
and the always-present terminating `report_to_main` tool.

## Failure and rollback

Invalid registry entries are skipped without disabling valid entries. A failed child
run emits bounded metadata and releases resources. Removing the feature registration
and patch restores the goal-only binary; no persistent user registry is rewritten by
rollback.

The first release's `/shadow pause|resume` control is process-local and therefore
applies to the embedded app-server. Remote app-server control requires a host RPC
bridge and is not claimed by R8.
