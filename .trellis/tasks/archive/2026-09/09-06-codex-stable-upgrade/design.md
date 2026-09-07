# Technical design: Codex stable upgrade

## Architecture and boundaries

The upgrade keeps the existing three-state rebuild model while changing the
official source snapshot:

```text
official rust-v0.153.4 source commit 3d2ee51c (pristine)
  -> immutable goal-old-continuation.patch via deterministic three-way apply
  -> regenerated shadow-mind.patch (fork Goal + Shadow integration and minimal
     compatibility glue)
  -> codex-src/
```

The complete target upstream implementation is authoritative and is treated as
one baseline rather than a list of capabilities to reselect or reintroduce. Fork
behavior is expressed as the smallest semantic delta needed to port its existing
Goal and Shadow responsibilities. Old fork files must never replace new `0.153.4`
modules wholesale.

## Provenance reconstruction

`scripts/verify_provenance.py` currently extracts an upstream archive and uses
plain `git apply`. That cannot reconstruct the immutable Goal patch on the new
baseline. Update the verifier so patch application occurs in a temporary Git
checkout with the patch preimage objects available.

- Record the target source commit and the Goal patch's prior baseline needed to
  seed three-way object lookup.
- Apply only the immutable Goal patch with `git apply --3way`; require a clean
  result with no unresolved index entries.
- Apply the regenerated Shadow patch directly to the resulting Goal-only state.
- Preserve fetch-only retry. A failed three-way merge, patch mismatch, changed
  symlink contract, or manifest mismatch remains a deterministic failure.
- Make the local `--upstream-root` path use equivalent Git-backed semantics so
  tests and offline audits do not exercise a weaker path than CI.
- Extend recorded provenance with enough application metadata to make the
  three-way step explicit and auditable, while preserving ordered patch hashes.

## Migration slices

### 1. Source and workspace baseline

Replace `codex-src/` with the pristine `0.153.4` source, retain intentional
repository materializations, and reconcile workspace, Cargo lock, Bazel lock,
and generated-file expectations from the new source before fork behavior is
ported. Rust remains pinned to `1.95.0`.

### 2. Goal policy on the new Goal model

Apply the immutable patch using three-way semantics, then adapt only integration
code in `shadow-mind.patch`. Preserve upstream root/descendant accounting, turn
parent/root relationships, execution-failure handling, and any new Goal state
types. The fork override remains narrow: only `UsageLimitExceeded` pauses; other
terminal turn errors leave the Goal Active for idle continuation.

### 3. Retry ownership and upstream compatibility

Treat request retry and Goal continuation as separate layers:

```text
provider failure
  -> bounded in-request retry/backoff + telemetry
  -> terminal turn error after exhaustion
  -> Goal remains Active (except UsageLimitExceeded)
  -> idle lifecycle automatically starts a new turn
  -> repeat without a consecutive-failure cap while the Goal is Active
```

Use the target baseline's existing transport path rather than duplicating it.
Explicitly constrain any `UnboundedConnectionRetries` option where the fork's
Goal contract requires bounded requests. Integration changes are limited to the
shared boundaries touched by Goal/Shadow; all other upstream behavior remains
authoritative as a whole.
The finite unit is the individual request or review attempt budget; the active
Goal's cross-turn continuation is not finite and must not stop or ask for user
intervention solely because these transient classes repeat.

## Agent orchestration contract

Sub-agent execution uses a two-step control boundary. First, the main agent uses
the standard persisted Goal mechanism (`thread/goal/set` or a platform-equivalent
agent-targeted operation) to create the specific agent Goal, including the
complete transient retry and continuation policy. Only after that operation
succeeds may the agent be dispatched. Dispatch text and inherited context are not
evidence that this boundary was satisfied.

The main agent remains the owner of progress: it polls agent status, inspects
intermediate evidence, performs recovery when a transient failure occurs, and
issues follow-up work when acceptance evidence is missing. Agent completion is
accepted only after its output is checked against the assigned goal and the task
acceptance criteria.

The current Codex tool boundary exposes thread-level Goal operations for the main
thread and a `spawn_agent` operation that starts a child before returning its
identifier. It does not expose an agent-targeted pre-dispatch Goal operation.
Therefore the safe execution mode for this task is `codex.dispatch_mode: inline`
unless a later session demonstrably exposes an atomic spawn-with-Goal or a
preallocated child thread that accepts `thread/goal/set` before work dispatch.
This is a fail-closed orchestration choice, not permission to weaken the Goal
requirement.

### 4. Lifecycle and Shadow ownership

Port trusted automatic-turn origin, idle epoch, pending-work reservation, and
report delivery onto the new session/task lifecycle. Ownership is accepted once
at the host boundary. The accepted turn emits `turn/started`, then the typed
display item's lifecycle, while the matching model item enters context without
being rendered as a user message.

Cancellation, stale epoch, busy/Plan state, and pending client/extension work
must reject or clear undelivered reports without leaking them into a later turn.
Only an automatic turn whose origin is `Extension("shadow")` suppresses the next
heartbeat.

### 5. Public representations

Keep one shared `ShadowReportItem` contract across extension items, rollout,
thread-store history, app-server protocol, generated JSON/TypeScript schemas, and
TUI live/replay rendering. Consumers use typed identity fields and never parse
report text to infer origin. Regenerate schemas from source after implementation.

## Compatibility decisions

- Stable `0.153.4` is the only upstream target for this task.
- The Goal patch remains immutable even though this requires a provenance-tool
  enhancement. Rewriting it for easier direct application would destroy the
  reviewed baseline identity.
- `shadow-mind.patch` is regenerated because it represents integration against a
  specific upstream architecture. Its hash is expected to change.
- Existing CLI release targets and Rust `1.95.0` remain unchanged unless CI
  provides concrete target dependency evidence.
- The complete upstream baseline wins when there is no explicit fork contract.
  It must not be decomposed into features supposedly supplied by
  `shadow-mind.patch`.

## Cross-audit gates

Run distinct architecture, behavioral, provenance/release, and adversarial
assumption reviews after semantic integration, after patch/provenance rebuild,
and before final completion. The adversarial pass must challenge both the
implementation and the reviewers' premises against actual ownership and trust
boundaries. Under inline execution these are separate evidence-backed main-agent
passes; they are not represented as independent agents. If compliant
pre-dispatch Goal creation becomes available, use independent `gpt-5.6-sol`
review agents and retain their goal-before-dispatch records. A read-only
`dbs-chatroom` may help only if it can run entirely inline. The currently
installed skill mandates child-agent dispatch, so it is unavailable under this
task's inline constraint.

## Rollout and rollback

Implementation uses reviewable checkpoints: provenance support, pristine source
snapshot, Goal-only reconstruction, shared core lifecycle integration, Shadow
and public protocol/TUI migration, and final patch/provenance regeneration. Each
checkpoint must leave a comprehensible diff and may be reverted independently.
These checkpoints may remain as multiple commits on the upgrade branch while CI
and review are in progress. They are not separate product changes. Final
integration into `main` squashes the complete upgrade range into exactly one
atomic commit named `feat: upgrade Codex baseline to 0.153.4`; no upgrade-local
`fix:` or checkpoint commit enters `main` independently.

The final merge remains blocked until GitHub Actions validates behavior and the
release artifact contract. Rollback is a revert to pre-upgrade commit
`632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5`; no data migration or external state
change is involved.
