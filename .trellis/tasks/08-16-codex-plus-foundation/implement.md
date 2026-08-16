# codex-plus 发行版地基 — 执行计划

1. Finish child planning artifacts and the four-section spike research.
2. Materialize the source snapshot and provenance/manifest verifier.
3. Add the transient Goal patch and concrete error/continuation regression tests.
4. Implement shadow host capability, registry/runtime, command surface, and tests.
5. Implement the Windows x64 CLI-only release workflow and allowlist checks.
6. Add README, decisions, licenses, trademark statement, and patch provenance.
7. Run child checks, parent integration checks, and the full completion audit.

Validation must include official commit checkout, patch dry-runs, ordered tree
hashes, concrete Goal error variants, shadow lifecycle/epoch tests, and release
artifact allowlist checks. Do not claim deterministic binary output.

Rollback points are the pristine, goal-only, and integrated tree manifests; each
can be rebuilt without mutating the source repository.
