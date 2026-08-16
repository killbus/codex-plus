#!/usr/bin/env python3
"""Regression tests for the downloaded six-platform artifact audit."""

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "scripts" / "audit_release_artifacts.py"
DEFAULT_PROVENANCE = ROOT / "docs" / "provenance.json"
SYNTHETIC_COMMIT = "a" * 40
SYNTHETIC_SOURCE_TREE = "1" * 64
SYNTHETIC_REBUILT_TREE = "2" * 64
SYNTHETIC_CARGO_SOURCE = "3" * 64
SYNTHETIC_CARGO_REBUILT = "4" * 64
SYNTHETIC_PATCH_HASHES = ("5" * 64, "6" * 64)
PLATFORMS = {
    "windows-x64": ("codex.exe", "x86_64-pc-windows-msvc"),
    "windows-arm64": ("codex.exe", "aarch64-pc-windows-msvc"),
    "macos-x64": ("codex", "x86_64-apple-darwin"),
    "macos-arm64": ("codex", "aarch64-apple-darwin"),
    "linux-musl-x64": ("codex", "x86_64-unknown-linux-musl"),
    "linux-musl-arm64": ("codex", "aarch64-unknown-linux-musl"),
}


class ReleaseArtifactAuditTest(unittest.TestCase):
    @staticmethod
    def read_default_provenance() -> dict[str, object]:
        return json.loads(DEFAULT_PROVENANCE.read_text(encoding="utf-8"))

    @staticmethod
    def build_info_from_provenance(
        provenance: dict[str, object],
    ) -> dict[str, str]:
        changed_files = provenance["changed_files"]
        assert isinstance(changed_files, dict)
        cargo_lock = changed_files["codex-rs/Cargo.lock"]
        assert isinstance(cargo_lock, dict)
        patch_hashes = provenance["patch_sha256"]
        assert isinstance(patch_hashes, list)
        return {
            "source_commit": str(provenance["commit"]),
            "source_tree_sha256": str(provenance["source_tree_sha256"]),
            "rebuilt_tree_sha256": str(provenance["rebuilt_tree_sha256"]),
            "cargo_lock_sha256": str(cargo_lock["source"]),
            "patch_sha256": ",".join(str(value) for value in patch_hashes),
        }

    @staticmethod
    def synthetic_provenance() -> dict[str, object]:
        return {
            "commit": SYNTHETIC_COMMIT,
            "source_tree_sha256": SYNTHETIC_SOURCE_TREE,
            "rebuilt_tree_sha256": SYNTHETIC_REBUILT_TREE,
            "changed_files": {
                "codex-rs/Cargo.lock": {
                    "source": SYNTHETIC_CARGO_SOURCE,
                    "rebuilt": SYNTHETIC_CARGO_REBUILT,
                }
            },
            "patch_sha256": list(SYNTHETIC_PATCH_HASHES),
        }

    @staticmethod
    def synthetic_build_info() -> dict[str, str]:
        return {
            "source_commit": SYNTHETIC_COMMIT,
            "source_tree_sha256": SYNTHETIC_SOURCE_TREE,
            "rebuilt_tree_sha256": SYNTHETIC_REBUILT_TREE,
            "cargo_lock_sha256": SYNTHETIC_CARGO_SOURCE,
            "patch_sha256": ",".join(SYNTHETIC_PATCH_HASHES),
        }

    @staticmethod
    def make_info(target: str, fields: dict[str, str]) -> bytes:
        return (
            f"source_commit={fields['source_commit']}\n"
            "repository_commit=deadbeef\n"
            f"source_tree_sha256={fields['source_tree_sha256']}\n"
            f"rebuilt_tree_sha256={fields['rebuilt_tree_sha256']}\n"
            f"cargo_lock_sha256={fields['cargo_lock_sha256']}\n"
            f"patch_sha256={fields['patch_sha256']}\n"
            f"toolchain=1.95.0\ntarget={target}\nrunner=Linux/X64\n"
            "built_at_utc=2026-08-17T00:00:00Z\n"
        ).encode()

    @classmethod
    def write_platform(
        cls, root: Path, platform: str, build_info: dict[str, str]
    ) -> None:
        binary, target = PLATFORMS[platform]
        platform_root = root / f"codex-plus-{platform}"
        platform_root.mkdir()
        binary_data = f"binary-{platform}".encode()
        embedded_hash = sha256(binary_data).hexdigest()
        files = {
            binary: binary_data,
            "LICENSE": b"license\n",
            "NOTICE": b"notice\n",
            "TRADEMARKS.md": b"trademarks\n",
            "BUILD-INFO.txt": cls.make_info(target, build_info),
            "SHA256SUMS": f"{embedded_hash}  {binary}\n".encode(),
        }
        archive = platform_root / f"codex-plus-{platform}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        archive_hash = sha256(archive.read_bytes()).hexdigest()
        (platform_root / f"codex-plus-{platform}.zip.sha256").write_text(
            f"{archive_hash}  {archive.name}\n", encoding="utf-8"
        )

    @classmethod
    def write_all_platforms(cls, root: Path, build_info: dict[str, str]) -> None:
        for platform in PLATFORMS:
            cls.write_platform(root, platform, build_info)

    def run_auditor(
        self, root: Path, provenance: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(AUDITOR),
            str(root),
            "--repository-commit",
            "deadbeef",
        ]
        if provenance is not None:
            command.extend(("--provenance", str(provenance)))
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=root,
        )

    def test_accepts_all_six_exact_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_info = self.build_info_from_provenance(self.read_default_provenance())
            self.write_all_platforms(root, build_info)
            result = self.run_auditor(root)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_tampered_zip_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_info = self.build_info_from_provenance(self.read_default_provenance())
            self.write_all_platforms(root, build_info)
            checksum = root / "codex-plus-macos-x64" / "codex-plus-macos-x64.zip.sha256"
            checksum.write_text(
                "0" * 64 + "  codex-plus-macos-x64.zip\n", encoding="utf-8"
            )
            result = self.run_auditor(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checksum mismatch", result.stderr)

    def test_rejects_extra_zip_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_info = self.build_info_from_provenance(self.read_default_provenance())
            self.write_all_platforms(root, build_info)
            archive = (
                root / "codex-plus-linux-musl-x64" / "codex-plus-linux-musl-x64.zip"
            )
            with zipfile.ZipFile(archive, "a") as bundle:
                bundle.writestr("debug.log", b"unexpected")
            archive_hash = sha256(archive.read_bytes()).hexdigest()
            (archive.parent / f"{archive.name}.sha256").write_text(
                f"{archive_hash}  {archive.name}\n", encoding="utf-8"
            )
            result = self.run_auditor(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact allowlist", result.stderr)

    def test_changed_provenance_document_changes_build_info_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "audit"
            root.mkdir()
            provenance_path = base / "expected-provenance.json"
            provenance = self.synthetic_provenance()
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            self.write_all_platforms(root, self.synthetic_build_info())

            result = self.run_auditor(root, Path("../expected-provenance.json"))
            self.assertEqual(result.returncode, 0, result.stderr)

            current_hash = provenance["source_tree_sha256"]
            provenance["source_tree_sha256"] = (
                "1" * 64 if current_hash != "1" * 64 else "2" * 64
            )
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            result = self.run_auditor(root, provenance_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "linux-musl-arm64: unexpected source_tree_sha256", result.stderr
            )

    def test_uses_cargo_source_hash_and_preserves_patch_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "audit"
            root.mkdir()
            provenance_path = base / "expected-provenance.json"
            provenance = self.synthetic_provenance()
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            self.write_all_platforms(root, self.synthetic_build_info())

            result = self.run_auditor(root, provenance_path)
            self.assertEqual(result.returncode, 0, result.stderr)

            provenance["patch_sha256"] = list(reversed(SYNTHETIC_PATCH_HASHES))
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
            result = self.run_auditor(root, provenance_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected patch_sha256", result.stderr)

    def test_rejects_invalid_provenance_documents_without_traceback(self) -> None:
        invalid_documents = {
            "invalid provenance document": "{",
            "expected a JSON object": "[]",
            "commit must be a 40-digit hex value": json.dumps(
                {**self.synthetic_provenance(), "commit": "not-a-commit"}
            ),
            "cargo_lock_sha256 must be a SHA-256 value": json.dumps(
                {
                    **self.synthetic_provenance(),
                    "changed_files": {
                        "codex-rs/Cargo.lock": {
                            "source": None,
                            "rebuilt": SYNTHETIC_CARGO_REBUILT,
                        }
                    },
                }
            ),
            "patch_sha256 must be a non-empty SHA-256 list": json.dumps(
                {**self.synthetic_provenance(), "patch_sha256": []}
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance_path = root / "expected-provenance.json"
            for expected_error, document in invalid_documents.items():
                with self.subTest(expected_error=expected_error):
                    provenance_path.write_text(document, encoding="utf-8")
                    result = self.run_auditor(root, provenance_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_rejects_missing_provenance_document_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_auditor(root, root / "missing-provenance.json")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot read provenance document", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
