# Decisions

- Source snapshot: `killbus/codex-goal-auto-retry-build` commit
  `ea17de047b46e9584ffba2d2bda2dc3ae5a5aff8`.
- Official baseline: `openai/codex` commit
  `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`, tag `rust-v0.146.0-alpha.3`.
- Tree states are pristine, goal-only, and integrated; patch order is fixed.
- Reference behavior is `liuzhengdongfortest/pi-shadow-mind` commit
  `ba75a67092024053f6529ef574d0cd81006ba6b1` under MIT. Only tested semantics
  are being ported; TypeScript runtime code is not copied.
- Shadow scheduling is one heartbeat at idle, guarded by completed-turn/idle epoch;
  errors and stops only cancel/close state. Reports require atomic active-turn or
  idle-epoch preconditions.
- Release is Windows x64 CLI-only. The archive uses an exact file allowlist and
  includes the license/notice/trademark bundle.
