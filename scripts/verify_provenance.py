#!/usr/bin/env python3
"""Verify an upstream commit, ordered patch chain, and source-tree manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


UPSTREAM = "https://github.com/openai/codex.git"
COMMIT = "bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb"
EXPECTED_MATERIALIZATION_DIFFERENCES = frozenset(
    {
        ".vscode/extensions.json",
        ".vscode/launch.json",
        ".vscode/settings.json",
        "codex-rs/Cargo.lock",
        "codex-rs/vendor/bubblewrap/LICENSE",
    }
)


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts or "target" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        result[rel] = digest(path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("codex-src"))
    parser.add_argument("--upstream-root", type=Path)
    parser.add_argument("--upstream", default=UPSTREAM)
    parser.add_argument("--commit", default=COMMIT)
    parser.add_argument("--patch", type=Path, action="append", default=None)
    parser.add_argument("--output", type=Path, default=Path("docs/provenance.json"))
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    patches = [path.resolve() for path in (args.patch or [Path("patches/goal-old-continuation.patch")])]
    if not source_root.is_dir() or not all(path.is_file() for path in patches):
        parser.error("source root and patch files must exist")

    with tempfile.TemporaryDirectory(prefix="codex-plus-provenance-") as temp:
        work = Path(temp) / "upstream"
        if args.upstream_root:
            upstream_root = args.upstream_root.resolve()
            run("git", "-C", str(upstream_root), "cat-file", "-e", f"{args.commit}^{{commit}}")
            run("git", "-C", str(upstream_root), "archive", args.commit, "-o", str(Path(temp) / "upstream.tar"))
            work.mkdir()
            run("tar", "-xf", str(Path(temp) / "upstream.tar"), "-C", str(work))
        else:
            run("git", "init", "--quiet", str(work))
            run("git", "-C", str(work), "remote", "add", "origin", args.upstream)
            run(
                "git",
                "-C",
                str(work),
                "fetch",
                "--quiet",
                "--filter=blob:none",
                "--no-tags",
                "origin",
                args.commit,
            )
            run("git", "-C", str(work), "checkout", "--quiet", "--detach", args.commit)
        for patch in patches:
            run("git", "apply", "--check", str(patch), cwd=work)
            run("git", "apply", str(patch), cwd=work)

        source_manifest = manifest(source_root)
        rebuilt_manifest = manifest(work)
        changed = {
            key: {"source": source_manifest.get(key), "rebuilt": rebuilt_manifest.get(key)}
            for key in sorted(set(source_manifest) | set(rebuilt_manifest))
            if source_manifest.get(key) != rebuilt_manifest.get(key)
        }
        changed_paths = set(changed)
        unexpected = sorted(changed_paths - EXPECTED_MATERIALIZATION_DIFFERENCES)
        missing = sorted(EXPECTED_MATERIALIZATION_DIFFERENCES - changed_paths)
        if unexpected or missing:
            details = []
            if unexpected:
                details.append(f"unexpected tree differences: {', '.join(unexpected)}")
            if missing:
                details.append(f"missing expected materialization differences: {', '.join(missing)}")
            raise SystemExit("provenance verification failed: " + "; ".join(details))
        result = {
            "upstream": args.upstream,
            "commit": args.commit,
            "patches": [display_path(path) for path in patches],
            "patch_sha256": [digest(path) for path in patches],
            "source_tree_sha256": digest_manifest(source_manifest),
            "rebuilt_tree_sha256": digest_manifest(rebuilt_manifest),
            "changed_files": changed,
            "expected_materialization_differences": sorted(EXPECTED_MATERIALIZATION_DIFFERENCES),
            "note": "Differences are reported explicitly; no vendored-only comparison is used.",
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"changed_files": len(changed), "output": str(args.output)}))
    return 0


def digest_manifest(values: dict[str, str]) -> str:
    h = hashlib.sha256()
    for key, value in values.items():
        h.update(key.encode())
        h.update(b"\0")
        h.update(value.encode())
        h.update(b"\n")
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
