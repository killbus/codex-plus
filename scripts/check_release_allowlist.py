#!/usr/bin/env python3
"""Fail if a staged CLI archive contains anything outside the release allowlist."""

from pathlib import Path
import sys

ALLOWED = {
    "codex.exe",
    "LICENSE",
    "NOTICE",
    "TRADEMARKS.md",
    "BUILD-INFO.txt",
    "SHA256SUMS",
}
root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/stage")
files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
bad = sorted(files - ALLOWED)
if bad:
    print("release allowlist violation:", *bad, sep="\n", file=sys.stderr)
    raise SystemExit(1)
if "codex.exe" not in files:
    print("release allowlist missing codex.exe", file=sys.stderr)
    raise SystemExit(1)
print(f"allowlist ok: {len(files)} files")
