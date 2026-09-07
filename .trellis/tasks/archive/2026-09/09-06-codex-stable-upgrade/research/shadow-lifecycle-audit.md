# Shadow lifecycle integration audit

Audit date: 2026-09-06

## Scope

This pass verifies ownership, ordering, and cleanup at the boundary where a
completed Shadow run starts an automatic main-Agent turn on the `0.153.4`
baseline. It is an inline evidence review, not an independently dispatched
agent review.

## Accepted delivery path

1. `ThreadRuntime::take_reports_for_delivery` checks the delivery run, epoch,
   and cancellation state while holding the report map, then removes the
   current epoch's reports exactly once.
2. `run_shadow` derives display and model representations from the same bounded
   `ShadowReport` values and calls
   `try_start_turn_if_idle_for_epoch_with_origin` with the trusted
   `Extension("shadow")` origin.
3. The session reserves an idle `ActiveTurn`, rechecks pending client/mailbox
   work and Plan mode, then queues display items before response items in that
   reservation's `TurnState`.
4. `start_task_for_idle_reservation` proves pointer ownership of the exact
   reservation and reaches the final automatic-turn admission boundary while
   retaining the active-turn lock.
5. Automatic admission performs an exact compare-and-swap from zero to the high
   admission bit in `client_input_reservations`. A client input that registered
   first makes the compare-and-swap fail; an automatic turn that claims first
   keeps the claim until `turn.task` is installed.
6. After admission, the task transfers the reservation's queued items into the
   installed task state, initializes lifecycle state, and installs the task. An
   RAII guard then clears only the admission bit.
7. `RegularTask` emits `TurnStarted` before `run_turn` records initial inputs.
   `record_pending_input` emits `ItemStarted` and `ItemCompleted` for each
   display item, while response items are recorded into model-visible history
   without being rendered as user messages.

## Confirmed admission race and resolution

The first audit missed a real linearization gap. Automatic startup could observe
zero client-input reservations, wait before task installation, and then install
a Shadow turn after a client-input handler had registered. Because the original
checks were independent loads, the later client registration did not revoke the
earlier observation. The rejected automatic path could therefore emit
`TurnStarted` and Shadow item lifecycle before the client replaced it.

The fix uses one `AtomicU64` admission state. The low 63 bits count entered
client-input handlers and the high bit is the automatic-turn claim. Client
reserve/release operations preserve the high bit and fail loudly on count
overflow or underflow. Automatic startup succeeds only by changing the exact
state `0` to the high bit. This gives the boundary a single winner:

- If client registration occurs first, the state is nonzero and automatic
  admission returns `Busy` before lifecycle initialization or task installation.
- If the automatic claim occurs first, the reservation has passed the final
  ownership boundary. A later client registration is still recorded and follows
  the normal steer/replacement path after the automatic task is installed.

Lifecycle setup that must not occur on rejected admission was moved after this
boundary. The claim remains live through `turn.task = Some(...)`, and its guard
clears only the high bit so a concurrently registered client count is retained.

## Epoch and cleanup reasoning

The Shadow turn-start contributor calls `begin_user_input`, which increments the
runtime epoch, cancels old Shadow runs, and clears reports still held by the
runtime. Accepted reports are already detached from that map and stored in the
core turn-state queue, so this lifecycle callback cannot erase the accepted
display/model pair. The new epoch also prevents any late old-epoch worker from
being accepted into a later turn.

If reservation ownership is lost before installation,
`try_start_turn_if_idle_inner` drains the detached reservation's pending queue
and clears the reservation. Busy, stale-epoch, Plan-mode, pending-trigger, and
in-flight client-input rejection paths enqueue no visible item. Abort, terminal
error, thread stop, and new turn start clear undelivered runtime reports.

## Test evidence present in the integrated tree

- Lifecycle order is asserted as `turnStarted`, `itemStarted`, then
  `itemCompleted`.
- Duplicate delivery while the follow-up turn is active is rejected.
- Stale epoch, active/busy state, Plan mode, pending trigger work, and in-flight
  client input reject Shadow delivery without emitting the display item.
- Reservation replacement cannot transfer Shadow work into a concurrent user
  turn, and stale pending-work startup cannot steal replacement-turn input.
- `client_input_registered_before_automatic_claim_rejects_shadow_without_lifecycle`
  deterministically pauses automatic startup at its final boundary, registers a
  client input, then proves that Shadow returns `Busy`, emits no `TurnStarted` or
  matching item lifecycle, and that the client owns the real user turn.
- Old-epoch and cancelled same-epoch delivery workers cannot drain replacement
  reports.
- Accepted reports drain once; cancellation and new-turn start clear
  undelivered reports.

## Counter-review

The apparent risk that `begin_user_input` clears the report being delivered is
not supported by the ownership trace: it clears the Shadow runtime map after the
accepted values have moved to core-owned turn state. The opposite risk, leaking
an accepted report after a failed reservation, is covered by explicit queue
drain on failed installation and by the reservation-replacement regression.

The admission-state design was challenged on five boundaries:

- Overflow: the 63-bit client count cannot wrap into the claim bit; reserve uses
  `fetch_update` and asserts instead.
- Underflow: release rejects a zero low-bit count even when the claim bit is set.
- Concurrent registration: increment/decrement preserves the claim bit because
  only the low-bit count is changed.
- RAII cleanup: every return or unwind after successful claim drops the guard,
  and the guard clears only the high bit.
- Lifecycle and ownership: claim occurs after exact reservation/pointer checks
  and before lifecycle mutation; it remains held until the task pointer is
  installed. No rejected automatic admission can emit Shadow lifecycle.

This change affects only automatic-turn admission synchronization. It does not
alter Guardian behavior, upstream policy, or the public Shadow representation.
Remote Rust validation remains required for compilation and runtime evidence.
