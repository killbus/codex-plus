# codex-plus 发行版地基 — 执行计划

1. Finish child planning artifacts and the four-section spike research.
2. Materialize the source snapshot and provenance/manifest verifier.
3. Remove `goal-transient-continuation.patch` from the integrated source and every
   build/provenance reference without modifying `goal-old-continuation.patch`.
4. Apply Shadow directly after the inherited Goal patch and add a real
   post-handshake stream-disconnect -> idle -> next-turn regression test.
5. Retain Shadow host capability, registry/runtime, command surface, and tests.
6. Retain the six-target CLI-only release workflow and allowlist checks.
7. Update README, decisions, patch provenance, and source-tree hashes for the
   two-patch chain.
8. Run patch reconstruction locally, Rust checks through the pinned GitHub Actions
   workflow, parent integration checks, and the full completion audit.

Validation must include official commit checkout, direct Goal -> Shadow patch
application, ordered tree hashes, concrete `Other`/network/usage-limit Goal cases,
a real dropped SSE stream, shadow lifecycle/epoch tests, and release artifact
allowlist checks. Do not claim deterministic binary output.

Rollback points are the pristine, goal-only, and integrated tree manifests; each
can be rebuilt without mutating the source repository.
