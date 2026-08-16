# codex-plus 发行版地基

## Goal

建立 `codex-plus`：以固定 upstream Codex CLI 源码为可审计基座，保留来源
仓库的 Goal 自动续跑行为作为 goal-only 基线，再在集成树中收敛为“临时网络
波动不阻断、永久错误不盲目循环”的错误矩阵，并叠加 shadow-mind 语义移植和
仅 CLI 的可验证发布流水线。

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
  `integrated`（Goal 窄化补丁 + shadow）。`codex-src/` 最终是 integrated，
  goal-only 在临时 worktree/验证脚本中重建。
- 原始 `goal-old-continuation.patch` 原样保存为血缘基线；集成使用
  `goal-transient-continuation.patch`，只放过临时错误矩阵。
- shadow 只在 `on_thread_idle` 触发一次 heartbeat；`on_turn_error` 与
  `on_turn_stop` 负责取消/收尾，按 `turn_id` 去重。
- shadow 报告必须经带 `expected_turn_id` 的原子注入入口；没有前提检查的
  `inject_if_running` 不得用于报告投递。
- release 首期只发布 Windows x64 CLI archive；输出白名单禁止 VSIX/桌面产物。
- child DAG：`spike || inherit -> shadow -> cli-release`；parent 只负责骨架、
  决策记录和最终集成验收。

## Requirements

- R1 骨架：README、LICENSE/NOTICE、`.gitignore`、`patches/`、`codex-src/` 和
  provenance/验证脚本。
- R2 基线迁移：官方 commit 树可重建，原始来源快照可逐文件复现，Goal-only
  回归通过；所有树和补丁有 hash 记录。
- R3 Goal 行为：429（非用量限制）、明确的 5xx、连接失败、SSE 连接失败/中途
  断流、重试耗尽且状态缺失/429/5xx 保持 Active；UsageLimit、预算、400、认证、
  沙箱、配置、内部 agent 故障等永久/本地错误按原生终止状态处理。当前
  `InternalServerError` 不带来源字段，集成版按终止处理，直到 host 提供可验证的
  远端来源/状态字段。
- R4 shadow：全局 Markdown registry + per-thread 运行态、exactly-once
  heartbeat、并发槽位、取消/超时/递归防护、原子 epoch 投递、`/shadow`
  list/status/pause/resume，以及 pi 语义 conformance tests。
- R5 release：固定源码/锁文件/toolchain 的可重建 CLI archive，附 LICENSE、
  NOTICE、非官方商标声明、SHA-256 和 BUILD-INFO；不包含 VSIX/桌面资产。
- R6 规划工件：spike 有四项 file:line research；inherit/shadow/release
  各有 prd/design/implement 和真实 check/implement context；parent 汇总跨
  child 验收。

## Error matrix

| Error | Goal disposition |
| --- | --- |
| `UsageLimitExceeded`, `SessionBudgetExceeded` | pause/limit; no continuation |
| `BadRequest`, `Unauthorized`, `SandboxError`, `ContextWindowExceeded`, `CyberPolicy`, local config errors | native terminal/block; no continuation |
| `ServerOverloaded` | keep Active for idle continuation |
| `InternalServerError` (unattributed) | native terminal; no continuation |
| `HttpConnectionFailed`, `ResponseStreamConnectionFailed`, `ResponseStreamDisconnected` | continue when status is absent, 429, or 5xx; otherwise terminal |
| `ResponseTooManyFailedAttempts` | same status rule as above |

## Acceptance Criteria

- [ ] AC1 README and `docs/decisions.md` state the three tree states, upstream/source
  coordinates, error matrix, pi reference, and CLI-only release boundary.
- [ ] AC2 `patches/` contains the original goal patch, the transient integration
  patch, and shadow patch; each applies cleanly to its declared base.
- [ ] AC3 pristine -> goal-only -> integrated tree manifests/hashes are verified;
  no circular comparison against only the vendored source is accepted.
- [ ] AC4 transient and permanent error tests prove Goal status and a real
  error -> idle -> next-turn continuation path, including a bounded consecutive
  transient-failure circuit breaker.
- [ ] AC5 shadow tests prove one heartbeat per main turn, cancellation/timeout,
  max parallel execution, atomic expected-turn rejection, and no shadow recursion.
- [ ] AC6 release workflow emits only the declared CLI/license/checksum metadata
  whitelist and fails when any VSIX/desktop file is present.
- [ ] AC7 all child planning artifacts and check manifests are present; child
  dependencies follow `(spike || inherit) -> shadow -> cli-release`.

## Out of Scope

- Official VSIX, desktop application, marketplace packaging, OpenAI branding or
  implied endorsement.
- Deterministic byte-identical binaries; this task promises fixed-source/toolchain
  rebuildability and records artifact hashes.
- Shadow-to-shadow communication, learning/Gate scheduling, project-level registry,
  cross-session memory, and cross-process registry locking beyond the minimum atomic
  replacement/lock needed for the first release.

## Risks / deferred items

- A shadow host capability is required for spawning and cancelling child threads;
  implementation must add the smallest explicit API rather than reaching through
  private core internals.
- Registry writes need atomic replacement and a host approval/elicitation path;
  if the host cannot expose that path, agent CRUD remains proposal-only until it can.
- Windows x64 is the only release platform verified by the source environment;
  other platforms are a follow-up, not an untested promise.
