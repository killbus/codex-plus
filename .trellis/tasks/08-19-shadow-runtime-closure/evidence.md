# Shadow runtime closure - Evidence

## Pre-fix deterministic failures

- Source SHA: `3a670da2e46329f741c639e5e38c729050c8044c`
- Workflow run: <https://github.com/killbus/codex-plus/actions/runs/32321574583>
- Focused job: <https://github.com/killbus/codex-plus/actions/runs/32321574583/job/96284667613>
- Result: `Shadow runtime contracts` failed after pinned formatting passed and all
  four focused tests compiled and executed.

Observed failures:

1. `idle_reservation_cannot_be_overwritten_by_concurrent_spawn_task`
   panicked in `core/src/tasks/mod.rs` because the idle worker reached the
   debug-only task installation assertion after the concurrent user task had
   already taken ownership (`assertion failed: turn.task.is_none()`).
2. `try_start_turn_if_idle_rejects_in_flight_client_user_input` accepted the
   Shadow start after real client work had entered the session, violating the
   host-visible user-work gate.
3. `old_epoch_delivery_worker_cannot_drain_new_epoch_report` showed the old
   worker draining the epoch-1 replacement report in full.
4. `cancelled_same_epoch_delivery_worker_cannot_drain_replacement_report`
   showed a cancelled worker draining the same-epoch replacement report in
   full after it acquired the delivery permit.

The tests use notification/channel ordering for their correctness condition;
the two-second timeouts only prevent a broken test from hanging the workflow.
No production runtime fix was present in this SHA.

## Additional pre-fix pending-work ownership failure

- Source SHA: `c4ad6ae6dba64b3fd98362db86a2898af9963e6e`
- Baseline production SHA: `3a670da2e46329f741c639e5e38c729050c8044c`
- Workflow run: <https://github.com/killbus/codex-plus/actions/runs/32328157388>
- Focused job: <https://github.com/killbus/codex-plus/actions/runs/32328157388/job/96303509943>
- Compile step: passed after the test target was built successfully.
- Execution step: the isolated pending-work ownership test failed in one second.

The evidence ref adds only a test gate, the deterministic
`pending_work_start_does_not_steal_user_pending_input_after_reservation_replacement`
test, and focused CI steps that compile and execute that test separately.
Production task-start behavior remains the baseline implementation. The gate
pauses after pending work reserves an `ActiveTurn`; a real user task then
replaces that reservation and queues user input before the stale pending-work
starter resumes. The baseline starter uses unqualified task ownership, so it
cannot finish without panicking, overwriting the user task, or stealing the
user's pending input. The timeout only bounds a broken test and is not the
correctness oracle.

The general `Rust checks` job on the evidence ref failed independently at
provenance verification because the intentionally test-only evidence commits
are not part of the formal patch chain. That expected evidence-branch failure
is not used as the runtime result.
