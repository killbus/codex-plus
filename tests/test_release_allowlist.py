#!/usr/bin/env python3
"""Regression tests for the exact release-stage allowlist."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPOSITORY_ROOT / "scripts" / "check_release_allowlist.py"
REQUIRED = {
    "codex",
    "LICENSE",
    "NOTICE",
    "TRADEMARKS.md",
    "BUILD-INFO.txt",
    "SHA256SUMS",
}


class ReleaseAllowlistTest(unittest.TestCase):
    def run_checker(self, stage: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(stage), "--binary", "codex"],
            check=False,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def populate(stage: Path) -> None:
        for name in REQUIRED:
            (stage / name).write_text(f"{name}\n", encoding="utf-8")

    def test_accepts_exact_six_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            self.populate(stage)

            self.assertEqual(self.run_checker(stage).returncode, 0)

    def test_rejects_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            self.populate(stage)
            (stage / "NOTICE").unlink()

            result = self.run_checker(stage)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("NOTICE", result.stderr)

    def test_rejects_undeclared_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            self.populate(stage)
            (stage / "debug").mkdir()

            self.assertNotEqual(self.run_checker(stage).returncode, 0)

    def test_rejects_allowed_name_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            self.populate(stage)
            (stage / "NOTICE").unlink()
            try:
                (stage / "NOTICE").symlink_to("LICENSE")
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable: {error}")

            result = self.run_checker(stage)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("regular files", result.stderr)


if __name__ == "__main__":
    unittest.main()
