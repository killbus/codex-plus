# Upstream audit for rust-v0.153.4

Audit date: 2026-09-06

## Release identity

- GitHub latest stable release: `rust-v0.153.4`
- Published: `2026-09-04T23:25:48Z`
- Draft: false
- Prerelease: false
- Annotated tag object: `042fb41b7c813ac7999105e886b2b7aa715b5081`
- Peeled source commit: `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`
- Source commit timestamp: `2026-09-04T15:41:04-07:00`

## Delta from the current baseline

Compared with `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`:

- 1,627 commits
- 3,587 changed files
- 515,524 insertions and 85,187 deletions
- 3,432 changed paths under `codex-rs/`

## Patch application probe

- Plain `git apply --check goal-old-continuation.patch`: fails.
- `git apply --3way --check goal-old-continuation.patch` with the required
  preimage blobs available: applies both Goal files cleanly.
- Applying `shadow-mind.patch` after the Goal patch produces 25 conflicts.

Conflict paths:

```text
codex-rs/app-server-protocol/src/protocol/thread_history.rs
codex-rs/app-server/src/extensions.rs
codex-rs/core/src/codex_thread.rs
codex-rs/core/src/hook_runtime.rs
codex-rs/core/src/session/handlers.rs
codex-rs/core/src/session/inject.rs
codex-rs/core/src/session/input_queue.rs
codex-rs/core/src/session/mod.rs
codex-rs/core/src/session/session.rs
codex-rs/core/src/session/tests.rs
codex-rs/core/src/session/turn.rs
codex-rs/core/src/session/turn_context.rs
codex-rs/core/src/tasks/lifecycle.rs
codex-rs/core/src/tasks/mod.rs
codex-rs/core/src/tasks/review.rs
codex-rs/ext/extension-api/src/contributors.rs
codex-rs/ext/extension-api/src/contributors/thread_lifecycle.rs
codex-rs/ext/extension-api/src/lib.rs
codex-rs/ext/goal/src/runtime.rs
codex-rs/rollout/src/policy.rs
codex-rs/tui/src/app/agent_status_feed.rs
codex-rs/tui/src/bottom_pane/slash_commands.rs
codex-rs/tui/src/chatwidget/replay.rs
codex-rs/tui/src/chatwidget/slash_dispatch.rs
codex-rs/tui/src/slash_command.rs
```

## Architectural observations

- Goal gained root/descendant accounting, turn parent/root relationships, and
  explicit execution-failure handling.
- The target release substantially changes shared orchestration and review
  boundaries. Those upstream implementations remain part of the authoritative
  baseline as a whole rather than becoming separately named fork deliverables.
- Upstream response retry now exposes `UnboundedConnectionRetries`, 5-60 second
  exponential backoff, and retry telemetry.
- The fork must therefore be expressed against the new architecture; copying old
  shared modules would discard upstream behavior.

## Baseline evidence

- Repository HEAD and `origin/main`: `632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5`
- Pre-upgrade CI run: `32451531000`, green
- Rust toolchain in current and target release workflows: `1.95.0`
