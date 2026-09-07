# Upgrade Codex to the latest stable release

## Goal

Upgrade `codex-plus` from the pinned `rust-v0.146.0-alpha.3` upstream snapshot to
the complete, authoritative `rust-v0.153.4` release. Port the fork's existing
Goal continuation and Shadow integration onto that baseline without decomposing
or redefining upstream behavior. Keep the reproducible patch chain and
six-target CLI release contract.

## Background and confirmed facts

- Repository HEAD is `632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5`; the same commit is on
  `origin/main` and `origin/fix/shadow-runtime-closure`. Baseline CI run
  `32451531000` passed before this upgrade task was created.
- The current upstream baseline is OpenAI Codex tag `rust-v0.146.0-alpha.3`,
  commit `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`.
- As of 2026-09-06, GitHub marks `rust-v0.153.4` as the latest non-draft,
  non-prerelease release. It was published on 2026-09-04. The annotated tag
  object is `042fb41b7c813ac7999105e886b2b7aa715b5081`; the source commit it resolves
  to is `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. Provenance must pin the source
  commit, not the tag object.
- The upstream delta contains 1,627 commits and 3,587 changed files, including
  3,432 paths under `codex-rs/`.
- `goal-old-continuation.patch` applies cleanly to the target source through a
  three-way application and must remain byte-for-byte unchanged. A direct
  application does not work on the new source.
- Applying the current `shadow-mind.patch` after the Goal patch leaves 25
  conflicts across core/session lifecycle, extensions, Goal, app server,
  protocol/history, rollout, and TUI. This is a semantic migration, not a patch
  refresh.
- Both the current tree and target release use Rust `1.95.0`; no Rust toolchain
  upgrade is required.

## Requirements

### R1. Stable upstream target

- Pin the vendored source and provenance to source commit
  `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` for tag `rust-v0.153.4`.
- Do not follow `main`, `rust-v0.154.0-alpha.4`, or another prerelease as part
  of this task.
- Retain upstream `0.153.4` architecture and behavior unless a documented fork
  contract below requires a deliberate override.
- Treat the release as the complete baseline, not as a partial feature set to be
  filled in by this fork. The fork migration scope is its existing Goal and
  Shadow responsibilities plus the minimum compatibility glue they require.

### R2. Goal continuation contract

- Keep `patches/goal-old-continuation.patch` unchanged, including SHA-256
  `eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6`.
- For disconnected response streams, ordinary HTTP 429, and transient HTTP 5xx,
  preserve bounded request behavior and the Goal continuation contract on the
  new baseline. Any fork delta must be limited to what Goal/Shadow integration
  requires, not framed as adding a general capability to upstream.
- If request retries are exhausted, the Goal remains Active and the idle
  lifecycle automatically starts another turn without requiring user input.
  This outer continuation has no consecutive-failure cap: bounded retry applies
  to one request/turn budget, not to whether the active Goal keeps trying.
- `UsageLimitExceeded` remains the distinct pause/accounting case and does not
  auto-continue.
- Do not add a transient-only Goal classifier or a consecutive-failure circuit
  breaker.

### R3. Upstream baseline non-regression contract

- Preserve the complete upstream `0.153.4` behavior as the baseline rather than
  enumerating selected upstream capabilities as migration deliverables.
- Make only the compatibility changes required where Goal/Shadow integration
  touches shared upstream boundaries. Do not port old upstream modules, present
  upstream behavior as a fork feature, or broaden the patch to reimplement it.
- Verify non-regression on every upstream path actually touched by the
  Goal/Shadow integration.

### R4. Shadow contract

- Preserve the typed internal `shadow.report` item and public app-server
  `shadowReport` item.
- Preserve one bounded report body shared by display-only and model-visible
  representations, with stable identity and ordering.
- Preserve idle-epoch and pending-work ownership checks, cancellation cleanup,
  and atomic acceptance of an idle automatic turn.
- Suppress feedback only for Shadow-origin automatic turns. User turns, Goal
  continuations, unspecified turns, and other extension origins remain eligible.
- Preserve legacy and paginated history, rollout persistence, app-server replay,
  and TUI live/replay rendering.

### R5. Reproducible provenance

- Keep the ordered chain `goal-old-continuation.patch` then
  `shadow-mind.patch`.
- Enhance provenance reconstruction to apply the immutable Goal patch
  deterministically with three-way semantics against a real Git object store.
- Regenerate `shadow-mind.patch` from the target Goal-only state to the final
  integrated tree; do not hand-edit generated schema fixtures into the patch.
- Regenerate `docs/provenance.json` and update all source/tag/hash references in
  release metadata and documentation.
- Deterministic patch, manifest, schema, checksum, or allowlist mismatches fail
  immediately. Only upstream network fetches receive bounded retry.

### R6. Release and validation contract

- Keep Rust `1.95.0` and the existing six native CLI targets unless the target
  source proves a target-specific dependency contract must be updated.
- Keep complete Goal, Guardian, Shadow, app-server, protocol/schema, rollout,
  TUI, clippy, provenance, Bazel-lock, release allowlist, smoke, and artifact
  audit coverage.
- Run local static and script-level checks only. Rust build, test, clippy, and
  cross-platform release checks run in GitHub Actions.

### R7. Agent dispatch contract

- Before every implementation, research, or checking agent is dispatched, the
  main agent must first use the standard `set goal` mechanism for that specific
  agent.
- The dispatched agent's goal must explicitly include the stream-disconnect, HTTP
  429, and transient HTTP 5xx backoff-and-continuation policy.
- Do not substitute a dispatch prompt, injected instruction, or implicit inherited
  context for the required goal-setting operation. The agent must not start until
  its goal has been set successfully.
- While an agent is running, the main agent actively checks status and results,
  handles retry/recovery, and assigns follow-up work when evidence remains
  incomplete; it must not wait passively.
- If the current platform cannot set a persisted Goal on an agent thread before
  dispatch, this task must run in Codex inline mode. Missing tooling never permits
  emulating the requirement with prompt text or dispatching first and setting the
  Goal afterward.

### R8. Independent cross-audit contract

- At the semantic-integration checkpoint, patch/provenance checkpoint, and final
  completion audit, review the work through separate architecture, behavioral,
  provenance/release, and adversarial-assumption lenses. Follow each review with
  a counter-review that challenges unsupported findings and checks the actual
  trust and ownership boundaries.
- Record concrete evidence and unresolved disagreements; review consensus alone
  is not acceptance evidence. The final decision remains tied to AC1-AC12.
- When a platform supports compliant pre-dispatch Goal creation, use independent
  `gpt-5.6-sol` agents for these lenses. Under the current inline constraint, the
  main session performs distinct passes and must not misrepresent simulated
  perspectives as independently dispatched agents.
- A read-only `dbs-chatroom` may be used only if its implementation can run
  entirely in the main session. The currently installed skill mandates child
  agents, so it is unavailable under this task's inline constraint.

### R9. Persisted artifact language

- Write every Trellis and related agent-workflow artifact created or modified by
  this upgrade entirely in English, including plans, research, audits, review
  records, journals, agent instructions, and context manifests. If this upgrade
  modifies a pre-existing non-English workflow artifact, translate that entire
  artifact rather than leaving mixed-language content.
- User-facing discussion may remain in the user's language, but it must not be
  copied into persisted workflow artifacts without an English translation.

## Acceptance criteria

- [ ] AC1: `docs/provenance.json`, `scripts/verify_provenance.py`, README, and
  decisions documentation consistently identify `rust-v0.153.4` source commit
  `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
