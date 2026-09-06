# Implementation plan: Codex stable upgrade

## Preconditions

- Obtain explicit user approval of the final planning summary in a subsequent
  message, then run `task.py start`.
- Create/switch to `upgrade/codex-0.153.4` from commit
  `632cc5b11a7a071bf5a3d45ccecfefa9a56ebcf5`.
- Confirm the baseline CI run remains green and the worktree contains no
  unclassified user changes.
- Before every agent dispatch, use the standard `set goal` mechanism for that
  agent and include the full requirement to retry stream disconnects, HTTP 429,
  and transient HTTP 5xx with backoff and to continue without user intervention.
  Do not dispatch until that goal operation succeeds.
- Record each goal-before-dispatch event and actively monitor every running agent;
  inspect status/results and take retry, recovery, or follow-up action as needed.
- Current-session audit found no agent-targeted Goal operation available before
  `spawn_agent` starts work. Unless this capability is present when implementation
  begins, explicitly set `codex.dispatch_mode: inline` for the task and perform
  implementation/checking in the main session. Do not dispatch first and repair
  the Goal state afterward.
- Treat `0.153.4` as the complete upstream baseline rather than decomposing it
  into selected capabilities. The migration ports only the fork's existing Goal
  and Shadow responsibilities plus their necessary compatibility glue.
- Keep every Trellis and related agent-workflow artifact created or modified by
  this upgrade entirely in English. If a pre-existing non-English workflow
  artifact is modified, translate the entire touched artifact before accepting
  the corresponding checkpoint.

## Ordered implementation checklist

### Phase 1: Make provenance capable of preserving the immutable Goal patch

- Add Git-backed three-way patch application to `scripts/verify_provenance.py`.
- Keep network retry scoped to upstream fetch and fail closed on merge, patch,
  manifest, symlink, and recorded-output mismatches.
- Add Python regression fixtures for direct-apply failure, clean three-way Goal
  application, missing preimage objects, unresolved merges, and equivalent
  `--upstream-root` behavior.
- Checkpoint: provenance tests pass without changing `codex-src/`.

### Phase 2: Establish the new pristine and Goal-only states

- Materialize source commit `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`
  into a clean staging tree.
- Preserve the repository's explicit source materialization rules and inspect
  upstream symlink/Cargo-lock changes before copying.
- Apply `goal-old-continuation.patch` with deterministic three-way semantics and
  verify its SHA-256 remains unchanged.
- Checkpoint: the Goal-only tree reconstructs cleanly and retains upstream
  `0.153.4` Goal accounting structures.

### Phase 3: Port core lifecycle and Goal semantics

- Resolve session/task lifecycle conflicts against the new upstream APIs.
- Reintroduce trusted automatic-turn origin, idle epoch, and pending-work
  ownership without bypassing new upstream lifecycle state.
- Reuse the target baseline's existing transport and host behavior. Limit fork
  changes to the configuration and shared lifecycle compatibility required by
  the existing Goal/Shadow contracts.
- Restore Goal continuation behavior after retry exhaustion, automatically repeat
  across turns without a consecutive-failure cap, and keep `UsageLimitExceeded`
  separate.
- Add or adapt focused behavioral tests before moving to public representations.
- Checkpoint: the core/Goal integration diff is reviewable and contains no copied
  old upstream modules or failure-count breaker.
- Cross-audit checkpoint: independently inspect architecture ownership, runtime
  behavior, and assumptions; then run a counter-review against the actual diff
  and tests before accepting the phase.

### Phase 4: Port Shadow and public contracts

- Port the Shadow extension runtime and registry against the new extension API.
- Restore typed report delivery, display/model dual representation, UTF-8 bound,
  cancellation, stale/busy/pending rejection, and Shadow-only origin suppression.
- Port rollout/thread-store persistence, app-server protocol/history, and TUI
  live/replay/slash-command integration.
- Regenerate app-server JSON/TypeScript schemas and Bazel module lock through the
  existing GitHub Actions jobs. Apply generated outputs only from successful
  workflow artifacts.
- Checkpoint: all 25 original conflict paths are resolved semantically and public
  wire shapes remain stable.

### Phase 5: Rebuild the patch chain and release evidence

- Generate a new `shadow-mind.patch` as the exact diff from the target Goal-only
  state to the integrated tree.
- Replace `codex-src/` with that integrated result and regenerate
  `docs/provenance.json`.
- Update README, decisions, CI/release references, BUILD-INFO expectations, and
  any version-dependent `rusty_v8` release inputs/checksums.
- Verify no stale `rust-v0.146.0-alpha.3` or old source commit references remain
  outside historical task records.
