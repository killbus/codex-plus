# shadow-extension - Technical Design

## Boundary

The fix has two independent contracts that meet at Shadow delivery:

1. `codex-extension-items` owns the durable, extension-namespaced display payload.
2. Core owns the trusted origin of an automatic turn and the atomic idle-start boundary.

Shadow owns policy: create the display payload after a report is accepted, launch the model-visible
follow-up with origin `extension:shadow`, and skip scheduling when the completed turn has that origin.
App-server and TUI only map and render the typed item; they do not infer identity from report text.

## Display Contract

Add a `shadow` module under `ext/items` and a `ShadowReportItem` with:

- `id`: stable lifecycle/deduplication id, derived from the accepted run/report rather than content
- `shadow_id`: stable registry identity
- `shadow_name`: resolved display name (registry already falls back to id)
- `content`: accepted report body after UTF-8-safe hard truncation

Serialize it as `ExtensionItem` kind `shadow.report`. Add the public app-server wrapper
`ThreadItem::ShadowReport(ShadowReportItem)` and exhaustive mappings/id accessors. Do not add a raw
response variant or legacy bespoke event.

The accepted report produces a standard completed turn item. Core persists and emits the typed item;
the separate `ResponseItem::Message` remains the model-visible input for the automatic follow-up.
This preserves prompt behavior without presenting generated content as a user-authored message.
Shadow applies one explicit report-size limit before creating either representation so the visible
item and model input carry identical bounded text; no model-visible fragment is unbounded.

## Delivery Sequence

```text
Shadow child completes
  -> epoch/cancellation check
  -> reserve idle turn atomically with origin extension:shadow
  -> record + emit ShadowReport item/started and item/completed
  -> enqueue model-visible report input
  -> run one regular main-Agent turn
  -> idle lifecycle exposes completed origin extension:shadow
  -> Shadow scheduler returns without heartbeat
```

The visible lifecycle and model input must commit as one accepted-delivery operation. If the idle
reservation fails because the epoch is stale, the thread is busy, trigger-turn work is pending, or
Plan mode is active, neither side is emitted. Cancellation/timeout checks remain before reservation.

To avoid a visible report without a follow-up, the host idle-start API should accept both the typed
display item and model inputs, or otherwise reserve first and emit/enqueue under the same owned turn
state before the task starts. Do not emit the item before `try_start_turn_if_idle_for_epoch` succeeds.

## Turn Origin

Introduce a small host-owned automatic-turn origin type instead of a Shadow boolean or text parser.
The origin is attached when core creates the `TurnContext` for idle work and copied to the completed
idle lifecycle input. Recommended shape:

```rust
enum AutomaticTurnOrigin {
    Unspecified,
    Extension(String),
}
```

Existing `try_start_turn_if_idle*` callers retain an `Unspecified` default through compatibility
wrappers. Add an explicit origin-aware path for Shadow; Goal may remain on the default path or use
`Extension("goal")`, but either way only `Extension("shadow")` is suppressed by Shadow. The marker is
trusted runtime metadata, not model-visible content. It need not change external app-server turn
schemas unless an existing public contract requires it.

`ThreadIdleInput` receives the completed turn origin alongside `completed_turn_id` and `idle_epoch`.
The origin must correspond to the same completed turn snapshot. Shadow checks it before
`schedule_once`; Goal and other lifecycle contributors continue to receive the callback unchanged.

## Persistence And Replay

Paginated rollouts already persist completed `TurnItem`s. Legacy policy currently persists only
selected extension items, so add `ExtensionItem::ShadowReport` to the legacy allowlist in
`rollout/src/policy.rs`. Item-start is transient; item-completed is the durable representation.

App-server's existing rollout-to-turn builder then reconstructs the public `ThreadItem`. TUI handles
`ShadowReport` in the shared completed-item path used by both live notifications and replay. The cell
renders:

```text
Shadow · reviewer
<accepted bounded report>
```

Use existing history-cell and wrapping helpers. The heading should be visually distinct but compact;
the report body must not inherit user-message styling.

## Compatibility And Failure

- Existing rollouts without `shadow.report` continue to decode unchanged.
- The model-visible `[shadow:<name>]` prefix may remain for prompt compatibility, but UI identity
  never depends on parsing it.
- Unknown future extension items remain governed by the current exhaustive Rust enums.
- Failed/stale reports are logged at bounded debug level and produce no durable item.
- Oversized reports are truncated once at a UTF-8 character boundary before display/model fan-out.
- `/shadow pause` remains process-local; it is resumed only after the recursion regression passes.

## Rejected Alternatives

- `UserMessage`: falsely attributes generated content to the user and changes replay semantics.
- `SubAgentActivity`: represents lifecycle activity and has no completed report-content contract.
- `CollabAgentToolCall`: Shadow is scheduler-owned, not a model-issued collaboration tool call.
- `HookPrompt`: wrong ownership, schema, and replay behavior.
- Review mode: wrong lifecycle and TUI semantics.
- Prefix parsing for suppression: model-controlled text is not a trustworthy turn origin.
