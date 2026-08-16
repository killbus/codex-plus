# CLI release pipeline — 执行计划

1. Add root LICENSE/NOTICE/TRADEMARKS.md and a CLI-only workflow.
2. Add provenance and allowlist scripts with negative VSIX/desktop tests.
3. Wire fixed toolchain Goal/shadow tests and CLI build.
4. Stage archive, BUILD-INFO, checksum, and release upload with least privilege.
5. Run workflow lint/static checks and local allowlist/checksum self-check.

Rollback is deleting the workflow and release staging files; no source tree changes
are needed to disable publication.
