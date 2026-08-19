# Shadow Report Lifecycle - Grounded Findings

## Current Behavior

- `ext/shadow/src/lib.rs:827-835` converts accepted reports to model items and starts a regular idle
  turn. `:905-914` uses `role = "user"` and a `[shadow:<name>]` text prefix.
- `core/src/session/inject.rs:179-186` queues these as `TurnInput::ResponseItem` and starts the task.
- `core/src/hook_runtime.rs:586-589` records a `ResponseItem` without emitting a user-message turn
  item. This is why the TUI shows only the main Agent response after `Worked for ...`.
- `ext/shadow/src/lib.rs:551-607` schedules on every eligible completed-turn idle edge and has no
  completed-turn origin filter. A Shadow-triggered main follow-up therefore becomes eligible again.

## Native Display Path

- `ext/items/src/lib.rs:15-45` defines the extension-owned typed item boundary and requires a public
  app-server wrapper for each variant.
- `protocol/src/items.rs:44-75` carries extension items as canonical `TurnItem::Extension` values.
- `app-server-protocol/src/protocol/v2/item.rs:905-909` maps extension items to public `ThreadItem`s.
- `app-server/src/bespoke_event_handling.rs:961-1015` forwards standard item started/completed events.
- `tui/src/chatwidget/protocol.rs:362-371` sends completed live items to the shared renderer;
  `tui/src/chatwidget/replay.rs:80-88` uses the same renderer for replay.

Conclusion: `ExtensionItem::ShadowReport` plus a typed app-server wrapper is the native API. Reusing
user, hook, collaboration, sub-agent activity, or review items would misstate authorship/lifecycle.

## Persistence

- `core/src/session/mod.rs:2022-2050` emits standard item lifecycle events through the persisted event
  path.
- `rollout/src/policy.rs:89-97` persists all completed `TurnItem`s for paginated history, but legacy
  history allowlists only plan and sleep extension items.

Conclusion: add Shadow report completed items to the legacy allowlist and test both modes. Started
events remain transient; completed items are the replay source of truth.

## Origin Suppression

- `core/src/tasks/lifecycle.rs:32-65` stores the completed turn id and emits `ThreadIdleInput`, but the
  input currently contains no completed turn origin.
- `ext/extension-api/src/contributors/thread_lifecycle.rs:43-55` is the host/extension idle contract.
- `core/src/session/inject.rs:85-186` owns the atomic idle epoch check, reservation, input enqueue, and
  task start. This is the correct point to attach a trusted origin.
- Goal uses the same generic automatic idle API at `ext/goal/src/runtime.rs:399-406`.

Conclusion: add a host-owned origin-aware idle-start path and surface the corresponding completed
origin in `ThreadIdleInput`. Shadow suppresses only its own origin; Goal and ordinary turns remain
eligible. Do not infer origin from `[shadow:...]` content.

## Research Agent Note

The earlier independent native-API research reached the same `ExtensionItem::ShadowReport` boundary.
The available collaboration runtime did not expose a `gpt-5.6-luna` override, so the agent inherited
the session model; no claim is made that Luna was actually used.
