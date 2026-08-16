# Decisions

- Source snapshot: `killbus/codex-goal-auto-retry-build` commit
  `ea17de047b46e9584ffba2d2bda2dc3ae5a5aff8`.
- Official baseline: `openai/codex` commit
  `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`, tag `rust-v0.146.0-alpha.3`.
- Tree states are pristine, goal-only, and integrated; the fixed patch order is
  `goal-old-continuation.patch` followed directly by `shadow-mind.patch`.
- The inherited Goal patch is the final continuation policy. Every terminal turn
  error except `UsageLimitExceeded` leaves the Goal active for idle continuation;
  no transient-only classifier or consecutive-failure breaker is layered on top.
- Reference behavior is `liuzhengdongfortest/pi-shadow-mind` commit
  `ba75a67092024053f6529ef574d0cd81006ba6b1` under MIT. Only tested semantics
  are being ported; TypeScript runtime code is not copied.
- Shadow scheduling is one heartbeat at idle, guarded by completed-turn/idle epoch;
  errors and stops only cancel/close state. Reports require atomic active-turn or
  idle-epoch preconditions.
- Release is CLI-only on Rust `1.95.0` for native Windows x64/ARM64, macOS x64/ARM64,
  and Linux musl x64/ARM64 runners. Each platform archive uses an exact file
  allowlist and includes the license/notice/trademark bundle. A post-build audit
  downloads all six artifacts and independently checks the external ZIP hash,
  embedded binary hash, BUILD-INFO target/provenance, and exact archive entries.
  Linux follows the source workflow's musl dependencies, including the
  source-matched official Codex `rusty_v8` archive/binding override after verifying
  both published checksums.
