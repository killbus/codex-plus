# Agent Goal and dispatch capability audit

Audit date: 2026-09-06

## Required ordering

For every delegated agent, the required state transition is:

```text
materialized agent thread
  -> persisted Goal set through the standard Goal mechanism
  -> Goal response confirms the retry objective is Active
  -> agent work is dispatched
  -> main agent actively checks progress, evidence, and recovery
```

Setting Goal text in the dispatch message, injecting it through a hook, or relying
on inherited parent context does not satisfy the requirement.

## Repository mechanism

The product's standard persisted Goal API is `thread/goal/set`:

- `codex-src/codex-rs/app-server/README.md` documents the RPC and its
  `threadId`, `objective`, `status`, and `tokenBudget` fields.
- `codex-src/sdk/python/src/openai_codex/client.py::thread_goal_set` invokes the
  RPC for a materialized thread.
- `start_goal_operation` reserves routing, clears the old Goal, sets an Active
  Goal, and then waits for the runtime-generated turn. This ordering demonstrates
  that persisted Goal activation precedes goal work.

## Current orchestration-tool boundary

The current session exposes:

- main-thread `create_goal`, `get_goal`, and terminal-only `update_goal`;
- `spawn_agent`, which starts child work and only then returns its agent/thread
  identifier;
- post-spawn `send_input`, `wait_agent`, `resume_agent`, and `close_agent`.

No exposed operation can preallocate a child thread and call `thread/goal/set` on
it before `spawn_agent` starts work. Calling `create_goal` affects the current
thread and cannot target a future child. Consequently, the current tools cannot
prove the required Goal-before-dispatch ordering.

## Safe execution decision

`.trellis/config.yaml` documents `codex.dispatch_mode: inline` as the explicit
mode that keeps implementation and checks in the main session. The configuration
now explicitly sets this key to `inline`, so implementation and checking remain
in the Goal-owning main session and no child agent is dispatched.

Keep inline mode unless a later platform demonstrably exposes one of these
auditable capabilities:

1. create/preallocate an agent thread, set its persisted Goal, then dispatch; or
2. atomically spawn an agent with a persisted Goal, where the Goal write is
   confirmed before the first work turn begins.

If neither capability exists, dispatching any agent is prohibited. Inline work
keeps the active main-thread Goal authoritative and satisfies the no-dispatch
branch of the contract.

A read-only `dbs-chatroom` audit is compatible with inline mode only if its
implementation runs entirely in the main session. The currently installed skill
requires one child agent per expert, so it is unavailable under the current
Goal-before-dispatch constraint even when the requested audit is read-only.

## Evidence required if delegation later becomes available

- Agent/thread identifier allocated before work starts.
- Successful Goal-set response showing the exact transient retry policy and
  Active status.
- Dispatch timestamp/order after the Goal-set confirmation.
- Main-agent status checks, result inspection, and any recovery/follow-up actions.
- Final closure of completed agents after their evidence is integrated.
