# shadow-extension

## Goal

让 integrated Codex 中的 Shadow 报告成为可识别、可回放的原生线程条目，并阻止
Shadow 报告触发的主 Agent 自动跟进再次调度 Shadow。用户应能明确区分 Shadow
原文与主 Agent 回复，同时不会因无行动报告形成持续消耗轮次和额度的反馈链。

## Background

- Shadow registry、scheduler、child session、epoch guard 和 `/shadow` 基础管理面已经
  集成；本任务不重新实现这些能力。
- 当前报告在 `codex-src/codex-rs/ext/shadow/src/lib.rs:827` 被包装为
  `ResponseItem::Message(role = "user")`，文本前缀由同文件 `:905` 生成。
- `codex-src/codex-rs/core/src/hook_runtime.rs:586` 只记录该 `ResponseItem`，不发出
  `UserMessage`/turn-item 展示事件，因此 TUI 只显示随后主 Agent 的回复。
- `codex-src/codex-rs/ext/shadow/src/lib.rs:551` 对每个完成后 idle 的主线程 turn 都可
  再次 heartbeat；Shadow 自动跟进没有可信来源标记，因此会形成反馈链。
- 原生扩展展示边界位于 `codex-src/codex-rs/ext/items/src/lib.rs:15`；app-server
  转换位于 `app-server-protocol/src/protocol/v2/item.rs:905`；TUI live/replay 统一消费
  completed item（`tui/src/chatwidget/protocol.rs:362`、`replay.rs:80`）。

## Requirements

- R1 新增 namespaced `ExtensionItem::ShadowReport`（wire kind `shadow.report`），字段至少
  包含稳定 item id、shadow id、display name 和有硬上限的 accepted report content；app-server 暴露
  对应的 `ThreadItem::ShadowReport`，不复用 `UserMessage`、`SubAgentActivity`、
  `CollabAgentToolCall`、`HookPrompt` 或 review mode。
- R2 模型可见输入与用户可见条目必须分离：原有报告仍可作为单次主 Agent 跟进的输入，
  但展示条目必须明确归因于 Shadow，绝不渲染成用户气泡。缺少 `name` 时 display name
  在 registry 解析处继续稳定回退到 `id`。进入展示与模型输入的报告正文必须在 UTF-8
  字符边界按同一硬上限截断，避免无界模型上下文。
- R3 只有通过 idle epoch/active-turn 原子前提并真正获准投递的报告才发出一次标准
  `item/started` + `item/completed` 生命周期；stale、busy、cancelled、timed-out 或被
  拒绝的报告不得留下可见条目，也不得启动跟进。
- R4 host 为扩展启动的自动 turn 携带可信、非文本解析的 origin，并在下一次
  `ThreadIdleInput` 中暴露完成 turn 的 origin。Shadow 跟进以 namespaced Shadow origin
  启动；该 origin 完成后 Shadow scheduler 必须直接跳过。普通用户 turn、协作触发 turn
  和 Goal 自动 continuation 的现有资格保持不变。
- R5 live、`thread/resume`、legacy rollout 和 paginated item history 对同一报告呈现一致
  的 identity/content/order。必要时扩展 rollout persistence policy，使
  `ShadowReport` 的 completed item 在两种 history mode 都持久化。
- R6 TUI 使用独立 history cell，首行显示 `Shadow · <display name>`，后续显示已接受的有界报告；
  内容按既有 wrapping helper 换行，live 与 replay 走同一渲染入口并有 snapshot 覆盖。

## Acceptance Criteria

- [ ] AC1 live Shadow 报告显示为 `Shadow · reviewer`（或配置的 name）及有界正文，且不会
  出现用户消息归因；app-server JSON/TypeScript schema 包含 `shadowReport` item。
- [ ] AC2 resume/replay 在 legacy 与 paginated history mode 中显示与 live 相同的
  shadow id、display name、content 和相对顺序。
- [ ] AC3 一个被接受的 Shadow 报告最多启动一个主 Agent 跟进，并只产生一个可见报告
  条目；同一 idle epoch 的重复 delivery 不会重复显示或重复启动。
- [ ] AC4 Shadow-origin 跟进完成后不再调度 Shadow；普通用户 turn 与 Goal 自动 turn
  仍可触发正常 heartbeat，现有 Goal 行为与 immutable Goal patch 不变。
- [ ] AC5 stale、busy、cancelled、timed-out、thread stop 和 pending user work 路径均
  不产生可见报告或后续 turn。
- [ ] AC6 missing-name 回退、extension item serde/TS、app-server 映射、rollout policy、
  TUI live/replay snapshots 和反馈链回归测试全部通过。

## Out of Scope

- 不修改 `patches/goal-old-continuation.patch`、Goal pause/error policy 或 Goal prompt。
- 不扩展 `/shadow` CRUD、summaries、跨 Shadow 通信、跨次记忆、全量 debug 语义或
  registry 写入审批。
- 不把 Shadow 伪装成用户、协作 sub-agent 工具调用、hook 或 review session。
- 不承诺在本任务中新增 Luna 调度能力；模型选择研究与 runtime 功能变更分离。

## Dependencies / Order

本任务在现有 Shadow runtime 与已验证 Goal baseline 上增量实现。实现和验证必须留在
`.trellis/tasks/08-16-shadow-extension`，不得并入 `08-16-inherit-goal-patch`。
