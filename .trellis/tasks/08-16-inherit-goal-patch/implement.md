# 继承 Goal 基线 — 执行计划

1. Copy source `codex-src/` and the original Goal patch, excluding only `.git`,
   target/build output, and documented Windows materialization artifacts.
2. Add a provenance script with upstream URL/commit, patch hashes, ordered tree
   manifests, and explicit expected differences.
3. Verify official checkout -> original patch -> goal-only tree.
4. Run the concrete Goal regression and CLI release build when Rust 1.95 is present;
   otherwise retain the exact command and report the environment gate.
5. Verify Shadow applies directly to the goal-only tree, add the real stream-drop
   continuation regression in the integrated patch, and hand the two-patch chain to
   the release child.

Rollback: remove the newly copied `codex-src/`, patch, and provenance output.
