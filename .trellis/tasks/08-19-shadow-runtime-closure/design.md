# Shadow runtime closure - Technical Design

## Boundary

Keep the landed typed-item and origin architecture. The fix belongs at the host-owned
idle reservation/task installation boundary and in Shadow's epoch-owned report queue,
not in app-server or TUI workarounds.

## Concurrency Contracts

An idle delivery reservation must remain the same owned state until its task is
installed. A concurrent user submission must observe that ownership and take one
defined path without clearing, steering into, or overwriting a partially installed
Shadow task. Release builds must not rely on `debug_assert!` for exclusivity.

Reports must be taken only by a worker whose epoch still matches the report epoch and
the current runtime epoch. Cancellation and epoch checks must occur after acquiring the
delivery permit. Prefer epoch-scoped extraction over draining one unpartitioned vector.

The user-input entry path needs a host-visible reservation or generation change before
its first await can race with idle delivery. The idle gate must reject once real client
work has entered, not only after an active task or trigger mailbox item appears.

## Verification Design

Introduce test-only synchronization at existing ownership boundaries only when a
production-neutral dependency or observer cannot express the race. Tests coordinate
with barriers/channels and assert state, origin, queued inputs, lifecycle events, and
request counts; sleeps may be used only under an outer timeout to prevent hangs.

The end-to-end test uses a real Shadow registry entry with activation probability 1.0,
a controlled child response, and a controlled parent follow-up. It observes public
app-server notifications and the number/order of model requests, then resumes the
thread through both history modes and compares TUI live/replay output.

Temporary mutation verification is not committed: locally or in a disposable tree,
remove each load-bearing link and prove its owning test fails.

## Compatibility And Rollback

Do not change `ShadowReport` wire fields or Goal behavior. Existing callers that start
ordinary idle turns retain `Unspecified` origin. Rollback is one coherent reversal of
the concurrency fix and its tests; never retain a widened public API solely for tests.
