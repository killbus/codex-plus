# shadow-extension - Implementation Plan

1. Add `ShadowReportItem` and `ExtensionItem::ShadowReport` under `ext/items`; update exhaustive ids,
   serde/JSON schema/TypeScript tests, and any Bazel source lists.
2. Add the app-server `ThreadItem::ShadowReport` wrapper and conversion; cover JSON-RPC serialization
   and rollout-to-thread reconstruction.
3. Add a host-owned automatic-turn origin and an origin-aware atomic idle-start/delivery API. Surface
   the matching completed origin through `ThreadIdleInput` without changing ordinary user or Goal
   continuation behavior.
4. Change Shadow accepted-report delivery to atomically create one visible `shadow.report` lifecycle
   item plus one model-visible follow-up input, mark the turn origin as Shadow, and skip Shadow
   heartbeat when that origin completes. Bound report content once at a UTF-8 character boundary
   before creating both representations.
5. Persist completed Shadow report items for both legacy and paginated history modes; add policy and
   resume/read reconstruction tests.
6. Add a compact TUI history cell and route both live and replay completed items through it. Add
   snapshots for configured name, missing-name fallback, multiline wrapping, and replay parity.
7. Add end-to-end regressions for accepted delivery, duplicate idle, Shadow-origin suppression, Goal
   eligibility, stale/busy/cancelled/timeout/thread-stop rejection, and pending user work.

## Validation

Rust compilation, lint, schema generation, and tests are authoritative in GitHub Actions. The root
workflow must execute the affected package checks and regenerate/check committed app-server schema
fixtures. Local work is limited to static checks such as formatting, diff hygiene, Trellis validation,
and immutable Goal patch hashing.

GitHub Actions runs the affected checks from `codex-src/codex-rs`:

```text
just fmt
just test -p codex-extension-items
just test -p codex-app-server-protocol
just test -p codex-rollout
just test -p codex-shadow-extension
just test -p codex-core
just test -p codex-app-server
just test -p codex-tui
cargo insta pending-snapshots -p codex-tui
just fix -p codex-extension-items
just fix -p codex-app-server-protocol
just fix -p codex-rollout
just fix -p codex-shadow-extension
just fix -p codex-core
just fix -p codex-app-server
just fix -p codex-tui
```

The workflow also runs `just write-app-server-schema` and rejects fixture drift. It should publish the
generated schema tree as an artifact when drift is detected so the generated files can be committed
without hand editing. Run `just argument-comment-lint` in CI if the new API introduces positional
literals. Do not treat local compilation as a completion criterion.

## Risk And Rollback

- Highest risk: committing a display event before idle reservation, which can leave replay-visible
  reports with no follow-up. Keep display + input inside the accepted host delivery boundary.
- Highest compatibility risk: persisting only paginated items. Verify both history modes explicitly.
- Highest regression risk: suppressing every automatic turn instead of only Shadow origin. Include
  a Goal continuation eligibility test.
- Keep `patches/goal-old-continuation.patch` byte-identical. Roll back by removing the new item,
  origin-aware API, Shadow delivery mapping, persistence allowlist, and TUI cell as one coherent unit.
