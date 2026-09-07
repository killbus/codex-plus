#!/usr/bin/env python3
"""Cross-platform regression tests for the provenance manifest."""

import hashlib
import json
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
    def test_default_upstream_release_identity(self) -> None:
        self.assertEqual(VERIFY_PROVENANCE.UPSTREAM_TAG, "rust-v0.153.4")
        self.assertEqual(
            VERIFY_PROVENANCE.COMMIT,
            "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a",
        )

    def test_recorded_cargo_lock_hash_matches_integrated_source(self) -> None:
        provenance = json.loads(
            (REPOSITORY_ROOT / "docs" / "provenance.json").read_text(
                encoding="utf-8"
            )
        )
        cargo_lock = REPOSITORY_ROOT / "codex-src" / "codex-rs" / "Cargo.lock"

        self.assertEqual(
            provenance["source_file_sha256"],
            {"codex-rs/Cargo.lock": hashlib.sha256(cargo_lock.read_bytes()).hexdigest()},
        )

    def git(self, root: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True
        ).strip()

    def make_three_way_fixture(
        self, root: Path, *, conflicting_target: bool = False
    ) -> tuple[Path, Path, str]:
        repository = root / "upstream"
        repository.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
        self.git(repository, "config", "user.name", "Provenance Test")
        self.git(repository, "config", "user.email", "test@example.com")
        tracked = repository / "tracked.txt"
        tracked.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        self.git(repository, "add", "tracked.txt")
        self.git(repository, "commit", "--quiet", "-m", "base")
        preimage_commit = self.git(repository, "rev-parse", "HEAD")

        tracked.write_text("patched-alpha\nbeta\ngamma\n", encoding="utf-8")
        patch = root / "change.patch"
        patch.write_text(
            self.git(repository, "diff", "--binary", "--full-index") + "\n",
            encoding="utf-8",
        )
        self.git(repository, "restore", "tracked.txt")
        target_first_line = "target-alpha" if conflicting_target else "alpha"
        tracked.write_text(
            f"{target_first_line}\nbeta\ntarget-gamma\n", encoding="utf-8"
        )
        self.git(repository, "add", "tracked.txt")
        self.git(repository, "commit", "--quiet", "-m", "target")
        return repository, patch, preimage_commit

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

    def test_resolved_regular_file_matches_normalized_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native"
            materialized = root / "materialized"
            for checkout in (native, materialized):
                checkout.mkdir()
                (checkout / "COPYING").write_text(
                    "license body\n", encoding="utf-8"
                )
            try:
                (native / "LICENSE").symlink_to("COPYING")
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlinks unavailable: {error}")
            (materialized / "LICENSE").write_text(
                "license body\n", encoding="utf-8"
            )

            self.assertEqual(
                VERIFY_PROVENANCE.manifest(native, {"LICENSE": "COPYING"}),
                VERIFY_PROVENANCE.manifest(materialized),
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

    def test_goal_patch_uses_recorded_three_way_preimage(self) -> None:
        goal_patch = REPOSITORY_ROOT / "patches" / "goal-old-continuation.patch"

        self.assertEqual(
            VERIFY_PROVENANCE.patch_application(goal_patch),
            {
                "mode": "three-way",
                "preimage_commit": "bb6a127bca6c9e190cc9285c4d7bd22c1dff5acb",
            },
        )
        self.assertEqual(
            VERIFY_PROVENANCE.patch_preimages(goal_patch),
            [
                ("codex-rs/ext/goal/src/extension.rs", "4fa1081db"),
                (
                    "codex-rs/ext/goal/tests/goal_extension_backend.rs",
                    "206216058",
                ),
            ],
        )

    def test_three_way_apply_succeeds_when_direct_apply_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, patch, preimage_commit = self.make_three_way_fixture(root)

            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.check_output(
                    ["git", "-C", str(repository), "apply", "--check", str(patch)],
                    stderr=subprocess.DEVNULL,
                )

            VERIFY_PROVENANCE.apply_patch(
                repository,
                patch,
                {"mode": "three-way", "preimage_commit": preimage_commit},
                fetch_preimages=False,
            )

            self.assertEqual(
                (repository / "tracked.txt").read_text(encoding="utf-8"),
                "patched-alpha\nbeta\ntarget-gamma\n",
            )
            self.assertEqual(self.git(repository, "ls-files", "--unmerged"), "")

    def test_three_way_apply_fails_without_preimage_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, patch, preimage_commit = self.make_three_way_fixture(root)
            isolated = root / "isolated"
            subprocess.run(["git", "init", "--quiet", str(isolated)], check=True)
            (isolated / "tracked.txt").write_text(
                "alpha\nbeta\ntarget-gamma\n", encoding="utf-8"
            )
            self.git(isolated, "add", "tracked.txt")

            with self.assertRaises(subprocess.CalledProcessError):
                VERIFY_PROVENANCE.apply_patch(
                    isolated,
                    patch,
                    {"mode": "three-way", "preimage_commit": preimage_commit},
                    fetch_preimages=False,
                )

            self.assertTrue((repository / "tracked.txt").is_file())

    def test_three_way_apply_fails_on_unresolved_merge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, patch, preimage_commit = self.make_three_way_fixture(
                root, conflicting_target=True
            )

            with self.assertRaises(subprocess.CalledProcessError):
                VERIFY_PROVENANCE.apply_patch(
                    repository,
                    patch,
                    {"mode": "three-way", "preimage_commit": preimage_commit},
                    fetch_preimages=False,
                )

    def test_local_upstream_checkout_preserves_three_way_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, patch, preimage_commit = self.make_three_way_fixture(root)
            target_commit = self.git(repository, "rev-parse", "HEAD")
            checkout = root / "checkout"

            VERIFY_PROVENANCE.checkout_local_upstream(
                checkout, repository, target_commit
            )
            VERIFY_PROVENANCE.apply_patch(
                checkout,
                patch,
                {"mode": "three-way", "preimage_commit": preimage_commit},
                fetch_preimages=False,
            )

            self.assertEqual(
                (checkout / "tracked.txt").read_text(encoding="utf-8"),
                "patched-alpha\nbeta\ntarget-gamma\n",
            )

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

    def test_ci_tests_integrated_goal_continuation_policy(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        step = workflow.split("- name: Test integrated Goal continuation policy", 1)[1]
        step = step.split("- name: Check Shadow extension", 1)[0]

        self.assertIn("working-directory: codex-src/codex-rs", step)
        self.assertIn(
            "cargo test --locked -p codex-goal-extension turn_error_",
            step,
        )
        self.assertNotIn("goal_only", step)
        self.assertNotIn("apply_patch", step)

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
        self.assertNotIn("ActiveGoalStopReason::TurnError", extension_text)
        self.assertIn("ActiveGoalStopReason::ExecutionUnavailable", extension_text)
        self.assertIn(
            "if input.error != CodexErrorInfo::UsageLimitExceeded {",
            extension_text,
        )
        self.assertIn("-    TurnError,", shadow_patch_text)
        self.assertIn("-            ActiveGoalStopReason::TurnError => {", shadow_patch_text)


if __name__ == "__main__":
    unittest.main()
