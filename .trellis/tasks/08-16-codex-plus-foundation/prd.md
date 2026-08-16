# codex-plus 发行版地基

## Goal

建立 `codex-plus`：以固定 upstream Codex CLI 源码为可审计基座，原样保留来源
仓库的 Goal 自动续跑行为，并直接叠加 shadow-mind 语义移植和仅 CLI 的可验证
发布流水线。`goal-old-continuation.patch` 是最终 Goal 契约，不再追加错误分类或
连续失败熔断来覆盖它。

## Ground truth

- 来源仓库：`https://github.com/killbus/codex-goal-auto-retry-build`。
- 来源快照提交：`ea17de047b46e9584ffba2d2bda2dc3ae5a5aff8`，标签
  `custom-v26.5721.30844-goal-auto-retry`。
- 官方基线：`https://github.com/openai/codex`，标签
  `rust-v0.146.0-alpha.3`，commit
  `bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb`，Rust `1.95.0`。
- 来源快照已将构建物化差异纳入仓库（Cargo.lock workspace 版本刷新、Windows
  复制时 symlink 展平、`.vscode` 未纳入）；这些差异必须记录，不得声称只有
  两个文件变化。
- pi 参考实现：`https://github.com/liuzhengdongfortest/pi-shadow-mind`，MIT，
  commit `ba75a67092024053f6529ef574d0cd81006ba6b1`。只迁移可测试语义，不复制
  TypeScript 运行时或其依赖。

## Decisions

- 仓库名 `codex-plus`，feature-agnostic；扩展置于 `ext/`，补丁置于 `patches/`。
- 交付状态分三层：`pristine`（官方树）、`goal-only`（原始来源 Goal 补丁）、
  `integrated`（同一 Goal 行为 + shadow）。`codex-src/` 最终是 integrated，
  goal-only 在临时 worktree/验证脚本中重建。
- 原始 `goal-old-continuation.patch` 原样保存并直接用于集成；
  `goal-transient-continuation.patch` 属于未经用户要求的策略扩展，不进入最终链。
- shadow 只在 `on_thread_idle` 触发一次 heartbeat；`on_turn_error` 与
  `on_turn_stop` 负责取消/收尾，按 `turn_id` 去重。
- shadow 报告必须经带 `expected_turn_id` 的原子注入入口；没有前提检查的
  `inject_if_running` 不得用于报告投递。
- release 只发布 CLI archive，覆盖 Windows x64/ARM64、macOS x64/ARM64 和 Linux
  musl x64/ARM64；每个平台输出使用精确文件白名单。VSIX 不设独立门禁，也不进入
  本地 Trellis 之外的项目上下文。
- child DAG：`spike || inherit -> shadow -> cli-release`；parent 只负责骨架、
  决策记录和最终集成验收。

## Requirements

- R1 骨架：README、LICENSE/NOTICE、`.gitignore`、`patches/`、`codex-src/` 和
  provenance/验证脚本。
- R2 基线迁移：官方 commit 树可重建，原始来源快照可逐文件复现，Goal-only
  回归通过；所有树和补丁有 hash 记录。
- R3 Goal 行为：严格保留 `goal-old-continuation.patch` 的兼容契约；
  `on_turn_error` 仅对 `UsageLimitExceeded` 执行 usage-limit 停止处理，其他 terminal
  turn error 不阻塞 Active Goal，使 idle continuation 能自动开始下一 turn。不得按
  429/5xx、`Other`、认证或其他 variant 再窄化，也不得添加连续失败次数熔断。
  现有预算核算、用户中断、Goal complete/blocked 和 clear 行为保持不变。
- R4 shadow：全局 Markdown registry + per-thread 运行态、exactly-once
  heartbeat、并发槽位、取消/超时/递归防护、原子 epoch 投递、`/shadow`
  list/status/pause/resume，以及 pi 语义 conformance tests。
- R5 release：固定源码/锁文件/toolchain 的可重建 CLI archive，附 LICENSE、
  NOTICE、非官方商标声明、SHA-256 和 BUILD-INFO；拒绝任何未声明文件。
- R6 规划工件：spike 有四项 file:line research；inherit/shadow/release
  各有 prd/design/implement 和真实 check/implement context；parent 汇总跨
  child 验收。

## Goal continuation contract

| Turn error | Goal disposition |
| --- | --- |
| `UsageLimitExceeded` | apply inherited usage-limit handling; no idle continuation |
| every other `CodexErrorInfo` | leave Goal Active for idle continuation |

## Acceptance Criteria

- [ ] AC1 README and `docs/decisions.md` state the three tree states, upstream/source
  coordinates, inherited Goal continuation contract, pi reference, and CLI-only
  release boundary.
- [ ] AC2 `patches/` contains only the original Goal patch and Shadow patch; Shadow
  applies cleanly directly after Goal without a transient integration patch.
- [ ] AC3 pristine -> goal-only -> integrated tree manifests/hashes are verified;
  no circular comparison against only the vendored source is accepted.
- [ ] AC4 concrete network and `Other` turn-error tests prove Goal remains Active;
  a real post-handshake stream disconnect proves error -> idle -> next automatic
  turn with Shadow present. Usage-limit handling remains covered separately.
- [ ] AC5 shadow tests prove one heartbeat per main turn, cancellation/timeout,
  max parallel execution, atomic expected-turn rejection, and no shadow recursion.
- [ ] AC6 release workflow emits only the declared CLI/license/checksum metadata
  whitelist and fails when any undeclared file is present.
- [ ] AC7 all child planning artifacts and check manifests are present; child
  dependencies follow `(spike || inherit) -> shadow -> cli-release`.

## Out of Scope

- Non-CLI distribution, marketplace packaging, OpenAI branding or implied
  endorsement.
- Classifying permanent versus transient Goal errors, changing protocol error
  mapping solely for Goal, or adding a consecutive-error circuit breaker.
- Deterministic byte-identical binaries; this task promises fixed-source/toolchain
  rebuildability and records artifact hashes.
- Shadow-to-shadow communication, learning/Gate scheduling, project-level registry,
  cross-session memory, and cross-process registry locking beyond the minimum atomic
  replacement/lock needed for the first release.

## Risks / deferred items

- The inherited broad continuation contract can retry non-usage errors that another
  policy might consider permanent. This is an explicit compatibility decision, not
  a missing classifier; changing it requires a separate user-approved requirement.

- A shadow host capability is required for spawning and cancelling child threads;
  implementation must add the smallest explicit API rather than reaching through
  private core internals.
- Registry writes need atomic replacement and a host approval/elicitation path;
  if the host cannot expose that path, agent CRUD remains proposal-only until it can.
- The release matrix follows the source repository's native runners. Linux uses
  its pinned musl dependencies and the source-matched, checksum-verified official
  Codex `rusty_v8` archive/binding override; the default denoland release does not
  provide every musl target asset.
