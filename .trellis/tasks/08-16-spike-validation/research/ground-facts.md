# Ground facts: Codex host and pi-shadow-mind

验证版本：Codex `rust-v0.146.0-alpha.3`，upstream commit
`bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`；来源快照
`ea17de047b46e9584ffba2d2bda2dc3ae5a5aff8`；pi reference
`ba75a67092024053f6529ef574d0cd81006ba6b1`。

## 1. Report injection and attribution

Codex `Session::inject_if_running` accepts only `Vec<ResponseItem>` and converts
each item directly into `TurnInput::ResponseItem`
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/core/src/session/inject.rs:19-35`).
The companion idle path starts a regular turn with the same item type
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/core/src/session/inject.rs:45-50,121-128`).
There is no source/role/epoch precondition in either API. `TurnSteerParams` has an
`expected_turn_id`, but that is part of the external steer request and does not
guard `inject_if_running`
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/app-server-protocol/src/protocol/v2/turn.rs:175-197`).

Conclusion: **needs a host change**. Add an atomic
`inject_if_running_for_turn(expected_turn_id, items)` and an idle-start equivalent
guarded by `expected_idle_epoch`, both under the same active-turn/input-queue lock.
Use a structured internal report item or an explicit source marker; do not encode
authority in untrusted model text. A successful enqueue is not evidence that a
completed model loop consumed the item, so lifecycle tests must cover both paths.

## 2. Epoch and late-result semantics

The host exposes `ThreadIdleInput` with only session and thread stores; it carries
no completed turn id or idle epoch
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/ext/extension-api/src/contributors/thread_lifecycle.rs:42-48`).
Turn stop lifecycle runs before the active turn is cleared
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/core/src/tasks/mod.rs:786-815`),
so a delayed report can race turn cleanup. pi increments epoch on user input,
cancels old runs, and checks epoch before batching/delivery
(`/tmp/pi-shadow-mind.8UXDVd/source/src/runtime.ts:64-69,128-166,205-219`; see also
`/tmp/pi-shadow-mind.8UXDVd/source/DESIGN.md:353-386`).

Conclusion: **the existing expected-turn field is insufficient**. Host must expose
monotonic `completed_turn_id`/`idle_epoch`, cancel on new input/abort/stop, and make
the precondition check and queue mutation atomic. Required tests: duplicate idle,
error->stop->idle, new input racing a report, and a report arriving after active
turn cleanup.

## 3. Parallelism and serialization

pi selects at most the remaining global slots and treats
`max_parallel_shadows` as currently running instances, not merely per-heartbeat
launches (`/tmp/pi-shadow-mind.8UXDVd/source/src/scheduler.ts:3-43` and
`DESIGN.md:306-314`). Codex's extension callbacks are awaited serially by the host
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/core/src/tasks/lifecycle.rs:76-89`),
while child execution would be asynchronous through `AgentSpawner`
(`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/ext/extension-api/src/capabilities/agent.rs:9-21`).

Conclusion: **separate the invariants**. A first Rust implementation may enforce a
per-thread semaphore for real child execution and a single serialized report queue;
it must not advertise a global `max_parallel_shadows` setting until a shared runtime
slot is observable and tested. The conformance test should assert both concurrent
child count and serialized host injection order.

## 4. Registry write approval

Codex `ToolContributor` only returns `ToolExecutor` values and the executor contract
has no approval argument (`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/ext/extension-api/src/contributors.rs:272-280`;
`/home/agent/Src/codex-goal-auto-retry-build/codex-src/codex-rs/tools/src/tool_executor.rs:44-68`).
The reference implementation explicitly calls a UI confirmation before every
registry mutation and refuses headless writes
(`/tmp/pi-shadow-mind.8UXDVd/source/src/management-tools.ts:41-115`).

Conclusion: **not confirmed in the current host API**. Shadow CRUD must remain
proposal-only until an `ApprovalReviewContributor`/host elicitation bridge is wired
and tested. The bridge must show a field/body diff, preserve sandbox policy, and
perform an atomic temp-file + rename only after approval. Rejected or headless writes
must leave the registry unchanged.
