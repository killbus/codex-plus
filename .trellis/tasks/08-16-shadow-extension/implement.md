# shadow-extension — 执行计划

1. Add feature flag, extension crate, registry/config types, and unit tests.
2. Add host `AgentSpawner` and atomic expected-turn injection capability with core
   lifecycle tests; wire source metadata and recursion guard.
3. Port trajectory sanitization, scheduler, run manager, report batcher, summaries,
   and registry validation from the pinned pi reference.
4. Add `/shadow` commands, status state, pause/resume, and approval-backed mutation
   tools; add TUI snapshots where output changes.
5. Add integration tests for exactly-once lifecycle scheduling, epoch cancellation,
   concurrent slots, stale injection, whitelist/approval, and debug logs.
6. Run `just fmt`, scoped `just test -p ...`, and scoped `just fix` per source AGENTS;
   record unavailable platform checks explicitly.

Risky files: extension registry/host capability, session injection, TUI command
routing, and workspace Cargo manifests. Roll back by removing the crate/registration
and rebuilding the integrated tree from goal-only.
