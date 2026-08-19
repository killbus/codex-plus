# 继承 Goal 基线 — 执行计划

1. Copy source `codex-src/` and the original Goal patch, excluding only `.git`,
   target/build output, and documented Windows materialization artifacts.
2. Add a provenance script with upstream URL/commit, patch hashes, ordered tree
   manifests, and explicit expected differences.
3. Verify official checkout -> original patch -> goal-only tree.
4. Run the concrete Goal regression and CLI release build when Rust 1.95 is present;
   otherwise retain the exact command and report the environment gate.
5. Verify Shadow applies directly to the goal-only tree, add real stream-drop,
   generic HTTP 429, and HTTP 5xx continuation regressions in the integrated patch,
   and hand the two-patch chain to the release child.
6. Add a failing Guardian classifier/request regression for generic HTTP 429, then
   extend only the existing bounded Guardian retry classifier; preserve terminal
   usage/quota, valid denial, cancellation, and timeout behavior.
7. Run the focused Goal and Guardian checks plus pinned formatting/static gates.
   Create behavior/test changes as `fixup!` commits for their owning historical
   commits, autosquash/rebase them, then regenerate `shadow-mind.patch` and
   provenance from the rewritten tree. Re-run the deterministic patch-chain check
   before pushing with `--force-with-lease` and following authoritative CI.

Rollback: remove the newly copied `codex-src/`, patch, and provenance output.
