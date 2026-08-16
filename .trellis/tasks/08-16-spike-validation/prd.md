# spike-验证

## Goal

收敛四项未验证项，产出带 file:line 证据的研究结论，作为 Child 3（shadow-extension）设计的定稿依据。避免"缺失全局约束造成设计债务"——四项全验。

## 确认事实（背景）

- 验证对象：`/home/agent/Src/codex-goal-auto-retry-build/codex-src`（固定的官方源码
  `rust-v0.146.0-alpha.3` + goal 补丁）；脚本参数化 source root。
- 决策记录：完全保真方向 = fork 核心；实体模型照搬 pi-shadow-mind（全局 registry）；结构定案"定义全局 + 运行实例 per-thread"。
- 四项未验证项及来源：
  1. `inject_if_running` 注入是否支持归属标记与消息角色（卡马克未确认项；参照 ext/goal/src/runtime.rs:428-440）。
  2. `expected_turn_id` 是否完整覆盖 pi 的 epoch 迟到结果丢弃语义（希基主张；参照 app-server-protocol/src/protocol/v2/turn.rs:175-217）。
  3. 单线程串行注入下 `max_parallel_shadows` 并发上限语义如何重新表述（希基未确认项）。
  4. agent 写 shadow registry 的确认通道落在哪条 permission/approval 路径（判官补盲区；对照 pi 的"写前确认"）。

## Requirements

- R1 验证 `inject_if_running`：注入的 ResponseItem 是否可携带归属标记（如 `<shadow id>`）与消息角色；找出可用机制，或确认不可行并说明替代。
- R2 验证 `expected_turn_id`：turn/steer 的前提门控能否等价实现"跨用户任务丢弃迟到结果"；与 pi epoch 语义逐条对照（新用户输入→中止旧 epoch shadow、迟到结果不投递、聚合窗口内过期结果丢弃）。
- R3 验证 `max_parallel`：per-thread 运行态 + 串行注入模型下，Pi 的并发上限语义该怎么重新表述；是否保留、以何种机制（如 per-thread 槽位 + 注入队列长度）。
- R4 验证 agent 确认通道：fork 核心里 agent 发起写 shadow registry（create/update/enable/disable/delete）时，确认落在哪条 permission/approval 路径；对照 pi 的"写前确认"要求。
- R5 四项结论合并写入 `research/ground-facts.md`，引用 file:line；无法确认的明确
  写"未确认"及原因。

## Acceptance Criteria

- [ ] AC1 `research/ground-facts.md` 下存在四个独立章节，每章含 file:line 证据链与结论。
- [ ] AC2 每项给出对 Child 3 的结论：支持 / 不支持 / 需设计取舍 + 理由。
- [ ] AC3 结论被 Child 3 的 prd/design 引用（引用关系可追溯）。
- [ ] AC4 本任务不写产品代码；全部产出为研究文档。

## Notes

- 验证方式以源码阅读为主，必要时用最小临时测试辅助；测试不保留为交付物。
- 本任务为研究型轻量任务，PRD + research；无 design/implement。
- 结论注明验证版本 `rust-v0.146.0-alpha.3`。
- 验证对象（codex-src）位于仓库外，引用路径注明绝对路径，不复制进本仓库。
