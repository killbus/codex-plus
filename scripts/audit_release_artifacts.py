#!/usr/bin/env python3
"""Audit downloaded CLI release artifacts and their recorded checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

DEFAULT_PROVENANCE = Path(__file__).resolve().parents[1] / "docs" / "provenance.json"
TOOLCHAIN = "1.95.0"
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
HEX_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
PLATFORMS = {
    "windows-x64": ("codex.exe", "x86_64-pc-windows-msvc"),
    "windows-arm64": ("codex.exe", "aarch64-pc-windows-msvc"),
    "macos-x64": ("codex", "x86_64-apple-darwin"),
    "macos-arm64": ("codex", "aarch64-apple-darwin"),
    "linux-musl-x64": ("codex", "x86_64-unknown-linux-musl"),
    "linux-musl-arm64": ("codex", "aarch64-unknown-linux-musl"),
}


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"artifact audit failed: {message}")


def load_expected_provenance(path: Path) -> dict[str, str]:
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"cannot read provenance document {path}: {exc}")
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid provenance document {path}: {exc}")

    if not isinstance(provenance, dict):
        fail(f"invalid provenance document {path}: expected a JSON object")

    commit = provenance.get("commit")
    source_tree = provenance.get("source_tree_sha256")
    rebuilt_tree = provenance.get("rebuilt_tree_sha256")
    patch_hashes = provenance.get("patch_sha256")
    changed_files = provenance.get("changed_files")
    cargo_lock = (
        changed_files.get("codex-rs/Cargo.lock", {}).get("source")
        if isinstance(changed_files, dict)
        and isinstance(changed_files.get("codex-rs/Cargo.lock"), dict)
        else None
    )

    if not isinstance(commit, str) or not HEX_COMMIT.fullmatch(commit):
        fail(f"invalid provenance document {path}: commit must be a 40-digit hex value")
    raw_hashes = {
        "source_tree_sha256": source_tree,
        "rebuilt_tree_sha256": rebuilt_tree,
        "cargo_lock_sha256": cargo_lock,
    }
    hashes: dict[str, str] = {}
    for field, value in raw_hashes.items():
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            fail(f"invalid provenance document {path}: {field} must be a SHA-256 value")
        hashes[field] = value.lower()
    if (
        not isinstance(patch_hashes, list)
        or not patch_hashes
        or any(
            not isinstance(value, str) or not HEX64.fullmatch(value)
            for value in patch_hashes
        )
    ):
        fail(
            f"invalid provenance document {path}: "
            "patch_sha256 must be a non-empty SHA-256 list"
        )

    return {
        "source_commit": commit.lower(),
        **hashes,
        "patch_sha256": ",".join(value.lower() for value in patch_hashes),
    }


def parse_external_checksum(path: Path, archive_name: str) -> str:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) != 1:
        fail(f"{path}: expected one checksum line")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != archive_name or not HEX64.fullmatch(fields[0]):
        fail(f"{path}: malformed checksum record")
    return fields[0].lower()


def parse_build_info(
    data: bytes,
    platform: str,
    target: str,
    repository_commit: str | None,
    expected_provenance: dict[str, str],
) -> None:
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        fail(f"{platform}: BUILD-INFO.txt is not UTF-8: {exc}")
    fields: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            fail(f"{platform}: malformed BUILD-INFO.txt line")
        key, value = line.split("=", 1)
        if not key or key in fields:
            fail(f"{platform}: duplicate or empty BUILD-INFO key")
        fields[key] = value

    required = {
        "source_commit",
        "repository_commit",
        "source_tree_sha256",
        "rebuilt_tree_sha256",
        "cargo_lock_sha256",
        "patch_sha256",
        "toolchain",
        "target",
        "runner",
        "built_at_utc",
    }
    missing = sorted(required - fields.keys())
    if missing:
        fail(f"{platform}: BUILD-INFO.txt missing {', '.join(missing)}")
    if fields["source_commit"].lower() != expected_provenance["source_commit"]:
        fail(f"{platform}: unexpected source commit")
    if (
        repository_commit is not None
        and fields["repository_commit"] != repository_commit
    ):
        fail(f"{platform}: repository commit mismatch")
    if fields["toolchain"] != TOOLCHAIN or fields["target"] != target:
        fail(f"{platform}: toolchain/target mismatch")
    expected_hashes = {
        key: expected_provenance[key]
        for key in (
            "source_tree_sha256",
            "rebuilt_tree_sha256",
            "cargo_lock_sha256",
            "patch_sha256",
        )
    }
    for key, expected in expected_hashes.items():
        if fields[key].lower() != expected:
            fail(f"{platform}: unexpected {key}")
    if (
        not fields["repository_commit"]
        or not fields["runner"]
        or not fields["built_at_utc"]
    ):
        fail(f"{platform}: empty repository/runner/timestamp field")


def audit_archive(
    platform: str,
    archive: Path,
    checksum: Path,
    repository_commit: str | None,
    expected_provenance: dict[str, str],
) -> None:
    binary, target = PLATFORMS[platform]
    expected_archive = f"codex-plus-{platform}.zip"
    if (
        archive.name != expected_archive
        or checksum.name != f"{expected_archive}.sha256"
    ):
        fail(f"{platform}: unexpected artifact names")
    recorded_archive_hash = parse_external_checksum(checksum, archive.name)
    actual_archive_hash = digest_file(archive)
    if recorded_archive_hash != actual_archive_hash:
        fail(f"{platform}: ZIP checksum mismatch")

    expected_names = {
        binary,
        "LICENSE",
        "NOTICE",
        "TRADEMARKS.md",
        "BUILD-INFO.txt",
        "SHA256SUMS",
    }
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                fail(f"{platform}: duplicate ZIP paths")
            if set(names) != expected_names:
                fail(f"{platform}: ZIP paths are not the exact allowlist")
            if any(
                info.is_dir()
                or "/" in info.filename
                or "\\" in info.filename
                or info.filename in {".", ".."}
                for info in infos
            ):
                fail(f"{platform}: ZIP contains a directory or nested path")
            contents = {info.filename: bundle.read(info) for info in infos}
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"{platform}: unreadable ZIP: {exc}")

    binary_hash = digest_bytes(contents[binary])
    checksum_lines = contents["SHA256SUMS"].decode("utf-8-sig").splitlines()
    if len(checksum_lines) != 1:
        fail(f"{platform}: malformed SHA256SUMS")
    fields = checksum_lines[0].split()
    if len(fields) != 2 or fields[1] != binary or fields[0].lower() != binary_hash:
        fail(f"{platform}: embedded binary checksum mismatch")
    parse_build_info(
        contents["BUILD-INFO.txt"],
        platform,
        target,
        repository_commit,
        expected_provenance,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root", type=Path, help="directory produced by download-artifact"
    )
    parser.add_argument(
        "--repository-commit", help="expected workflow commit in BUILD-INFO"
    )
    parser.add_argument(
        "--provenance",
        type=Path,
        default=DEFAULT_PROVENANCE,
        help="expected provenance JSON (default: repository docs/provenance.json)",
    )
    args = parser.parse_args()
    root = args.root
    if root.is_symlink() or not root.is_dir():
        parser.error("artifact root must be a directory")
    expected_provenance = load_expected_provenance(args.provenance)

    entries = {entry.name: entry for entry in root.iterdir()}
    artifact_dirs = {f"codex-plus-{platform}": platform for platform in PLATFORMS}
    if set(entries) != set(artifact_dirs) or any(
        not entry.is_dir() or entry.is_symlink() for entry in entries.values()
    ):
        fail("downloaded artifact directories do not match the six target platforms")
    for artifact_dir, platform in sorted(artifact_dirs.items()):
        files = {entry.name: entry for entry in entries[artifact_dir].iterdir()}
        archive_name = f"codex-plus-{platform}.zip"
        expected_files = {archive_name, f"{archive_name}.sha256"}
        if set(files) != expected_files or any(
            not entry.is_file() or entry.is_symlink() for entry in files.values()
        ):
            fail(
                f"{platform}: artifact directory does not contain exactly ZIP and checksum"
            )
        audit_archive(
            platform,
            files[archive_name],
            files[f"{archive_name}.sha256"],
            args.repository_commit,
            expected_provenance,
        )
    print(f"artifact audit ok: {len(PLATFORMS)} platform archives")
    return 0


if __name__ == "__main__":
    sys.exit(main())
