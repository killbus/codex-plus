#!/usr/bin/env python3
"""Fail if a staged CLI archive contains anything outside the release allowlist."""

import argparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("root", nargs="?", default="dist/stage")
parser.add_argument("--binary", choices=("codex", "codex.exe"), default="codex.exe")
args = parser.parse_args()
ALLOWED = {
    args.binary,
    "LICENSE",
    "NOTICE",
    "TRADEMARKS.md",
    "BUILD-INFO.txt",
    "SHA256SUMS",
}
root = Path(args.root)
if root.is_symlink() or not root.is_dir():
    print(f"release stage is not a directory: {root}", file=sys.stderr)
    raise SystemExit(1)

entries = {path.name: path for path in root.iterdir()}
bad_names = sorted(entries.keys() - ALLOWED)
missing = sorted(ALLOWED - entries.keys())
bad_types = sorted(
    name
    for name, path in entries.items()
    if name in ALLOWED and (path.is_symlink() or not path.is_file())
)
if bad_names or missing or bad_types:
    if bad_names:
        print("release allowlist violation:", *bad_names, sep="\n", file=sys.stderr)
    if missing:
        print("release allowlist missing:", *missing, sep="\n", file=sys.stderr)
    if bad_types:
        print("release allowlist requires regular files:", *bad_types, sep="\n", file=sys.stderr)
    raise SystemExit(1)
print(f"allowlist ok: {len(entries)} files")
