# Full-scope inline audit

Audit date: 2026-09-07

## Status and method

This is the continuing full-scope review for the `rust-v0.153.4` migration.
It is an evidence-backed inline review performed by the main session. It is not
independent-agent evidence. No child agent was dispatched because the current
platform cannot create and activate a persisted Goal on a child thread before
that child begins execution. The repository therefore remains in the explicit
`codex.dispatch_mode: inline` mode recorded in `.trellis/config.yaml` and
`AGENTS.md`.

The review uses four distinct lenses: architecture and ownership, Goal/retry
behavior, Shadow public/runtime behavior, and provenance/release. A separate
counter-review challenges the conclusions against the actual trust and
ownership boundaries. Acceptance remains tied to AC1-AC12 rather than review
consensus.

Current integration state:

- Upstream tag: `rust-v0.153.4`.
- Upstream source commit: `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
- Pre-upgrade rollback commit: `632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5`.
- Staging tree: `.trellis/.runtime/upgrade-staging`.
- Staging base HEAD: `5352fbd14d09926a5217353f08a93c756c87c52a`.
- Staged integration delta: 87 files, 5,933 insertions, and 320 deletions.
- Ordered patches: immutable Goal patch followed directly by the regenerated
  Shadow integration patch.

## Architecture and ownership

The complete upstream `0.153.4` release is the authoritative baseline. The fork
delta ports the existing Goal continuation and Shadow integration contracts plus
the minimum compatibility glue needed at shared upstream boundaries. Guardian,
approval behavior, plugin attribution, and other upstream functionality are not
separate fork deliverables and are not described as additions supplied by this
migration.

The integrated tree preserves upstream Goal root/descendant accounting, turn
relationships, execution-failure accounting, transport fallback, and session
lifecycle. The fork does not replace target modules wholesale. The largest
delta is the Shadow extension and its tests; shared core changes are concentrated
at automatic-turn admission, typed item injection, lifecycle contributors, and
history/rendering boundaries.

`guardian_agent_spawner.clone()` is expected. The closure captures one
`Weak<ThreadManager>`; cloning the closure creates another handle to the same
manager rather than another manager or agent. Guardian consumes one closure and
Shadow consumes the other. Shadow identifies its child with
`ThreadSource::Feature("shadow")`, and `ThreadManager` gives only that source
`InitialHistory::New` because Shadow receives an extension-supplied sanitized
prompt. Other Guardian and subagent paths retain the upstream interrupted-fork
history behavior.

The upstream execution-unavailability protection is separate from service-error
continuation and remains intact. `execution_failure_goal` counts only turns with
an actually executed, failed default-namespace execution tool and no successful
tool. It may select `ExecutionUnavailable` after three such turns. It does not
classify stream disconnects, HTTP 429, or HTTP 5xx turn failures and therefore is
not the prohibited network/service-error breaker in R2/AC4.

## Goal and retry behavior

The immutable Goal patch remains the policy source. `GoalExtension::on_turn_error`
special-cases only `UsageLimitExceeded`; every other terminal `CodexErrorInfo`
leaves the Goal Active so the idle lifecycle can start another automatic turn.
The removal of the now-unreachable `ActiveGoalStopReason::TurnError` variant and
match arm is compatibility cleanup in the Shadow integration patch, not a policy
change or an edit to the immutable Goal patch.

Request and cross-turn retry ownership remain separate:

1. The model provider owns a bounded request attempt budget and backoff. The
   integration enables ordinary HTTP 429 retries in that existing policy by
   setting `retry_429: true`; 5xx and transport retries remain enabled.
2. Stream retry remains bounded by `stream_max_retries` for post-handshake
   incomplete response streams.
3. After request or stream retry exhaustion, the turn terminates with a typed
   error. The active Goal remains Active except for `UsageLimitExceeded`.
4. The idle lifecycle starts a distinct automatic turn. This outer Goal
   continuation has no consecutive service-failure limit and repeats while the
   Goal remains Active.

The upstream unbounded connection-retry branch does not invalidate the bounded
post-handshake tests. That branch is entered only when all of these conditions
hold: `UnboundedConnectionRetries` is enabled, the operation is normal sampling,
the error detail is `ConnectionFailed`, the session is not internal, and the
provider is not Bedrock. The dropped-stream fixture sends `response.created` and
then closes without `response.completed`; parsing produces a stream error rather
than the pre-handshake `ConnectionFailed` detail, so it follows the bounded
`stream_max_retries` path.

Focused tests in the integrated tree cover:

- HTTP 429 recovery and exhaustion after exactly `request_max_retries + 1`
  requests.
- HTTP 5xx/overload exhaustion under the request budget.
- `UsageLimitExceeded` remaining distinct after request retries.
- Post-handshake dropped streams under a bounded stream retry budget.
- Two consecutive exhausted turns, Active Goal persistence after each failure,
  a different automatic turn after each failure, and eventual completion with
  Goals and Shadow enabled together.
- The imported Goal backend behavior for a generic terminal error and the
  distinct usage-limit path.

Guardian is treated as a touched shared upstream path, not as a migration
feature. Its existing isolated review session has
`request_max_retries = 1` and `stream_max_retries = 1`; its existing review loop
permits at most three attempts under one shared deadline. The compatibility
classification retries transient 429, 5xx, connection, and stream failures while
leaving `UsageLimitExceeded` non-retryable. Backoff remains bounded by the shared
deadline and cancellation. Tests cover recovery and exhausted transient failures
with one terminal event. This policy is local to Guardian review and does not
limit or redefine the root Goal's cross-turn continuation.

## Shadow public and runtime contract

The public and durable representation remains typed end to end:

- Internal extension item: `shadow.report`.
- Public app-server item: `shadowReport`.
- Shared fields: report identity, Shadow identity/name, and content.
- One UTF-8-safe bounded report body is used for both the display-only item and
  model-visible response item.

Accepted delivery preserves ordering and ownership. The runtime removes reports
for the matching run and idle epoch exactly once. Core reserves an idle turn,
checks Plan mode and pending client/extension work, queues display items before
model items, and then validates ownership at final task installation. The regular
task emits `turnStarted` before the Shadow item's `itemStarted` and
`itemCompleted` lifecycle. The display item is not inserted as a user message;
the paired response item is the model-visible representation.

The automatic-turn admission state uses the low 63 bits as the count of entered
client-input handlers and the high bit as the automatic-turn claim. Automatic
admission succeeds only through an exact compare-and-swap from zero to the high
bit. Client reservation and release preserve the claim bit. The claim remains
held through `turn.task = Some(...)`, and its RAII guard clears only the high bit.
This gives client input and automatic startup one linearized winner and prevents
a rejected Shadow turn from emitting lifecycle events.

The regression
`client_input_registered_before_automatic_claim_rejects_shadow_without_lifecycle`
deterministically exercises the losing automatic path. Other tests cover stale
epochs, busy and Plan states, pending work, cancellation, replacement reports,
duplicate delivery, UTF-8 bounds, typed wire shape, legacy and paginated history,
rollout persistence, app-server replay, TUI live/replay rendering, slash
commands, and Shadow-only origin suppression. Goal, user, unspecified, and other
extension origins remain eligible for later Shadow scheduling.

## Provenance and release

The provenance document and verifier consistently record the target tag and
peeled source commit. Reconstruction uses this ordered chain:

1. `patches/goal-old-continuation.patch`, SHA-256
   `eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`,
   applied with deterministic three-way semantics using preimage commit
   `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`.
2. `patches/shadow-mind.patch`, SHA-256
   `d5723f568621bff708a05e453c50afdab0d59ba14b3e18fada9c7ff8ba78bd96`,
   applied directly.

The source tree digest is
`03e456e8661fb38e4034a4caf4b63c7d1a7b2a37fae14b3987b3c522d26d9ac1`;
the rebuilt digest is
`b59ba57ac70a37aa5ccd335f130717e5de8c3ceb9ae95eb4483fd6e33748da8e`.
The only expected materialization differences are the three recorded `.vscode`
files. The source-side Cargo lock digest is recorded independently under
`source_file_sha256` as
`3f1ff14f28ffc173e63d2323bc11ec5b73d3b5f994c168e10272733b3b39444a`.

The exact local reconstruction completed successfully on 2026-09-07. The
provenance unit suite passed 18 tests and the release artifact audit suite passed
7 tests. Static checks also confirmed the immutable Goal hash, the Goal preimage
reference allowlist, absence of stale `rust-v0.146.0-alpha.3` references in the
active release surfaces, and clean non-vendored/staged diffs.

## Failed CI run and corrective delta

GitHub Actions run `34066769319` tested branch commit
`9257a8622233dd3676d9733de29ac003349738ee` and failed all three required jobs:
`Shadow runtime contracts`, `Rust checks`, and
`Goal and Guardian retry contracts`. The logs expose two blocking causes before
the intended Rust behavior tests could provide acceptance evidence:

1. `cargo fmt --all -- --check` reported formatter output in exactly six Rust
   files. The corrective diff applies the reported wrapping and import ordering
   only; it contains no runtime-policy edit.
2. Every `cargo test --locked` invocation stopped because Cargo wanted to update
   `Cargo.lock`. Static lock analysis found exactly 150 source-less workspace
   packages. Each corresponds to a local workspace manifest inheriting
   `workspace.package.version`; the target workspace version is `0.153.4`, while
   all 150 imported lock entries still recorded `0.0.0`. The corrective lock
   delta changes exactly those 150 versions to `0.153.4`. It does not add, remove,
   or retarget a dependency.

The corrected staging index and `codex-src/codex-rs` tree are byte-identical
apart from an ignored local `target` directory. The regenerated Shadow patch is
the exact binary diff of the staging index against Goal-only commit
`5352fbd14d09926a5217353f08a93c756c87c52a`; an independent regeneration and
`cmp` check succeeded. A replacement CI run remains required because the failed
run did not execute the full Rust acceptance surface.

GitHub Actions run `34068522523` then tested branch commit
`36326735d7823fd1fbe81b9388a452c6eea4055a` on 2026-09-07. Formatting and
provenance passed, but the three runtime/Rust jobs failed before behavioral
assertions. The Rust compiler exposed six integration defects: a stale duplicate
skills import, one field-style collaboration-mode access that must use the
upstream accessor, a missing `automatic_turn_origin`, two same-named cleanup
helpers with different reservation ownership, an invalid broad `PartialEq`
derive after adding `DisplayItem`, and one non-exhaustive `TurnInput` match. It
also reported one stale lifecycle import. The corrective delta preserves the two
reservation types as separately named helpers and narrows the serialization
test instead of adding equality to upstream `TurnItem`.

The same run found that upstream `0.153.4` has no `write_schema_fixtures` binary
target even though its `just` recipe invokes that name. CI now calls the
authoritative Python fixture generator directly. The retry job is renamed to
`Goal retry and upstream regression contracts`: Guardian remains an upstream
capability and is tested only because the fork's shared bounded-retry error
mapping can affect that upstream caller. It is not treated as a migrated fork
feature.

After these corrections, the Goal patch hash remains
`eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`. The
regenerated Shadow patch hash is
`8df949f057726149eef681533b2f463af01cbe3f219b61f5dd69318ef9525df5`. The
18 provenance unit tests, seven release-audit unit tests, exact two-patch
reconstruction check, stale-reference check, and diff checks pass locally. A
new remote CI run is still required for compilation and runtime evidence.

GitHub Actions run `34069926136` tested branch commit
`681d69c7e22a5a9f5f75a4ec201a4919129608d8` on 2026-09-07. Formatting,
provenance, schema generation/upload, and Bazel-lock generation passed. Rust
compilation failed before runtime assertions and exposed compatibility drift in
six authored integration files: removed or renamed session fields and turn-start
APIs, tuple-backed pending input, non-`PartialEq` turn inputs and response
envelopes, a stale Guardian test helper signature, a missing Goal stop-reason
import, and the removed `Op::UserInput` Shadow submission path. The corrective
delta adapts those call sites to the authoritative `0.153.4` APIs without
changing Goal retry policy, Shadow ownership semantics, or Guardian product
behavior.

The same run's generated schema artifact differed in exactly four files: three
JSON response schemas gained the generated `shadowReport` variant, and the
precomputed stable export archive changed accordingly. Those exact artifact
bytes were applied and compared byte-for-byte. Guardian-labelled CI coverage
remains only shared-upstream regression coverage for a touched retry/error
boundary. Guardian is not a fork migration feature, patch objective, or separate
upgrade capability. A replacement CI run is required for compiled behavior.

GitHub Actions run `34073233510` tested branch commit
`fecc7c42a7e1d2f7aec92b6022c7d6a6ba2753e6` on 2026-09-07. All three jobs
reported the same single rustfmt import-order correction in
`core/src/session/tests.rs`. Compilation then exposed two missing explicit
`TurnInput::FunctionCallOutput` no-op branches in one pending-input ownership
test and one missing `ThreadItem::ShadowReport` no-op branch in app-server media
filtering. The latter is correct because the typed Shadow report contains text
only and has no image or audio payload to remove. No additional compiler error
class appeared in the completed Goal/retry, Rust, or Shadow-runtime job logs.

The corrective delta changes only those three exhaustive matches plus the
formatter-requested import order. Both source trees are byte-identical for all
83 staged integration files, and an independently emitted cached diff matches
`patches/shadow-mind.patch` byte-for-byte. The Goal patch hash remains unchanged;
the regenerated Shadow patch and tree hashes are the values recorded above. A
replacement CI run is required before any runtime or release acceptance claim.

The subsequent pending-work review found a narrower ownership race before the
replacement run. Pending-work startup observed mailbox metadata while building
`TurnContext`, but final installation drained the mailbox's then-current full
contents. A message arriving between those operations could therefore enter a
turn whose trigger, service tier, output schema, cyber-access program, and
lineage were computed without that message. The corrective delta introduces
`PendingMailboxTurnStart`, carries one observed mailbox prefix and its start
metadata through the reservation, and drains exactly that prefix only after the
reservation is revalidated. Late arrivals remain queued. Context-construction
failure or user-turn replacement leaves the still-owned snapshot queued rather
than consuming it. Regressions cover exact-prefix draining and preservation of
all queued start-option fields.

The obsolete CI step that built and tested an intermediate Goal-only tree was
also removed. CI now tests `codex-goal-extension` continuation policy against
the final integrated `codex-src/codex-rs` tree, which is the artifact actually
shipped and includes the required Goal/Shadow compatibility cleanup.

GitHub Actions run `34077690289` tested branch commit
`571898866eda6f4cd700d33d7a442e2ec289e59b` on 2026-09-07. Rustfmt requested
only wrapping changes in `core/src/session/tests.rs`; those exact changes were
applied. Every named Guardian, Goal, and Shadow runtime step was then blocked by
the same compiler error before behavior execution: `tasks` named
`session::input_queue::PendingMailboxTurnStart`, but `input_queue` is a private
implementation module. This is not evidence of three independent behavior
regressions. The corrective delta narrowly re-exports
`PendingMailboxTurnStart` from the crate-visible `session` facade and changes
`tasks` to use that path. The type and all fields retain their existing
`pub(crate)` or narrower visibility; no Guardian, Goal, retry, or Shadow policy
changed.

The failure class is a cross-layer contract and change-propagation gap: a new
ownership token crossed the `session`/`tasks` boundary without an explicit
facade path, and static source checks could not prove compilation under the
project's remote-only Rust policy. The backend quality specification now records
the narrow crate-visible re-export rule. The regenerated Shadow patch is an
exact cached staging diff, all 84 staged integration files match `codex-src`,
and the local provenance and release-audit suites pass. A replacement CI run is
still required for compilation and runtime evidence.

GitHub Actions run `34078985075` tested branch commit
`bd45b02a92e758d8e25635bc20f622e226b9c9c8` on 2026-09-07. The Goal retry
and upstream regression job passed. The Shadow runtime job reached its focused
ownership regressions and failed only
`pending_work_start_does_not_steal_user_pending_input_after_reservation_replacement`:
the replacement user turn retained both queued inputs, but the trigger's
`TurnStartOptions` had become default values.

## Bug Analysis: Active-turn pending input lost mailbox start metadata

### 1. Root Cause Category

- **Category**: B - Cross-Layer Contract.
- **Specific Cause**: `TurnInputQueue` represented ownership of `Vec<TurnInput>`
  but not ownership of the aggregated `TurnStartOptions` that belonged to those
  inputs. When pending-work ownership was replaced, the available-turn path
  drained mailbox items and metadata together, then copied only the items into
  `TurnState.pending_input`. A later read recovered the inputs from turn state
  but found no mailbox metadata and therefore returned default options.

### 2. Why Earlier Fixes Missed It

1. The reservation fix made the observed mailbox prefix immutable and delayed
   draining until ownership revalidation, but stopped tracing the data after the
   mailbox-to-active-turn transfer.
2. The facade fix made the reservation token compile across `session` and
   `tasks`, but did not change the narrower `TurnInputQueue` data model.
3. Static checks could prove patch and source consistency but could not execute
   the remote-only Rust regression that exposed the metadata loss.

Bayesian review began with mailbox-to-turn transfer loss as the dominant
hypothesis. The test proved both inputs survived, directly contradicting item
loss. Source tracing then showed ownership validation returns before draining on
a stale reservation, contradicting rollback loss. The exact point where metadata
disappeared was the `Vec<TurnInput>`-only active queue, raising confidence in the
cross-layer data-model cause above 95 percent.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Store pending items and their aggregated start options in one `TurnInputQueue` value. | Done |
| P0 | Test coverage | Keep the replacement regression and add a queue-level ordered-batch metadata merge regression. | Done |
| P1 | Documentation | Record the bundled ownership and merge contract in the backend quality specification. | Done |

### 4. Systematic Expansion

- **Similar issues**: Any future path that takes, clears, defers, or transfers
  pending input must account for both item bytes and start metadata.
- **Design improvement**: Queue methods own bundling and ordered metadata merge;
  callers no longer reconstruct that contract from separate values.
- **Process improvement**: Ownership reviews must trace data through the next
  storage boundary, not stop after proving reservation validation and draining.

### 5. Knowledge Capture and Counter-review

- [x] Updated the existing backend scenario instead of creating a duplicate rule.
- [x] Added structural bundled storage and focused regression coverage.
- [x] Confirmed no `src/templates/markdown/spec/` mirror exists in this repository.
- [x] Rejected leaving metadata in the mailbox, because the items have already
  moved and a later mailbox batch would no longer share their ownership.
- [x] Rejected duplicating the items, because that would violate exactly-once
  delivery.
- [x] Rejected weakening the regression, because all six start-option fields are
  part of the ownership contract.
- [x] Audited every no-options `TurnInputQueue::extend` caller. Triggering
  inter-agent input can use that path only when its start options have already
  been applied to the newly created `TurnContext`, or while steering an existing
  turn where start-only options intentionally do not apply. Other callers add
  user, response, display, or queue-only input. No evidence supports changing
  the queue merge semantics for this corrective delta.
- [x] Re-ran the caller audit across `turn_input`, idle injection, active-turn
  delivery, task completion, and cleanup. Start metadata is consumed only at the
  turn-start boundary; later take/clear operations intentionally discard it
  together with the owned items. No production path moves triggering mailbox
  input into active-turn storage without either carrying its options or having
  already installed those options on the active `TurnContext`.

## Bug Analysis: Shadow report variant missed TUI exhaustive consumers

### 1. Root Cause Category

- **Category**: C - Change Propagation Failure.
- **Specific Cause**: The public `ThreadItem::ShadowReport` variant was ported
  through protocol, persistence, history, and primary rendering, but two
  exhaustive matches in `tui/src/dynamic_tools.rs` were not updated. The latest
  tool-marker projection needed an explicit no-op, while turn summaries needed
  a typed Shadow report mapping.

### 2. Why Earlier Fixes Missed It

1. The semantic audit followed the report's primary live/replay path but did not
   enumerate secondary consumers of the public enum.
2. Static patch and provenance checks do not compile exhaustive Rust matches.
3. The two failures were grouped under the Rust/TUI CI job, separate from the
   focused Shadow runtime failure, so they required independent log inspection.

The initial hypotheses were an incomplete generated-schema update, a stale TUI
snapshot, or missed exhaustive consumers. The compiler identified the exact
uncovered variant at both match sites, driving the third hypothesis above 99
percent. Inspection then distinguished their contracts: a Shadow report is not
a tool marker, but it is durable turn content that summaries must preserve.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Compile-time | Keep exhaustive matches so a new public variant fails closed instead of disappearing behind a wildcard. | Done |
| P0 | Test coverage | Add a turn-summary regression that preserves Shadow identity and content. | Done |
| P1 | Documentation | Require an explicit semantic decision for every exhaustive public-enum consumer. | Done |

### 4. Systematic Expansion

- **Similar issues**: Any new `ThreadItem`, `TurnItem`, `ResponseItem`, or other
  cross-layer enum variant can affect summaries, filtering, replay, export,
  telemetry, and tool-marker projections outside its primary renderer.
- **Design improvement**: Retain exhaustive matches at representation boundaries
  and encode intentional non-applicability as a named variant arm.
- **Process improvement**: Search all consumers of a changed public enum before
  remote CI, then classify each match by preserve, ignore, or reject semantics.

### 5. Knowledge Capture and Counter-review

- [x] Updated the existing backend Shadow scenario with the exhaustive-consumer
  rule instead of creating a disconnected checklist.
- [x] Added explicit handling to both compiler-reported consumers.
- [x] Added focused coverage for the preserving summary path.
- [x] Confirmed the marker path should ignore the item because a Shadow report is
  durable textual history, not a tool invocation or completion marker.
- [x] Confirmed no `src/templates/markdown/spec/` mirror exists in this repository.
- [x] Rejected a wildcard match because it would hide the next public-enum
  propagation omission from the compiler.
- [x] Ran an AST-level source enumeration over all Rust files. It found 108
  `match` expressions containing `ThreadItem` patterns. Fourteen expressions
  explicitly spell all 20 public variants, and every one includes
  `ThreadItem::ShadowReport`; there are zero 19-of-20 matches missing only that
  variant. These exhaustive consumers cover app-server media filtering,
  protocol conversion, analytics, thread-store history/search, TUI replay,
  transcript projection, status feeds, summaries, and marker selection. The
  remaining matches are partial selectors, wildcard-based projections, or
  single-variant destructuring/tests rather than unreviewed exhaustive consumers.

GitHub Actions run `34083243977` tested branch commit
`81915ce7f637bde5311984b79ad669718280f047` on 2026-09-07. Its Rust,
Goal/retry, and Shadow-runtime jobs all reported the same rustfmt-only failure.
The formatter requested two line-wrapping changes in
`core/src/session/input_queue.rs` and `core/src/tasks/mod.rs`; no semantic
change was requested. Those exact mechanical edits were applied to both the
vendored source and integration staging tree before regenerating the Shadow
patch and provenance. The replacement run remains required for all compiled
behavior and completion evidence.

GitHub Actions run `34085782538` tested exact branch commit
`7905505c1ea9c4cfdce98d17a3d298671d25aa3b` on 2026-09-07. The Goal retry
and upstream regression job and the Shadow runtime job passed completely. The
Rust job passed formatting, provenance reconstruction, stable and experimental
schema generation/upload, Bazel generation, integrated Goal policy, Shadow,
app-server, and TUI checks, Shadow and extension-item tests, app-server protocol
and schema tests, Goal tests, the dropped-stream Goal lifecycle test with
Shadow enabled, changed TUI integration, lifecycle injection, and Bazel-lock
drift. It then failed at exactly two gates:

1. `cargo test --locked -p codex-rollout shadow_report` did not compile because
   the fork-authored Shadow persistence fixture omitted the upstream
   `ItemCompletedEvent.started_at_ms` field. Other fixtures in the same file
   use `Some(0)`; the correction applies that same explicit fixture value and
   does not change runtime persistence behavior.
2. The schema drift check reported only
   `app-server-exports-experimental.json.zst`. The generated stable archive
   already matched the repository at SHA-256
   `a157ea8a1c27ec21829c16081a1691b6c6fbc46ad00709ae00b8ef6afdfa08fc`.
   The old experimental archive hash was
   `05948c1ae7d50d2ec2d01153eeb4eb9b82cf6f7d851acb576ebb5fb201c38b2c`;
   the authoritative artifact hash is
   `f8f67ea5864e44d9beb85ac245fa69d8dae011aead778d426e1b9230d444340f`.
   The generated expanded JSON and TypeScript trees compare byte-for-byte with
   the checked-in expanded schemas, so the correction copies only the
   precomputed experimental archive bytes produced by that CI run.

Clippy was skipped only because the rollout gate failed earlier in the same job;
it remains pending rather than failed. After both corrections were applied to
`codex-src` and the integration staging tree, the Shadow patch was regenerated
as exactly `git -C .trellis/.runtime/upgrade-staging diff --binary HEAD`.
The immutable Goal patch remains
`eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`;
the new Shadow patch is
`d5723f568621bff708a05e453c50afdab0d59ba14b3e18fada9c7ff8ba78bd96`.
Local two-patch reconstruction succeeds with source tree hash
`03e456e8661fb38e4034a4caf4b63c7d1a7b2a37fae14b3987b3c522d26d9ac1`
and rebuilt tree hash
`b59ba57ac70a37aa5ccd335f130717e5de8c3ceb9ae95eb4483fd6e33748da8e`.
A new exact-SHA CI run remains required; run `34085782538` is not a green CI
result and must not be represented as one.

GitHub Actions run `34089015125` then tested branch commit
`eb19e98d7c6ed94f2c09e6b071ed6bff3891a36c`. Shadow runtime, Goal retry and
shared-upstream regression contracts, formatting, provenance reconstruction,
schema generation and drift, Bazel lock generation and drift, affected package
checks and tests, Goal lifecycle, and TUI integration all passed. The sole
failure was affected-crate Clippy with `-D warnings`: `TaskStartOwnership`
stored the 224-byte `PendingMailboxTurnStart` snapshot inline, triggering
`clippy::large_enum_variant`.

The corrective delta boxes only that enum field, boxes the snapshot at
reservation construction, and borrows it at mailbox consumption. This preserves
the same immutable snapshot, reservation ownership, and mailbox-prefix behavior;
it changes storage representation only and does not suppress the lint. The
correction is identical in `codex-src` and the integration staging tree. The
Shadow patch was regenerated from the complete staging diff and now has SHA-256
`9f3ec340a950cffeed509ce1398bca64d938134eee561279629c285c3f3d52ce`.
The immutable Goal patch remains
`eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`.
Exact two-patch reconstruction now records source tree hash
`962b4c0e74b3d6420a76346c255c19af22b30e81052b768028d0c842ae0603d1`
and rebuilt tree hash
`2bb966c5ad5649cfae4ca42c9851b30e69d976310bdc3c98256bfc6d1457276e`.
A replacement exact-SHA CI run is required before the branch can be accepted.

GitHub Actions run `34092736317` tested branch commit
`8876f72e33469ef8180e43bc6e020b20691f9ce2` on 2026-09-07. The Shadow
runtime job and the Goal retry/shared-upstream regression job passed. The Rust
job passed formatting, provenance reconstruction, schema and Bazel generation
and drift checks, all affected package checks and tests, the Goal lifecycle
test with Shadow enabled, TUI integration, and rollout persistence. Its only
failure was affected-crate Clippy with `-D warnings`: the upstream
`core/tests/suite/openai_file_mcp.rs` fixture imported the `body_json` matcher
without using it. The file uses `body_partial_json`; its `set_body_json` calls
are `ResponseTemplate` methods and do not consume the matcher import.

The corrective delta removes only that unused import from `codex-src` and the
integration staging tree. It changes no matcher, fixture behavior, Goal/Shadow
lifecycle, retry policy, or upstream runtime capability. The Shadow patch was
regenerated from the complete staging diff and now has SHA-256
`0a18b78fb6facc930ab70eb5e593633b23438c2a27a7c2a4737fc5c376151960`.
The immutable Goal patch remains
`eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`.
Exact two-patch reconstruction now records source tree hash
`6fba68d5b068e348a76f67a6cd18105af81809487501067db4727147aec5ac55`
and rebuilt tree hash
`6401db674bd8f27a75a8855524dbb95d1700964805afcab8dac6ab7c2c2ecbe1`.
A replacement exact-SHA CI run remains required before branch acceptance.

GitHub Actions still owns Rust formatting, compilation, package tests, Clippy
with `-D warnings`, app-server schema generation/drift, Bazel lock generation/
drift, and the six-target CLI release. The configured targets are Windows x64,
Windows arm64, macOS x64, macOS arm64, Linux musl x64, and Linux musl arm64. The
release audit must verify archive allowlists, binary and ZIP hashes, BUILD-INFO,
toolchain/target identity, and provenance. These remote results are pending and
must not be inferred from the local checks.

## Adversarial counter-review

The counter-review challenged the main conclusions as follows:

- Could the Goal retry change accidentally create unbounded requests? No for the
  tested post-handshake stream, 429, and 5xx paths: request/stream attempts still
  use provider budgets. The separate upstream unbounded branch requires a
  pre-handshake `ConnectionFailed` detail and additional feature/session/provider
  predicates. Remote runtime tests are still required to prove the compiled
  behavior.
- Could upstream execution protection contradict the no-breaker requirement? No.
  It counts failed execution-tool turns, not service failures. Removing it would
  be an unrelated regression against the authoritative baseline.
- Could Guardian's three-attempt review loop cap Goal continuation? No. Guardian
  owns an isolated review request and deadline; Goal continuation is evaluated
  after root turn termination and remains independent.
- Could cloning `guardian_agent_spawner` duplicate policy or agents? No. It
  duplicates a closure handle over the same weak manager. Spawning occurs only
  when a consumer invokes its copy.
- Could Shadow accept a turn after client input registered? The exact atomic
  claim prevents this. If client input registers first, automatic admission
  returns `Busy` before lifecycle mutation. If automatic admission claims first,
  it retains ownership through task installation and later client input follows
  the normal post-install path.
- Could accepted reports be erased by the next turn's lifecycle callback? No.
  Accepted values have already moved from the Shadow runtime map into core-owned
  turn state. Failed installation drains the detached reservation queue.
- Could generated schema files have been hand-edited into agreement? Local
  provenance proves the recorded patch reconstruction, but only the remote schema
  generator and drift check can prove generated-file agreement. AC8 therefore
  remains pending.
- Could the review be mistaken for independent expert evidence? No. This file and
  the task contract explicitly identify it as separate inline passes by the main
  session. No agent or `dbs-chatroom` child was dispatched.

No unresolved design disagreement was found. The remaining uncertainty is
execution evidence owned by GitHub Actions and the release workflow.

## Local validation results

All permitted local checks passed on 2026-09-07:

- `git diff --check -- . ':(exclude)codex-src/**'`.
- Staging base and cached diff whitespace checks.
- `python3 -m unittest tests/test_verify_provenance.py`: 18 tests passed.
- `python3 -m unittest tests/test_release_artifact_audit.py`: 7 tests passed.
- Exact two-patch `scripts/verify_provenance.py --check` reconstruction.
- Immutable Goal and regenerated Shadow patch SHA-256 checks.
- Full staging diff matches `patches/shadow-mind.patch` byte-for-byte, and all
  88 integration paths match their `codex-src/` counterparts.
- AST enumeration covers 108 `ThreadItem` match expressions with no exhaustive
  19-of-20 omission of `ShadowReport`.
- Stale old-tag scan and Goal preimage reference allowlist.
- CJK scan over `AGENTS.md` and the active task artifacts: no matches.

Rust formatting, compilation, tests, Clippy, schema generation, Bazel generation,
full CI, and native release builds were intentionally not run locally under the
project validation policy.

## AC1-AC12 evidence map

| Criterion | Current evidence | Status |
| --- | --- | --- |
| AC1 | Provenance JSON, verifier constants, README, and decisions all identify `rust-v0.153.4` / `3d2ee51c...`. | Locally proven |
| AC2 | Goal hash and patch order match; exact reconstruction succeeds with only three declared materialization differences. | Locally proven |
| AC3 | Focused core/app-server tests encode bounded stream/429/5xx retries, repeated exhausted turns, Active Goal persistence, distinct automatic turns, and eventual completion. | Test coverage present; remote execution pending |
| AC4 | Goal hook special-cases only `UsageLimitExceeded`; generic errors remain Active. The only retained three-turn protection is upstream execution-tool failure accounting. | Source and tests reviewed; remote execution pending |
| AC5 | Touched retry, Goal, Guardian, session, history, and rendering paths have focused non-regression tests without old-module replacement. | Scope reviewed; remote execution pending |
| AC6 | Typed wire, identity, UTF-8, ordering, ownership, pending/cancel, origin, persistence, app-server, and TUI tests are present. | Test coverage present; remote execution pending |
| AC7 | Staged scope treats the complete release as the baseline and limits the fork delta to Goal/Shadow plus shared-boundary compatibility. | Inline scope audit passed; final post-CI diff audit pending |
| AC8 | CI contains schema/Bazel generation and drift checks plus affected-crate Clippy with `-D warnings`. | Pending GitHub Actions |
| AC9 | CI and six-target release workflows contain the required gates and artifact audit. | Replacement exact-SHA CI and release run pending |
| AC10 | Current diff is scoped and rollback is documented as `632cc5b...`. | Pre-push audit passed; final post-CI audit pending |
| AC11 | Inline mode is persisted in `.trellis/config.yaml` and `AGENTS.md`; no child agent was dispatched. | Proven for work to date |
| AC12 | Persisted active-task artifacts and `AGENTS.md` pass the no-CJK scan. | Proven for current files; rerun after any later edit |

The task and active Goal must remain open. AC8 and AC9 are unproven until the
remote Rust/schema/Bazel checks, full CI, and six-target release audit complete.

## Integration history boundary

The upgrade branch may retain multiple reviewable checkpoint commits, including
temporary `fix:` commits produced while remote CI reveals compatibility drift.
Those commits are development evidence, not independently meaningful product
changes. Final integration into `main` must squash the complete range from
pre-upgrade commit `632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5` through the
accepted upgrade result into exactly one atomic commit:

```text
feat: upgrade Codex baseline to 0.153.4
```

No upgrade-internal checkpoint or corrective `fix:` commit may enter `main` as
a separate commit. This preserves the first-principles boundary: the product
change is one baseline upgrade with the fork's existing Goal and Shadow
responsibilities integrated onto that baseline.
