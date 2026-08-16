# 继承 Goal 基线 — 技术设计

The child copies the source repository snapshot as the goal-only artifact. A
provenance verifier checks the upstream commit checkout, applies the original
patch, and compares an ordered manifest. It separately records known Windows
materialization differences instead of excluding arbitrary files.

The goal-only tree keeps the source behavior (“only UsageLimitExceeded pauses”) so
the inherited contract remains independently testable. The integrated tree applies
`shadow-mind.patch` directly after the old patch and does not override Goal error
handling. Patch-file inspection and a direct apply check prove the two patches have
no Goal-file conflict.

The verifier never mutates the source repository and uses temporary worktrees for
all patch applications. Removing the copied tree and patch is a complete rollback.
