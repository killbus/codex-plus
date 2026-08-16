# CLI release pipeline — 执行计划

1. Add root LICENSE/NOTICE/TRADEMARKS.md and a six-target CLI-only workflow.
2. Add provenance and allowlist scripts with a generic undeclared-file test.
3. Wire fixed toolchain Goal/shadow tests and CLI build.
   Use an explicit per-target check profile; musl keeps complete package coverage
   under the source-proven release profile.
4. Verify Windows placeholder/native symlink equivalence without erasing the
   recorded flattened-source difference; make tree digests independent of host
   path ordering and report stale fields.
5. Configure musl network-client retries and checksum-verified official Codex
   rusty_v8 archive/binding overrides while retaining full package tests.
6. Stage archive, BUILD-INFO, checksum, and release upload with least privilege.
   Scope the symbol-free Cargo profile overrides to the final CLI build only;
   do not add a numeric binary-size gate or a symbols artifact.
7. Download all six workflow artifacts and independently audit archive contents,
   BUILD-INFO, and both checksum layers.
8. Run workflow lint/static checks and local allowlist/checksum self-check.

Rollback is deleting the workflow and release staging files; no source tree changes
are needed to disable publication.
