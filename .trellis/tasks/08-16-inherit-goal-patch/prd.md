# 继承 Goal 基线

## Goal

把来源仓库 `custom-v26.5721.30844-goal-auto-retry` 的固定 Codex 快照和原始
Goal 补丁迁移到 `codex-plus`，产出可重建的 goal-only 基线；集成树直接保留
这一行为并叠加 Shadow，不再由 parent 追加 transient 窄化策略。

## Evidence coordinates

- Source repo commit `ea17de047b46e9584ffba2d2bda2dc3ae5a5aff8`.
- Upstream repo `https://github.com/openai/codex`, tag
  `rust-v0.146.0-alpha.3`, commit
  `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`.
- Rust toolchain `1.95.0`; source build was verified on Windows x64.
- Source snapshot materialization differences from pristine (Cargo.lock workspace
  versions, flattened bubblewrap LICENSE symlink, omitted `.vscode`) are recorded
  in provenance instead of being silently called “no differences”.

## Requirements

- R1 copy the source snapshot into `codex-src/` without generated build output;
  scripts accept `--source-root` and do not assume a nested `.git`; copy
  `goal-old-continuation.patch` into `patches/`.
- R2 rebuild pristine from the upstream commit, apply the original patch, and
  compare manifests/hashes to the goal-only snapshot; record expected materialized
  differences.
- R3 run the source regression and a real turn-error -> idle continuation test.
- R3a verify `shadow-mind.patch` applies directly after the original Goal patch and
  a real post-handshake stream disconnect still starts the next automatic turn.
- R4 preserve the exact source version/toolchain and provenance in README/decisions.

## Acceptance Criteria

- [ ] AC1 goal-only tree and original patch are present and hash-verified against
  the source snapshot.
- [ ] AC2 official commit and patch dry-run are independently verified; no source
  path on a particular developer machine is required.
- [ ] AC3 concrete `CodexErrorInfo` tests cover usage-limit pause and the inherited
  broad compatibility behavior in both goal-only and Shadow-integrated states.
- [ ] AC4 fixed-toolchain test/build commands are reproducible or explicitly marked
  unavailable on the current host.

## Out of Scope

Changing the inherited Goal error policy, Shadow implementation details, and release
publication belong outside this child.
