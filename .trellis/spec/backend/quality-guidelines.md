# Quality Guidelines

> Code quality standards for backend and release infrastructure.

## Overview

Release workflows are infrastructure contracts: they must be reproducible from
the recorded source tree and fail closed before uploading an artifact. Rust
builds and tests run on GitHub Actions; the local agent performs only static and
script-level checks.

## Scenario: Cross-platform CLI release

### 1. Scope / Trigger

The CLI release workflow is triggered manually and builds the six source-backed
targets: Windows x64/ARM64, macOS x64/ARM64, and Linux musl x64/ARM64.

### 2. Signatures

- Workflow matrix fields: `platform`, `runner`, `rust_target`, `binary`, and
  `check_profile`, plus optional `musl`.
- Final CLI build environment: `CARGO_PROFILE_RELEASE_DEBUG=none` and
  `CARGO_PROFILE_RELEASE_STRIP=symbols`; these overrides are scoped to the
  distribution build step, not package tests or app-server checks.
- Allowlist command: `python scripts/check_release_allowlist.py <stage>
  --binary <codex|codex.exe>`.
- Provenance command: `python scripts/verify_provenance.py --check --patch ...`;
  only its upstream fetch is retried.
- Artifact audit command: `python scripts/audit_release_artifacts.py <download-root>
  --repository-commit <sha> [--provenance <path>]`; the provenance path defaults
  to the repository's `docs/provenance.json`, independent of the caller's cwd.

### 3. Contracts

Each matrix job pins `RUST_TOOLCHAIN=1.95.0` and exports `RUST_TARGET` and
`RELEASE_BINARY`. The staged directory contains exactly the target binary,
`LICENSE`, `NOTICE`, `TRADEMARKS.md`, `BUILD-INFO.txt`, and `SHA256SUMS`.
`BUILD-INFO.txt` records source commit/tree hashes, patch hashes, Cargo.lock
hash, toolchain, target, runner, and UTC build time. The uploaded artifact is a
platform-named ZIP plus its `.zip.sha256` file.

The workspace `release` profile intentionally retains symbolication data for
the upstream symbols-packaging phase. This repository does not publish a
symbols artifact, so the final CLI build applies the two workflow-local Cargo
profile overrides above. The resulting stripped binary is smoke-tested before
staging. Do not apply those overrides to Goal/Shadow tests or app-server checks,
and do not add a numeric binary-size gate as a substitute for finalizing the
distribution binary correctly.

Raw-byte provenance inputs use LF checkout through `.gitattributes`. The
verifier reads upstream mode-`120000` entries from the Git tree and hashes the
rebuilt symlink target even when Windows checks out a regular placeholder file.
It must not apply that normalization to the copied source: the source's flattened
`bubblewrap/LICENSE` remains an explicit materialization difference.
Manifest digests sort normalized POSIX path strings at the hash boundary; they
must not inherit `pathlib` ordering because Windows compares paths
case-insensitively. Stale output reports the differing top-level fields.

The four Windows/macOS rows use `check_profile: dev`; the two Linux musl rows use
`check_profile: release` for full Goal/Shadow package tests and app-server check.
This matches the source-backed musl build practice without narrowing test names.
Musl rows also derive the pinned `rusty_v8` version from the copied source, fetch
the matching archive, binding, and two-line checksum file from the official
`openai/codex` release, verify both checksums, and export `RUSTY_V8_ARCHIVE` plus
`RUSTY_V8_SRC_BINDING_PATH`. Their curl client retries transient HTTP, timeout,
disconnect, and connection failures; deterministic verification still fails.
The archive and binding directory includes both `GITHUB_RUN_ID` and
`GITHUB_RUN_ATTEMPT`. The `v8` build script tracks these override paths with
`rerun-if-env-changed`; a run-attempt-unique path invalidates a restored Cargo
fingerprint and forces the native archive to be copied into the current target
directory instead of relying on a large library from another runner's cache.

