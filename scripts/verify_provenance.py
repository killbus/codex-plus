#!/usr/bin/env python3
"""Verify an upstream commit, ordered patch chain, and source-tree manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
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
EXPECTED_SYMLINK_MATERIALIZATIONS = {
    "codex-rs/vendor/bubblewrap/LICENSE": "COPYING",
}


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


def git_symlink_targets(root: Path, treeish: str = "HEAD") -> dict[str, str]:
    """Return symlink paths and targets from a Git tree, independent of checkout mode."""
    output = subprocess.check_output(
        ("git", "-C", str(root), "ls-tree", "-r", "-z", treeish)
    )
    result: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, _kind, object_id = metadata.split(b" ", 2)
        if mode != b"120000":
            continue
        target = subprocess.check_output(
            ("git", "-C", str(root), "cat-file", "blob", object_id)
        )
        result[path_bytes.decode("utf-8")] = target.decode("utf-8")
    return result


def manifest(root: Path, symlink_targets: dict[str, str] | None = None) -> dict[str, str]:
    symlink_targets = symlink_targets or {}
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or "target" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        symlink_target = symlink_targets.get(rel)
        if symlink_target is not None:
            # Windows checks out Git symlinks as regular files containing the
            # link target. Hash the resolved target on every OS so the manifest
            # describes the same content regardless of checkout capability.
            resolved = (path.parent / symlink_target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError as error:
                raise SystemExit(f"symlink target escapes source root: {rel}") from error
            if not resolved.is_file():
                raise SystemExit(f"symlink target is not a file: {rel} -> {symlink_target}")
            result[rel] = digest(resolved)
        elif path.is_file() and not path.is_symlink():
            result[rel] = digest(path)
    return result


def checkout_upstream(work: Path, upstream: str, commit: str) -> None:
    run("git", "init", "--quiet", str(work))
    # The rebuilt tree is a byte-level provenance input. Do not inherit the
    # Windows runner's checkout conversion policy.
    run("git", "-C", str(work), "config", "core.autocrlf", "false")
    run("git", "-C", str(work), "remote", "add", "origin", upstream)
    fetch_upstream_commit(work, commit)
    run("git", "-C", str(work), "checkout", "--quiet", "--detach", commit)


def stale_output_detail(recorded: str, result: dict[str, object]) -> str:
    try:
        recorded_result = json.loads(recorded)
    except json.JSONDecodeError:
        return "recorded output is not valid JSON"
    differing_fields = sorted(
        key
        for key in set(recorded_result) | set(result)
        if recorded_result.get(key) != result.get(key)
    )
    return "differing fields: " + ", ".join(differing_fields)


def fetch_upstream_commit(work: Path, commit: str, attempts: int = 3) -> None:
    """Retry only the network fetch, never deterministic manifest failures."""
    for attempt in range(1, attempts + 1):
        try:
            run(
                "git",
                "-C",
                str(work),
                "fetch",
                "--quiet",
                "--filter=blob:none",
                "--no-tags",
                "origin",
                commit,
            )
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            time.sleep(attempt * 10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path("codex-src"))
    parser.add_argument("--upstream-root", type=Path)
    parser.add_argument("--upstream", default=UPSTREAM)
    parser.add_argument("--commit", default=COMMIT)
    parser.add_argument("--patch", type=Path, action="append", default=None)
    parser.add_argument("--output", type=Path, default=Path("docs/provenance.json"))
    parser.add_argument("--check", action="store_true", help="fail if the recorded output is stale")
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
            symlink_targets = git_symlink_targets(upstream_root, args.commit)
            run("git", "-C", str(upstream_root), "archive", args.commit, "-o", str(Path(temp) / "upstream.tar"))
            work.mkdir()
            run("tar", "-xf", str(Path(temp) / "upstream.tar"), "-C", str(work))
        else:
            checkout_upstream(work, args.upstream, args.commit)
            symlink_targets = git_symlink_targets(work)
        for patch in patches:
            run("git", "apply", "--check", str(patch), cwd=work)
            run("git", "apply", str(patch), cwd=work)

        if symlink_targets != EXPECTED_SYMLINK_MATERIALIZATIONS:
            raise SystemExit(
                "provenance verification failed: upstream symlink contract changed: "
                + json.dumps(symlink_targets, sort_keys=True)
            )
        # The copied source intentionally preserves its flattened Windows
        # materialization. Only the rebuilt Git tree is normalized so that its
        # native/placeholder checkout modes produce one stable comparison.
        source_manifest = manifest(source_root)
        rebuilt_manifest = manifest(work, symlink_targets)
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
            "normalized_git_symlinks": dict(sorted(symlink_targets.items())),
            "note": (
                "Content differences are reported explicitly; rebuilt Git symlinks are hashed "
                "through their targets across checkout modes, while copied source bytes remain "
                "literal materialization evidence."
            ),
        }

    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file():
            raise SystemExit(f"provenance output is missing: {args.output}")
        recorded = args.output.read_text(encoding="utf-8")
        if recorded != serialized:
            detail = stale_output_detail(recorded, result)
            raise SystemExit(f"provenance output is stale: {args.output} ({detail})")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({"changed_files": len(changed), "output": str(args.output)}))
    return 0


def digest_manifest(values: dict[str, str]) -> str:
    h = hashlib.sha256()
    # pathlib orders Windows paths case-insensitively, while POSIX path order is
    # case-sensitive. Sort the normalized manifest keys here so the tree digest
    # never inherits the host's Path flavour or directory iteration order.
    for key, value in sorted(values.items()):
        h.update(key.encode())
        h.update(b"\0")
        h.update(value.encode())
        h.update(b"\n")
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
