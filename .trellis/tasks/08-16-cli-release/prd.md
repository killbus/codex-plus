# CLI release pipeline

## Goal

在 integrated `codex-plus` 基线上构建并发布 Windows x64 CLI archive，提供完整
许可证/声明、非官方商标边界、来源与补丁 provenance、SHA-256，并以精确白名单
拒绝任何未声明文件。

## Requirements

- R1 workflow 固定 upstream commit、patch hashes、Cargo.lock、Rust `1.95.0`
  和目标 triple；先跑 Goal/shadow 回归，再构建 `codex-cli`。
- R2 archive 只允许 `codex.exe`、LICENSE、NOTICE、TRADEMARKS.md、SHA256SUMS
  和 BUILD-INFO.txt。
- R3 BUILD-INFO 记录 source commit/tree hashes、patch hashes、toolchain、runner
  和构建时间；README 不宣称 deterministic binary。
- R4 release job 在发布前执行输出白名单检查和 SHA-256 生成，任何额外路径失败。
- R5 workflow 使用最小 release 权限并在失败时不发布半成品。

## Acceptance Criteria

- [ ] AC1 workflow 在 Windows x64 runner 上成功测试、构建并生成 archive。
- [ ] AC2 archive 白名单、license/notice/trademark 和 BUILD-INFO 校验通过。
- [ ] AC3 allowlist negative check 在注入任意未声明文件时失败。
- [ ] AC4 SHA-256 可由独立命令复算；来源与补丁 provenance 可追溯。

## Out of Scope

非 CLI 发行物、marketplace 上传、其他平台二进制和字节级 deterministic build。