The downloaded-artifact auditor derives the expected source commit, source and
rebuilt tree hashes, source-side Cargo.lock hash, and ordered patch hashes from
the checked-out provenance document. It must not duplicate those values as
Python constants: the build jobs write `BUILD-INFO.txt` from the same versioned
document, and a second manually synchronized list can silently retain a removed
patch until the final release audit.

### 4. Validation & Error Matrix

- Missing target binary or any undeclared staged path -> allowlist failure.
- Injected undeclared file -> negative probe must fail before archive creation.
- Provenance mismatch, failed Goal/Shadow test, app-server check, CLI build, or
  `--version` smoke test -> matrix job fails and uploads no artifact.
- SHA-256 is computed after staging and independently covers both binary and ZIP.
- Missing/changed upstream symlink contract -> provenance failure.
- Windows symlink placeholder -> canonicalize only the rebuilt side; never erase
  the recorded flattened-source difference.
- Windows/POSIX path ordering difference -> sort manifest string keys inside the
  digest function, independent of dictionary insertion order.
- Upstream fetch 429/5xx/disconnect -> bounded fetch retry; deterministic
  manifest/patch mismatch -> immediate failure without rerunning the whole gate.
- Musl debug-profile native dependency failure -> use the declared release check
  profile, keeping complete package coverage.
- Missing default denoland musl `rusty_v8` archive -> use the checksum-verified
  official Codex release pair; do not drop the package or narrow its tests.
- Restored Cargo metadata references `rusty_v8` but its copied static library is
  absent -> change the override path identity per run attempt so the build script
  reruns and recopies the verified archive; do not rely on cache completeness.
- Missing, malformed, or structurally invalid audit provenance document -> fail
  before inspecting artifacts, without a traceback; do not fall back to embedded
  or hard-coded provenance values.
- Artifact `BUILD-INFO.txt` differs from the current provenance document -> fail
  on the exact field; preserve `patch_sha256` list order and use the source-side
  Cargo.lock digest recorded under `changed_files`.
- Missing distribution overrides -> the intentionally symbol-bearing Cargo
  intermediate may be archived directly; fail the workflow contract review and
  restore the scoped overrides rather than inventing a size threshold.

### 5. Good/Base/Bad Cases

- Good: a target stage has six allowlisted files and matching checksums.
- Base: a platform job is skipped only when GitHub does not provide its declared
  native runner; the workflow must then report failure rather than silently
  substituting another target.
- Base: native and placeholder checkouts of the known upstream symlink produce the
  same rebuilt manifest, while the flattened source still differs.
- Bad: a Windows binary is placed in a macOS/Linux archive, or an extra debug/log
  file remains in the stage; both are rejected.

### 6. Tests Required

- Run Goal and Shadow package tests and the app-server target check on every
  matrix target.
- Build `codex-cli` for the target and execute `<binary> --version`.
- Run allowlist positive, injected-file negative, and post-cleanup positive
  assertions before compression.
- Recompute the recorded checksums from the downloaded ZIP during artifact audit.
- Test the artifact auditor with independent synthetic provenance and BUILD-INFO
  fixtures, including changed tree hashes, source-vs-rebuilt Cargo.lock selection,
  ordered patch hashes, relative/default provenance paths, and malformed input.
- Unit-test native symlink and Windows-placeholder manifests, source-side
  flattening preservation, LF attributes, insertion-order-independent tree
  digests, stale-field diagnostics, and fetch-only retry.
- Static-test four `dev` plus two musl `release` matrix profiles and prove the
  package tests are not narrowed to one named case.
- Static-test musl curl retry configuration and the official Codex `rusty_v8`
  archive/binding/checksum override contract.
- Static-test that the musl `rusty_v8` artifact directory contains
  `${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}`, has one assignment, and does not fall
  back to the fixed `${RUNNER_TEMP}/rusty_v8` path.
