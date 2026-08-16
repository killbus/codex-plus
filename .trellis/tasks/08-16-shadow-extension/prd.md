# shadow-extension

## Goal

在 integrated Codex core 中语义移植 `pi-shadow-mind`：全局 Markdown registry、
per-thread 临时运行实例、受控并发、报告投递和 `/shadow` 管理面。参考实现只
作为行为基准，不把 TypeScript 包或运行时依赖复制进 Rust workspace。

## Reference

`https://github.com/liuzhengdongfortest/pi-shadow-mind`，MIT，commit
`ba75a67092024053f6529ef574d0cd81006ba6b1`。Child 1 的研究文档必须逐项引用
该版本和 Codex source file:line 证据。

## Requirements

- R1 `ext/shadow` crate 注册到 extension registry，并由 `Feature::Shadow`
  门控；未启用或 shadow 来源线程时无调度。
- R2 registry 使用有效 `codex_home/shadow-minds/`，顶层 Markdown + config，
  解析 frontmatter（id/name/enabled/debug/activation_probability/
  active_for_models/run_with_model/thinking_level/timeout_seconds/tools），
  last-known-good、冲突/损坏可见、原子替换写入。
- R3 每个主 turn 在 `on_thread_idle` 恰好一次 heartbeat；error/stop 只收尾。
  host 必须提供完成 turn/idle epoch；per-thread 实例快照定义，后台执行槽位与
  主线程注入串行分别验收，第一版不暴露未实现的全局并发承诺。
- R4 host 提供可取消的 `AgentSpawner`：继承 cwd/model/权限快照和净化轨迹，
  标记 shadow session source，禁止 shadow-of-shadow；新用户 turn、abort、
  timeout、thread stop 都取消并回收实例。
- R5 report 必须携带 source turn/epoch，并通过 active-turn 或 idle-epoch 的
  原子前提入口；迟到结果不得进入新 turn。批处理窗口只合并当前 epoch 报告。
- R6 `/shadow` 支持 list/status/enable/disable/pause/resume/edit/create；
  agent CRUD 工具与 config 写入先走 host approval/elicitation，拒绝即无写入。
- R7 默认只读工具 + 显式白名单追加，内置 `report_to_main` 终止单次 shadow；
  debug=true 保存 bounded metadata/session log，不泄露未授权参数。
- R8 首期只移植 registry 校验、scheduler/trajectory 的最小闭环、报告通道和
  list/status/pause/resume；summaries、batcher、entity CRUD 和全量 debug 语义
  在有独立契约前不进入 integrated patch。

## Acceptance Criteria

- [ ] AC1 feature gate、registry、last-known-good 和 malformed/duplicate tests 通过，
  并引用 `08-16-spike-validation/research/ground-facts.md`。
- [ ] AC2 一个主 turn 只产生一个 heartbeat；并发槽位、取消、超时、线程停止和
  shadow recursion tests 通过。
- [ ] AC3 active report 与 idle report 分别经 expected-turn/idle-epoch 原子入口；
  stale report 被拒绝并可观测。
- [ ] AC4 `/shadow` 全部子命令有可观察结果；agent/config 写确认与拒绝测试通过。
- [ ] AC5 工具白名单、报告终止、debug 日志、快照/无跨次记忆测试通过。
- [ ] AC6 首期 pi 参考语义的 registry、调度、轨迹和校验有对应测试；其余语义
  明确延期，不作为本 patch 的完成条件。

## Out of Scope

Shadow 间通信、学习/Gate、项目级 registry、跨次记忆、复杂 entity CRUD、主模型
thinking 暴露和官方 VSIX/桌面产物。

## Dependencies / order

Child 1 spike 与 Child 2 inherit 可并行；本 child 等两者的 evidence/baseline
后实现；CLI release 等 integrated shadow 通过 check。
