#!/usr/bin/env python3
"""Verify an upstream commit, ordered patch chain, and source-tree manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

UPSTREAM = "https://github.com/openai/codex.git"
UPSTREAM_TAG = "rust-v0.153.4"
COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
GOAL_PATCH_SHA256 = "eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6"
GOAL_PATCH_PREIMAGE_COMMIT = "bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb"
EXPECTED_MATERIALIZATION_DIFFERENCES = frozenset(
    {
        ".vscode/extensions.json",
        ".vscode/launch.json",
        ".vscode/settings.json",
    }
)
EXPECTED_SYMLINK_MATERIALIZATIONS = {
    "codex-rs/vendor/bubblewrap/LICENSE": "COPYING",
}
SOURCE_FILE_HASH_PATHS = ("codex-rs/Cargo.lock",)


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


def checkout_local_upstream(work: Path, upstream_root: Path, commit: str) -> None:
    """Create a Git-backed checkout so three-way patching matches remote CI."""
    run("git", "-C", str(upstream_root), "cat-file", "-e", f"{commit}^{{commit}}")
    run(
        "git",
        "clone",
        "--quiet",
        "--shared",
        "--no-checkout",
        str(upstream_root),
        str(work),
    )
    run("git", "-C", str(work), "config", "core.autocrlf", "false")
    run("git", "-C", str(work), "checkout", "--quiet", "--detach", commit)


def patch_application(patch: Path) -> dict[str, str]:
    if digest(patch) == GOAL_PATCH_SHA256:
        return {
            "mode": "three-way",
            "preimage_commit": GOAL_PATCH_PREIMAGE_COMMIT,
        }
    return {"mode": "direct"}


def patch_preimages(patch: Path) -> list[tuple[str, str]]:
    """Return (path, abbreviated old blob id) pairs recorded by a Git patch."""
    old_blob: str | None = None
    result: list[tuple[str, str]] = []
    for line in patch.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"index ([0-9a-f]+)\.\.[0-9a-f]+(?: [0-7]+)?", line)
        if match:
            old_blob = match.group(1)
            continue
        if old_blob is None or not line.startswith("--- "):
            continue
        old_path = line.removeprefix("--- ").split("\t", 1)[0]
        if old_path != "/dev/null":
            if not old_path.startswith("a/"):
                raise SystemExit(
                    f"provenance verification failed: unsupported patch preimage path: {old_path}"
                )
            result.append((old_path.removeprefix("a/"), old_blob))
        old_blob = None
    return result


def prepare_three_way_preimages(
    work: Path,
    patch: Path,
    preimage_commit: str,
    *,
    fetch_missing: bool,
) -> None:
    """Verify and materialize the exact old blobs required by --3way."""
    if fetch_missing:
        fetch_upstream_commit(work, preimage_commit)
    else:
        run("git", "-C", str(work), "cat-file", "-e", f"{preimage_commit}^{{commit}}")

    for path, abbreviated_blob in patch_preimages(patch):
        full_blob = run(
            "git",
            "-C",
            str(work),
            "rev-parse",
            f"{preimage_commit}:{path}",
        )
        if not full_blob.startswith(abbreviated_blob):
            raise SystemExit(
                "provenance verification failed: patch preimage does not match "
                f"{preimage_commit}:{path}"
            )
        if fetch_missing:
            fetch_upstream_commit(work, full_blob)
        run("git", "-C", str(work), "cat-file", "-e", f"{full_blob}^{{blob}}")


def apply_patch(
    work: Path,
    patch: Path,
    application: dict[str, str],
    *,
    fetch_preimages: bool,
) -> None:
    mode = application["mode"]
    if mode == "direct":
        run("git", "apply", "--check", str(patch), cwd=work)
        run("git", "apply", str(patch), cwd=work)
        return
    if mode != "three-way":
        raise SystemExit(f"provenance verification failed: unknown patch mode: {mode}")

    preimage_commit = application["preimage_commit"]
    prepare_three_way_preimages(
        work,
        patch,
        preimage_commit,
        fetch_missing=fetch_preimages,
    )
    run("git", "apply", "--3way", "--check", str(patch), cwd=work)
    run("git", "apply", "--3way", str(patch), cwd=work)
    if unmerged := run("git", "ls-files", "--unmerged", cwd=work):
        raise SystemExit(
            "provenance verification failed: three-way patch left unresolved entries: "
            + unmerged
        )


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
    parser.add_argument("--tag", default=UPSTREAM_TAG)
    parser.add_argument("--commit", default=COMMIT)
    parser.add_argument("--patch", type=Path, action="append", default=None)
    parser.add_argument("--output", type=Path, default=Path("docs/provenance.json"))
    parser.add_argument("--check", action="store_true", help="fail if the recorded output is stale")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    patches = [path.resolve() for path in (args.patch or [Path("patches/goal-old-continuation.patch")])]
    if not source_root.is_dir() or not all(path.is_file() for path in patches):
        parser.error("source root and patch files must exist")
    applications = [patch_application(patch) for patch in patches]

    with tempfile.TemporaryDirectory(prefix="codex-plus-provenance-") as temp:
        work = Path(temp) / "upstream"
        if args.upstream_root:
            upstream_root = args.upstream_root.resolve()
            checkout_local_upstream(work, upstream_root, args.commit)
            symlink_targets = git_symlink_targets(upstream_root, args.commit)
        else:
            checkout_upstream(work, args.upstream, args.commit)
            symlink_targets = git_symlink_targets(work)
        for patch, application in zip(patches, applications, strict=True):
            apply_patch(
                work,
                patch,
                application,
                fetch_preimages=args.upstream_root is None,
            )

        if symlink_targets != EXPECTED_SYMLINK_MATERIALIZATIONS:
            raise SystemExit(
                "provenance verification failed: upstream symlink contract changed: "
                + json.dumps(symlink_targets, sort_keys=True)
            )
        # The copied source materializes known upstream symlinks as regular
        # files containing their resolved target bytes. Normalize only the
        # rebuilt Git tree so native and placeholder checkout modes compare to
        # that portable materialization consistently.
        source_manifest = manifest(source_root)
        rebuilt_manifest = manifest(work, symlink_targets)
        missing_source_files = [
            path for path in SOURCE_FILE_HASH_PATHS if path not in source_manifest
        ]
        if missing_source_files:
            raise SystemExit(
                "provenance verification failed: missing required source files: "
                + ", ".join(missing_source_files)
            )
        source_file_sha256 = {
            path: source_manifest[path] for path in SOURCE_FILE_HASH_PATHS
        }
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
            "tag": args.tag,
            "commit": args.commit,
            "patches": [display_path(path) for path in patches],
            "patch_sha256": [digest(path) for path in patches],
            "patch_application": [
                {"patch": display_path(patch), **application}
                for patch, application in zip(patches, applications, strict=True)
            ],
            "source_tree_sha256": digest_manifest(source_manifest),
            "rebuilt_tree_sha256": digest_manifest(rebuilt_manifest),
            "source_file_sha256": source_file_sha256,
            "changed_files": changed,
            "expected_materialization_differences": sorted(EXPECTED_MATERIALIZATION_DIFFERENCES),
            "normalized_git_symlinks": dict(sorted(symlink_targets.items())),
            "note": (
                "Content differences are reported explicitly; rebuilt Git symlinks are hashed "
                "through their targets across checkout modes, while copied source symlinks are "
                "portable regular files containing the resolved target bytes."
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
