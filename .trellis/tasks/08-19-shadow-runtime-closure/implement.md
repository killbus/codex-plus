# Shadow runtime closure - Implementation Plan

1. Add deterministic failing tests for idle reservation/task installation, in-flight
   client user work, and old-epoch report draining. Capture the current failures.
2. Fix the host idle reservation so task installation cannot be overwritten and user
   work cannot be steered into a Shadow-origin turn.
3. Make Shadow report extraction epoch-owned and recheck cancellation/current epoch
   after acquiring the delivery permit.
4. Add a real `run_shadow`/app-server integration covering typed lifecycle, parent
   follow-up, request ordering, and feedback-loop suppression.
5. Add public legacy/paginated resume and TUI live/replay parity coverage.
6. Resolve unused frontmatter fields by implementation or contract removal, with
   behavior tests for the chosen contract.
7. Run focused CI checks, mutation probes, full affected-crate lint/tests, schema drift,
   ordered patch provenance, then update `shadow-mind.patch` and provenance.

## Validation

- No correctness test depends on a fixed sleep.
- Red tests are run against the pre-fix tree before production edits.
- GitHub Actions remains authoritative for Rust compilation and test execution.
- `patches/goal-old-continuation.patch` remains byte-identical.
## Rollback Points

- After red tests: no production behavior changed.
- After host reservation fix: core concurrency tests must pass before Shadow queue work.
- After Shadow queue fix: production-path delivery tests must pass before replay/TUI work.
