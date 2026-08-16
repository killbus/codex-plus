#!/usr/bin/env python3
"""Cross-platform regression tests for the provenance manifest."""

import hashlib
import os
import subprocess
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "verify_provenance", REPOSITORY_ROOT / "scripts" / "verify_provenance.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load provenance verifier")
VERIFY_PROVENANCE = module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_PROVENANCE)


class VerifyProvenanceTest(unittest.TestCase):
    def test_windows_placeholder_hashes_resolved_target_but_source_stays_flattened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flattened = root / "flattened"
            source = root / "source"
            for checkout in (flattened, source):
                checkout.mkdir()
                (checkout / "COPYING").write_text("license body\n", encoding="utf-8")
            (flattened / "LICENSE").write_text("COPYING", encoding="utf-8")
            (source / "LICENSE").write_text("COPYING", encoding="utf-8")
            targets = {"LICENSE": "COPYING"}

            flattened_manifest = VERIFY_PROVENANCE.manifest(flattened, targets)
            source_manifest = VERIFY_PROVENANCE.manifest(source)

            self.assertNotEqual(
                source_manifest["LICENSE"], flattened_manifest["LICENSE"]
            )

    def test_native_symlink_and_windows_placeholder_share_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native"
            flattened = root / "flattened"
            for checkout in (native, flattened):
                checkout.mkdir()
                (checkout / "COPYING").write_text("license body\n", encoding="utf-8")
            try:
                (native / "LICENSE").symlink_to("COPYING")
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            (flattened / "LICENSE").write_text("COPYING", encoding="utf-8")
            targets = {"LICENSE": "COPYING"}

            self.assertEqual(
                VERIFY_PROVENANCE.manifest(native, targets),
                VERIFY_PROVENANCE.manifest(flattened, targets),
            )

    def test_symlink_contract_comes_from_git_tree_not_worktree_mode(self) -> None:
        if os.name == "nt":
            self.skipTest("creating an indexed symlink is not portable on Windows")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / "COPYING").write_text("license body\n", encoding="utf-8")
            (root / "LICENSE").symlink_to("COPYING")
            subprocess.run(["git", "-C", str(root), "add", "COPYING", "LICENSE"], check=True)
            tree = subprocess.check_output(
                ["git", "-C", str(root), "write-tree"], text=True
            ).strip()

            self.assertEqual(
                VERIFY_PROVENANCE.git_symlink_targets(root, tree),
                {"LICENSE": "COPYING"},
            )

    def test_upstream_checkout_disables_autocrlf_before_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "upstream"
            with mock.patch.object(VERIFY_PROVENANCE, "run") as run:
                VERIFY_PROVENANCE.checkout_upstream(work, "origin", "commit")

            calls = [call.args for call in run.call_args_list]
            config = ("git", "-C", str(work), "config", "core.autocrlf", "false")
            checkout = (
                "git",
                "-C",
                str(work),
                "checkout",
                "--quiet",
                "--detach",
                "commit",
            )
            self.assertLess(calls.index(config), calls.index(checkout))

    def test_upstream_fetch_retries_only_network_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            failure = subprocess.CalledProcessError(1, ["git", "fetch"])
            with mock.patch.object(
                VERIFY_PROVENANCE, "run", side_effect=(failure, "")
            ) as run, mock.patch.object(VERIFY_PROVENANCE.time, "sleep") as sleep:
                VERIFY_PROVENANCE.fetch_upstream_commit(work, "commit")

            self.assertEqual(run.call_count, 2)
            sleep.assert_called_once_with(10)

    def test_manifest_digest_is_independent_of_host_path_order(self) -> None:
        case_sensitive_order = {
            "codex-rs/Alpha/file": "first",
            "codex-rs/alpha/file": "second",
            "codex-rs/Beta/file": "third",
        }
        windows_style_order = dict(reversed(case_sensitive_order.items()))

        self.assertEqual(
            VERIFY_PROVENANCE.digest_manifest(case_sensitive_order),
            VERIFY_PROVENANCE.digest_manifest(windows_style_order),
        )

    def test_stale_output_names_only_differing_top_level_fields(self) -> None:
        recorded = '{"commit": "same", "source_tree_sha256": "old"}'
        result = {
            "commit": "same",
            "source_tree_sha256": "new",
            "rebuilt_tree_sha256": "new",
        }

        self.assertEqual(
            VERIFY_PROVENANCE.stale_output_detail(recorded, result),
            "differing fields: rebuilt_tree_sha256, source_tree_sha256",
        )

    def test_repository_checkout_pins_provenance_inputs_to_lf(self) -> None:
        attributes = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("/codex-src/** text=auto eol=lf", attributes)
        self.assertIn("/patches/** text eol=lf", attributes)
        self.assertIn("/docs/provenance.json text eol=lf", attributes)

    def test_integrated_goal_runtime_drops_unreachable_turn_error_stop_reason(self) -> None:
        goal_patch = REPOSITORY_ROOT / "patches" / "goal-old-continuation.patch"
        shadow_patch = REPOSITORY_ROOT / "patches" / "shadow-mind.patch"
        runtime = (
            REPOSITORY_ROOT / "codex-src" / "codex-rs" / "ext" / "goal" / "src" / "runtime.rs"
        )
        extension = (
            REPOSITORY_ROOT
            / "codex-src"
            / "codex-rs"
            / "ext"
            / "goal"
            / "src"
            / "extension.rs"
        )

        self.assertEqual(
            hashlib.sha256(goal_patch.read_bytes()).hexdigest(),
            "eed4c30a1bf83099c2bdd764d83ae3c6719524ba7101867b29c8ccf870559ec6",
        )
        runtime_text = runtime.read_text(encoding="utf-8")
        extension_text = extension.read_text(encoding="utf-8")
        shadow_patch_text = shadow_patch.read_text(encoding="utf-8")
        self.assertNotIn("TurnError,", runtime_text)
        self.assertNotIn("ActiveGoalStopReason::TurnError", runtime_text)
        self.assertNotIn("ActiveGoalStopReason", extension_text)
        self.assertIn(
            "if input.error != CodexErrorInfo::UsageLimitExceeded {",
            extension_text,
        )
        self.assertIn("-    TurnError,", shadow_patch_text)
        self.assertIn("-            ActiveGoalStopReason::TurnError => {", shadow_patch_text)


if __name__ == "__main__":
    unittest.main()