- Static-test that both distribution overrides occur only in the unconditional
  final CLI build step and are absent from Goal, Shadow, and app-server checks.

### 7. Wrong vs Correct

Wrong: hard-code `codex.exe` in the allowlist and publish one Windows archive as
if it represented all platforms.

Correct: pass the matrix binary name to the allowlist, record the target in
`BUILD-INFO.txt`, and upload one independently validated archive per target.

Wrong: normalize both source and rebuilt symlink placeholders, which hides a
known source materialization difference, or retry the entire provenance check
after a deterministic mismatch.

Correct: derive the upstream symlink contract from Git objects, normalize only
the rebuilt manifest, and retry only the network fetch.

Wrong: copy only the musl Cargo profile from the source workflow and let Cargo
fall back to denoland assets that do not exist for every musl target.

Correct: copy the complete source-backed build contract: profile, native tools,
official Codex `rusty_v8` pair, checksum verification, and override environment.

Wrong: reuse a fixed `RUSTY_V8_ARCHIVE` path across workflow runs and assume a
restored Cargo target cache includes the copied native archive whenever its
build-script fingerprint is present.

Correct: keep the override stable within a job but include the GitHub run ID and
attempt in its directory, forcing `v8` to recopy the verified archive after a
cross-run cache restore.

Wrong: hard-code provenance hashes in the artifact auditor and copy the same
constants into its tests; both can agree while the versioned patch chain changes.

Correct: load the checked-out provenance document at runtime and use independent
synthetic fixture values to prove field mapping, Cargo.lock side, and patch order.

Wrong: treat `cargo build --release` as a publishable artifact even though the
workspace profile says packaging must strip the symbol-bearing intermediate, or
hide the mistake behind an arbitrary binary-size threshold.

Correct: scope `DEBUG=none` and `STRIP=symbols` to the CLI-only distribution
build, then smoke-test and hash those final bytes.

## Scenario: Auditable Goal and Shadow patch chain

### 1. Scope / Trigger

Apply this contract whenever Goal continuation behavior, Shadow integration, the
ordered patch list, or `codex-src/` provenance changes.

### 2. Signatures

- Goal hook: `GoalExtension::on_turn_error(TurnErrorInput)`.
- Ordered patches: `goal-old-continuation.patch`, then `shadow-mind.patch`.
- Provenance check:
  `python3 scripts/verify_provenance.py --check --patch patches/goal-old-continuation.patch --patch patches/shadow-mind.patch`.

### 3. Contracts

`goal-old-continuation.patch` is an immutable imported baseline with SHA-256
`eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6` and is also
the final Goal policy. `UsageLimitExceeded` uses inherited usage-limit handling;
every other terminal `CodexErrorInfo` leaves the Goal Active for idle
continuation. Shadow applies directly after that patch and must not add a Goal
error classifier or consecutive-failure counter.

### 4. Validation & Error Matrix

- `UsageLimitExceeded` -> inherited usage-limit state; no automatic next turn.
- Any other terminal turn error, including `Other`, stream disconnect, HTTP 429,
  or HTTP 5xx -> Goal remains Active and idle may start the next turn.
- Added transient/permanent matrix or fixed failure-count breaker -> contract
  violation even when patch provenance is internally reproducible.
- Clippy reports `ActiveGoalStopReason::TurnError` as never constructed after the
  imported Goal patch -> remove the unreachable variant and match arm in the
  following integration patch; do not edit the immutable Goal patch or suppress
  `dead_code`.
- Patch application, hash, or reconstructed manifest mismatch -> deterministic
  provenance failure; do not retry it as a network error.
- Upstream fetch disconnect/429/5xx -> retry only the fetch boundary.

### 5. Good/Base/Bad Cases

- Good: an SSE response sends headers and at least one event, closes without a
  provider terminal event, and a different automatic turn starts with Goals and
  Shadow enabled.
