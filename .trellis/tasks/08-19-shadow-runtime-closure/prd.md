# Shadow runtime closure

## Goal

Close the native Shadow runtime around concurrent user work, epoch-scoped report
delivery, and observable end-to-end behavior. Tests must first fail deterministically
against the current implementation so the fix cannot be justified by self-confirming
helper tests.

## Background

- Native `ShadowReport` items, app-server mapping, TUI rendering, persistence policy,
  and Shadow-origin suppression landed in `a49161f`.
- The architecture is directionally correct, but the archived task has no production
  `run_shadow` end-to-end test and all acceptance boxes remain unchecked.
- Source review confirms three race windows: idle reservation before task installation,
  unpartitioned reports drained by an old-epoch delivery worker, and client user input
  entering before the runtime exposes pending user work to the idle gate.

## Requirements

- R1 add deterministic barrier/channel-based regression tests for all three confirmed
  races; do not use timing sleeps as the correctness oracle.
- R2 demonstrate that the tests fail on the current implementation before changing
  production code, and retain the failure evidence in task notes or commit history.
- R3 make idle reservation and task installation ownership-safe so concurrent user work
  cannot overwrite a Shadow turn, be overwritten by it, or be attributed to
  `Extension("shadow")`.
- R4 prevent cancelled or old-epoch workers from draining reports accepted for a newer
  epoch; report collection and delivery must preserve epoch ownership.
- R5 add a production-path Shadow integration test covering child completion, accepted
  report delivery, typed live lifecycle, one parent follow-up, and zero recursive Shadow
  spawn.
- R6 verify public attribution and replay: no Shadow report is exposed as a user item,
  and legacy/paginated resume plus TUI live/replay preserve identity, content, and order.
- R7 resolve parsed-but-unused Shadow frontmatter (`debug`, `thinking_level`, `tools`)
  explicitly: either implement documented behavior with tests or remove unsupported
  fields from the accepted contract. Do not silently leave parse-only configuration.

## Acceptance Criteria

- [ ] AC1 each confirmed race has a deterministic red test that fails on `a49161f` and
  passes after the fix.
- [ ] AC2 concurrent user input and Shadow delivery result in exactly one correctly
  owned active turn; no pending input is lost and user input is never tagged Shadow.
- [ ] AC3 an old/cancelled epoch worker cannot drain or reject a newer epoch's report.
- [ ] AC4 one real Shadow report emits one `shadowReport` started/completed pair, no
  user-attributed item, one main-Agent follow-up, and no recursive model request.
- [ ] AC5 Shadow-origin is observed through the completed `ThreadIdleInput`, including
  normal completion and relevant abort paths; ordinary turns remain eligible.
- [ ] AC6 stale, busy, Plan, pending user work, cancellation, timeout, and thread stop
  produce no visible report and no Shadow follow-up.
- [ ] AC7 legacy and paginated public reads plus TUI live/replay agree on Shadow id,
  display name, bounded content, and relative order.
- [ ] AC8 temporary mutation checks prove that removing origin, display delivery, or
  legacy persistence makes the corresponding end-to-end test fail.
- [ ] AC9 GitHub Actions runs the new integration tests and all affected Rust checks.

## Out Of Scope

- Goal continuation policy, `goal-old-continuation.patch`, HTTP 429/5xx behavior, and
  Guardian approval policy.
- New Shadow product features, model selection policy, cross-Shadow communication, or
  persistent Shadow memory.
- Broad refactors unrelated to the confirmed runtime races and evidence gaps.
