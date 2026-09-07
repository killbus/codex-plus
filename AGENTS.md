<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Project Language

All persisted Trellis artifacts and all related agent-workflow artifacts must
be written in English. This includes task plans, PRDs, designs, implementation
plans, research, audits, review records, workspace journals, agent instructions,
and generated context manifests. User-facing conversation may follow the user's
language, but non-English conversation must not be copied into persisted
workflow artifacts. When an existing non-English workflow artifact is modified,
translate the entire touched artifact to English before completing the change.

## Codex Execution Mode

Use Trellis Codex inline mode as configured by
`codex.dispatch_mode: inline` in `.trellis/config.yaml`. Keep implementation,
research, and checks in the main session unless the platform can create and
activate a persisted Goal for a child agent before that child starts executing.
A read-only `dbs-chatroom` audit is allowed only if its implementation can run
entirely in the main session. The currently installed skill mandates child-agent
dispatch, so do not invoke it while inline mode is required. Never represent an
inline simulated perspective as independent-agent evidence.
