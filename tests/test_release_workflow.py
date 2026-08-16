#!/usr/bin/env python3
"""Static regression tests for the cross-platform release workflow."""

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "cli-release.yml"


class ReleaseWorkflowTest(unittest.TestCase):
    workflow: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def named_step(self, name: str) -> str:
        marker = f"      - name: {name}\n"
        self.assertIn(marker, self.workflow)
        return self.workflow.split(marker, 1)[1].split("\n      - ", 1)[0]

    def test_matrix_rows_pin_the_native_release_contract(self) -> None:
        expected_rows = (
            (
                "windows-x64",
                "windows-2022",
                "x86_64-pc-windows-msvc",
                "codex.exe",
                "dev",
            ),
            (
                "windows-arm64",
                "windows-11-arm",
                "aarch64-pc-windows-msvc",
                "codex.exe",
                "dev",
            ),
            (
                "macos-x64",
                "macos-15-intel",
                "x86_64-apple-darwin",
                "codex",
                "dev",
            ),
            (
                "macos-arm64",
                "macos-latest",
                "aarch64-apple-darwin",
                "codex",
                "dev",
            ),
            (
                "linux-musl-x64",
                "ubuntu-latest",
                "x86_64-unknown-linux-musl",
                "codex",
                "release",
            ),
            (
                "linux-musl-arm64",
                "ubuntu-24.04-arm",
                "aarch64-unknown-linux-musl",
                "codex",
                "release",
            ),
        )
        for platform, runner, rust_target, binary, check_profile in expected_rows:
            row = (
                f"- platform: {platform}\n"
                f"            runner: {runner}\n"
                f"            rust_target: {rust_target}\n"
                f"            binary: {binary}\n"
            )
            if platform.startswith("linux-musl-"):
                row += "            musl: true\n"
            row += f"            check_profile: {check_profile}"
            with self.subTest(platform=platform):
                self.assertIn(row, self.workflow)

        self.assertEqual(self.workflow.count("- platform:"), len(expected_rows))

    def test_musl_checks_use_profile_without_narrowing_package_tests(self) -> None:
        self.assertEqual(self.workflow.count('$profileArgs = @("--release")'), 3)
        self.assertIn(
            "cargo test --locked @profileArgs --target $env:RUST_TARGET -p codex-goal-extension",
            self.workflow,
        )
        self.assertIn(
            "cargo test --locked @profileArgs --target $env:RUST_TARGET -p codex-shadow-extension",
            self.workflow,
        )
        self.assertIn(
            "cargo check --locked @profileArgs --target $env:RUST_TARGET -p codex-app-server",
            self.workflow,
        )
        self.assertGreaterEqual(self.workflow.count("shell: pwsh"), 4)

    def test_cli_build_uses_symbol_free_distribution_overrides(self) -> None:
        build_step = self.named_step("Build and smoke-test CLI")
        self.assertIn('CARGO_PROFILE_RELEASE_DEBUG: "none"', build_step)
        self.assertIn('CARGO_PROFILE_RELEASE_STRIP: "symbols"', build_step)
        self.assertIn(
            "cargo build --locked --release --target $env:RUST_TARGET -p codex-cli --bin codex",
            build_step,
        )
        self.assertNotIn("\n        if:", build_step)
        self.assertEqual(self.workflow.count("CARGO_PROFILE_RELEASE_DEBUG:"), 1)
        self.assertEqual(self.workflow.count("CARGO_PROFILE_RELEASE_STRIP:"), 1)

        for check_step_name in (
            "Test Goal extension",
            "Test Shadow extension",
            "Check app-server integration",
        ):
            with self.subTest(step=check_step_name):
                check_step = self.named_step(check_step_name)
                self.assertNotIn("CARGO_PROFILE_RELEASE_DEBUG", check_step)
                self.assertNotIn("CARGO_PROFILE_RELEASE_STRIP", check_step)

    def test_provenance_failure_is_not_blindly_retried(self) -> None:
        self.assertNotIn("for attempt in 1 2 3", self.workflow)
        self.assertEqual(self.workflow.count("python scripts/verify_provenance.py --check"), 1)

    def test_musl_network_and_rusty_v8_inputs_follow_upstream_release_practice(self) -> None:
        rusty_v8_step = self.named_step("Configure Codex-built rusty_v8 artifacts (musl)")
        self.assertIn("Configure transient network retries (musl)", self.workflow)
        self.assertIn("retry-all-errors", self.workflow)
        self.assertIn("retry = 8", self.workflow)
        self.assertIn("python3 -B codex-src/.github/scripts/rusty_v8_bazel.py", self.workflow)
        self.assertIn("https://github.com/openai/codex/releases/download/rusty-v8-v${version}", self.workflow)
        self.assertIn(
            'artifact_dir="${RUNNER_TEMP}/rusty_v8/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"',
            rusty_v8_step,
        )
        self.assertEqual(rusty_v8_step.count("artifact_dir="), 1)
        self.assertNotIn('artifact_dir="${RUNNER_TEMP}/rusty_v8"', rusty_v8_step)
        self.assertIn("rusty_v8_release_${target}.sha256", self.workflow)
        self.assertIn("sha256sum -c", self.workflow)
        self.assertIn('echo "RUSTY_V8_ARCHIVE=${archive}"', self.workflow)
        self.assertNotIn('gzip -d "${archive}"', self.workflow)
        self.assertIn("RUSTY_V8_SRC_BINDING_PATH=", self.workflow)
        self.assertIn("workspaces: codex-src/codex-rs", self.workflow)


if __name__ == "__main__":
    unittest.main()
