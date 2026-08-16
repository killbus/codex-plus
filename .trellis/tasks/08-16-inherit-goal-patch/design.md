# 继承 Goal 基线 — 技术设计

The child copies the source repository snapshot as the goal-only artifact. A
provenance verifier checks the upstream commit checkout, applies the original
patch, and compares an ordered manifest. It separately records known Windows
materialization differences instead of excluding arbitrary files.

The goal-only tree keeps the source behavior (“only UsageLimitExceeded pauses”) so
the inherited contract remains independently testable. The integrated tree applies
`goal-transient-continuation.patch` after the old patch; it restores native blocking
for permanent and unattributed internal errors while preserving continuation only
for the explicit transient matrix.

The verifier never mutates the source repository and uses temporary worktrees for
all patch applications. Removing the copied tree and patch is a complete rollback.