- Checkpoint: a clean two-patch reconstruction matches `codex-src/` exactly.
- Cross-audit checkpoint: review patch ownership and provenance/release evidence,
  then challenge the review for false positives and unsupported attribution.

### Phase 6: Validate remotely and prepare merge

- Run local static/script checks listed below; do not run local Rust compilation.
- Push the upgrade branch and require all existing GitHub Actions jobs to pass.
- Retrieve generated schema/Bazel-lock artifacts if drift jobs identify expected
  updates, incorporate them, regenerate the Shadow patch/provenance, and rerun CI.
- Run the six-target CLI release workflow as a dry run or equivalent artifact
  validation. Audit exact archive contents, hashes, BUILD-INFO, target/toolchain,
  and provenance before merge.
- Perform a final diff review against every PRD acceptance criterion.
- Perform a final multi-lens completion audit and counter-audit. Use independent
  `gpt-5.6-sol` review agents only if each agent can create and activate its Goal
  before execution; otherwise perform clearly separated inline review passes and
  record that they are not independent agent evidence. Use `dbs-chatroom` only
  if it can operate without child-agent dispatch; the currently installed skill
  cannot, so use evidence-backed main-session passes instead.
- Audit agent orchestration records: every dispatch must be preceded by a
  successful standard goal-setting operation containing the retry policy, and
  every delegated run must show active status/result/recovery follow-up.
- If no compliant pre-dispatch Goal operation exists, verify inline mode was
  active for the full implementation/check cycle and that no agent IDs were
  created.

## Local validation commands

```bash
git diff --check -- . ':(exclude)codex-src/**'
git -C .trellis/.runtime/upgrade-staging diff --check \
  3d2ee51ca2d5db578f328aa75e20aa22c0197c9a..HEAD
git -C .trellis/.runtime/upgrade-staging diff --cached --check HEAD
python3 -m unittest tests/test_verify_provenance.py
python3 -m unittest tests/test_release_artifact_audit.py
python3 scripts/verify_provenance.py --check \
  --patch patches/goal-old-continuation.patch \
  --patch patches/shadow-mind.patch
! rg -n 'rust-v0\.146\.0-alpha\.3' README.md docs scripts .github
python3 - <<'PY'
from pathlib import Path

preimage = "bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb"
allowed = {
    Path("docs/decisions.md"),
    Path("docs/provenance.json"),
    Path("scripts/verify_provenance.py"),
}
candidates = {Path("README.md")}
for root, suffixes in (
    (Path("docs"), {".json", ".md"}),
    (Path("scripts"), {".py"}),
    (Path(".github"), {".md", ".yaml", ".yml"}),
):
    candidates.update(
        path for path in root.rglob("*") if path.is_file() and path.suffix in suffixes
    )
found = {
    path
    for path in candidates
    if preimage in path.read_text(encoding="utf-8")
}
if found != allowed:
    raise SystemExit(f"unexpected Goal preimage references: {sorted(map(str, found))}")
PY
! rg -n --pcre2 '[\p{Han}\p{Hiragana}\p{Katakana}\p{Hangul}]' \
  AGENTS.md .trellis/tasks/09-06-codex-stable-upgrade
```

The final `rg` result must contain only intentionally documented historical or
Goal-patch preimage references. Rust `cargo fmt`, tests, checks, clippy, schema
generation, Bazel lock generation, and native release builds run in GitHub
Actions per project policy.
The language-audit `rg` command must return no matches.

## Remote validation gates

- `shadow-runtime`: ownership, stale/cancelled epoch, and pending-work tests.
- `retry-contracts`: non-regression coverage for the touched upstream retry paths
  and Goal continuation after exhausted stream/429/5xx retries, including
  repeated automatic turns without a breaker or user-intervention request.
- `rust`: formatting, provenance, Goal-only compatibility, affected package
  checks/tests, schema drift, Bazel-lock drift, and `-D warnings`.
- `cli-release`: all six native targets, source-matched native dependencies,
  smoke tests, allowlists, checksums, BUILD-INFO, and final artifact audit.

## Risky areas and rollback points

- Provenance application semantics: revert Phase 1 independently if the clean
  three-way contract cannot be made deterministic.
- Core lifecycle ownership: keep Phase 3 separate from protocol/TUI changes so
  behavior regressions can be bisected.
- Generated files and patch regeneration: never retain partially regenerated
  schemas, lock files, or provenance. Revert to the previous checkpoint and
  regenerate from one accepted integrated tree.
- If any fork acceptance criterion cannot be preserved without discarding a new
  upstream capability, stop and return to planning for an explicit product
  decision instead of silently choosing one side.