- Base: `UsageLimitExceeded` retains the imported pause/accounting behavior.
- Bad: a later patch blocks `CodexErrorInfo::Other` or blocks the fourth transient
  failure while README still claims the imported continuation contract.

### 6. Tests Required

- Goal backend tests assert `Other` remains Active and usage-limit handling remains
  distinct.
- App-server integration sends a post-handshake incomplete SSE response with
  in-turn retries disabled, asserts the failed turn completes, then asserts a
  different automatic turn starts and the Goal remains Active.
- Enable both Goals and Shadow in that integration test.
- CI and release provenance commands use exactly the two ordered patches.
- Verify the immutable Goal patch hash and reject any residual classifier/counter.
- Statically assert that the integrated Goal runtime has no unreachable
  `TurnError` stop reason while `on_turn_error` still special-cases only
  `UsageLimitExceeded`.

### 7. Wrong vs Correct

Wrong: treat provenance as product approval, then add a reproducible
`goal-transient-continuation.patch` that narrows errors and introduces a local
circuit breaker.

Correct: keep the imported Goal patch byte-for-byte unchanged, layer Shadow
directly on it, and use behavior tests plus ordered provenance to prove both the
policy and its reconstruction.

## Forbidden Patterns

- Do not run Rust compilation locally when the task requires GitHub Actions.
- Do not silently replace a missing native runner with a different target.
- Do not broaden an archive allowlist to make a failed build pass.
- Do not let `core.autocrlf` or `core.symlinks` decide provenance hashes.
- Do not let host `Path` comparison or directory iteration decide manifest hashes.
- Do not narrow musl regressions to one test merely to avoid a debug-profile
  native dependency failure.
- Do not treat a release profile as the complete musl dependency contract; audit
  the source workflow's prebuilt native inputs too.
- Do not assume a Cargo release-profile output is distribution-ready when its
  contract delegates symbol stripping to packaging.
- Do not add a numeric artifact-size gate for this contract; produce the correct
  stripped artifact directly.
- Do not infer a new Goal error policy from generic safety preferences; preserve
  the reviewed imported contract until the user approves a separate change.
- Do not modify the imported Goal patch or weaken clippy to hide dead code left
  unreachable by that patch; clean it up in the following integration patch.

## Required Patterns

- Keep source, patch, lockfile, toolchain, target, and artifact hashes in the
  workflow evidence.
- Keep platform-specific binaries and archive names derived from the matrix.
- Keep check profile explicit in every matrix row.
- Keep musl transient retries at the network-client boundary and verify downloaded
  native inputs before exporting them to Cargo.
- Keep musl `rusty_v8` override paths unique per GitHub run attempt so restored
  Cargo fingerprints cannot suppress native archive materialization.
- Keep release artifact audit expectations derived from `docs/provenance.json`;
  never maintain a parallel hash or patch list in the auditor.
- Keep symbol-removal overrides local to the final CLI distribution build.
- Keep workflow permissions at the minimum needed for the selected publication
  channel.
- Keep the Goal patch hash, ordered two-patch chain, vendored source, workflows,
  and provenance manifest synchronized.

## Testing Requirements

Every release change must pass static workflow/script checks locally and the
full matrix of Rust checks remotely. A release is not complete until each
platform artifact passes the allowlist and checksum audit.

## Code Review Checklist

- [ ] Matrix targets match the source-backed native runner set.
- [ ] Every row declares the intended check profile; musl keeps full package tests.
- [ ] Provenance is LF-stable and preserves flattened-source symlink evidence.
- [ ] Binary name and target are not hard-coded outside matrix metadata.
- [ ] Provenance, tests, smoke test, allowlist, and checksums run before upload.
- [ ] Negative allowlist coverage rejects an undeclared file.
- [ ] A dependent job downloads all six artifacts and rechecks both checksum layers.
- [ ] No unrequested distribution context or platform claim was added.
- [ ] Goal behavior matches the immutable imported patch, with no hidden narrowing
  patch or consecutive-failure breaker.