- [ ] AC2: The immutable Goal patch hash is unchanged, the two-patch order is
  unchanged, and a clean provenance reconstruction exactly reproduces
  `codex-src/`.
- [ ] AC3: Automated tests prove disconnected streams, HTTP 429, and transient
  HTTP 5xx retry within a request and then preserve an Active Goal for a later
  idle automatic turn after exhaustion. Repeated failures continue this cycle
  without a consecutive-failure cap or a request for user intervention.
- [ ] AC4: Automated tests prove `UsageLimitExceeded` pauses separately and no
  consecutive-failure breaker or narrowed Goal error classifier exists.
- [ ] AC5: Focused non-regression tests cover every shared upstream path touched
  by Goal/Shadow integration, including its relevant retry and terminal-error
  cases, without importing or reimplementing old upstream modules.
- [ ] AC6: Shadow tests cover typed wire shape, display/model identity, UTF-8
  bounds, ordering, idle-epoch ownership, pending-work rejection, cancellation,
  Shadow-only self-feedback suppression, Goal eligibility, persistence, and
  TUI/app-server replay.
- [ ] AC7: Upstream `0.153.4` remains the authoritative complete baseline. The
  migration ports only the fork's Goal/Shadow responsibilities and required
  compatibility glue, without decomposing or relabeling upstream behavior as
  fork additions or overwriting new upstream implementations with old files.
- [ ] AC8: Generated app-server schemas and Bazel lock files have no drift after
  their generation jobs, and all affected crates pass `-D warnings`.
- [ ] AC9: The full GitHub Actions CI workflow is green on the upgrade branch,
  followed by a green six-target CLI release dry run or equivalent artifact
  validation before merge.
- [ ] AC10: The final diff contains no unrelated product changes, documents
  rollback to the pre-upgrade commit, and enters `main` as exactly one squashed
  commit named `feat: upgrade Codex baseline to 0.153.4`. Development checkpoint
  and corrective `fix:` commits may remain on the upgrade branch but do not enter
  `main` independently.
- [ ] AC11: If agents are used, dispatch records prove every
  implementation/research/check agent had its persisted Goal set through the
  standard mechanism before dispatch, that each Goal contained the required retry
  policy, and that the main agent performed active progress/recovery checks until
  delegated work completed. Otherwise, task evidence proves Codex inline mode was
  selected and no agent was dispatched.
- [ ] AC12: Every Trellis and related agent-workflow artifact created or modified
  by this upgrade is entirely written in English, with no mixed-language content
  left in a touched artifact.

## Out of scope

- Tracking upstream `main` or any `0.154.0` prerelease.
- Changing the reviewed Goal error policy, adding a failure-count breaker, or
  redesigning Shadow behavior.
- Adding release targets, changing publication channels, or changing toolchain
  version without evidence that `0.153.4` requires it.
- Broad refactors unrelated to adapting fork contracts to the new upstream
  architecture.

## Risks and deferred items

- The 25 conflict paths cross lifecycle ownership and public wire contracts, so
  migration errors can compile while still violating ordering or continuation
  behavior. Behavioral tests are the primary gate.
- Upstream response retry behavior now includes an unbounded connection-retry
  option and new telemetry. The implementation must reconcile this with the
  fork's bounded request retry contract rather than silently inheriting an
  unbounded mode for Goal or Guardian flows.
- Estimated implementation effort is 2-4 engineering days. This estimate is not
  an acceptance criterion.
