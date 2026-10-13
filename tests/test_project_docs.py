from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "project-docs"


def load_checker_module():
    """Import bin/project-docs as a module so pure helpers can be unit tested."""
    loader = importlib.machinery.SourceFileLoader("project_docs_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("project_docs_under_test", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load project-docs for testing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def command(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
    )


def git(root: Path, *args: str) -> None:
    command(["git", *args], cwd=root)


def initialize_repo(root: Path, *, github: bool = True) -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Project Docs Tests")
    git(root, "config", "user.email", "project-docs@example.invalid")
    if github:
        git(root, "remote", "add", "origin", "git@github.com:example/project.git")


def commit_all(root: Path, message: str = "fixture") -> None:
    git(root, "add", ".")
    git(root, "commit", "-m", message)


def valid_root_map(name: str = "Fixture") -> str:
    lines = [
        f"# {name} - Project Knowledge Map",
        "",
        "> Shared project facts.",
        "",
        "## Reading Order",
        "",
        "1. Read this file.",
        "2. Read the nearest module map.",
        "",
        "## Project Boundary",
        "",
        "- Test fixture.",
        "",
        "## Validation",
        "",
        "- Run declared tests.",
        "",
        "## Knowledge Map",
        "",
        "- Add only proven facts.",
        "",
    ]
    return "\n".join(lines)


def prepare_valid_docs(root: Path) -> None:
    (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (root / "GEMINI.md").write_text("@./AGENTS.md\n", encoding="utf-8")
    (root / ".gitignore").write_text(".agents/local/\n", encoding="utf-8")


class ProjectDocsTests(unittest.TestCase):
    def run_cli(
        self,
        root: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return command(
            [str(SCRIPT), *args, "--repo", str(root)],
            cwd=root,
            check=check,
        )

    def test_bootstrap_generates_evidence_based_docs_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project docs ") as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"test": "vitest", "build": "vite build"},
                        "dependencies": {"react": "19.0.0"},
                        "devDependencies": {"vite": "7.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src" / "main.tsx").write_text("export {};\n", encoding="utf-8")
            commit_all(root)
            git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            git(root, "switch", "-c", "codex/bootstrap")

            first = self.run_cli(root, "bootstrap", "--format", "json")
            payload = json.loads(first.stdout)
            self.assertIn("AGENTS.md", payload["created"])
            self.assertIn("CLAUDE.md", payload["created"])
            self.assertIn("GEMINI.md", payload["created"])
            self.assertIn(".github/workflows/project-docs.yml", payload["created"])
            self.assertIn(".github/project-docs/project-docs", payload["created"])
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(agents.startswith("# project - 项目知识地图"))
            self.assertIn("React", agents)
            self.assertIn("Vite", agents)
            self.assertIn("`npm run test`", agents)
            self.assertIn("`src/`", agents)
            self.assertIn(".github/workflows/project-docs.yml", agents)
            self.assertIn("--base origin/main", agents)
            self.assertNotIn("{{", agents)
            self.assertNotIn("project-docs: template", agents)
            doctor_result = self.run_cli(root, "doctor")
            self.assertIn("OK project-docs doctor", doctor_result.stdout)
            second = self.run_cli(root, "bootstrap", "--format", "json")
            second_payload = json.loads(second.stdout)
            self.assertEqual([], second_payload["created"])

    def test_bootstrap_prioritizes_root_validation_commands_in_monorepos(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            scripts = {
                "test": "fixture",
                "lint": "fixture",
                "typecheck": "fixture",
                "check": "fixture",
                "build": "fixture",
            }
            (root / "package.json").write_text(
                json.dumps({"scripts": scripts}), encoding="utf-8"
            )
            for name in ("alpha", "beta"):
                package = root / "apps" / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(
                    json.dumps({"scripts": scripts}), encoding="utf-8"
                )
            commit_all(root)
            git(root, "switch", "-c", "codex/bootstrap")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("`npm run test`", agents)
            self.assertIn("`npm run build`", agents)

    def test_bootstrap_honors_nearest_package_manager_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
            package = root / "apps" / "legacy"
            package.mkdir(parents=True)
            (package / "package.json").write_text(
                json.dumps(
                    {
                        "packageManager": "npm@11.0.0",
                        "scripts": {"test": "jest"},
                    }
                ),
                encoding="utf-8",
            )
            (package / "package-lock.json").write_text("{}\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/bootstrap")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("npm --prefix apps/legacy run test", agents)
            self.assertNotIn("pnpm --dir apps/legacy run test", agents)

    def test_bootstrap_and_doctor_ignore_local_agent_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / ".gitignore").write_text(".agents/local/\n", encoding="utf-8")
            local = root / ".agents" / "local"
            local.mkdir(parents=True)
            (local / "package.json").write_text(
                json.dumps({"scripts": {"test": "local-only"}}), encoding="utf-8"
            )
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/bootstrap")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            (local / "AGENTS.md").write_text(
                "# {{LOCAL_ONLY}}\n[missing](missing.md)\n", encoding="utf-8"
            )
            doctor = self.run_cli(root, "doctor", check=False)

            self.assertNotIn("Node.js", agents)
            self.assertNotIn("npm run test", agents)
            self.assertEqual(0, doctor.returncode)
            self.assertNotIn("LOCAL_ONLY", doctor.stdout)

    def test_bootstrap_preserves_existing_agents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            original = valid_root_map("Existing")
            (root / "AGENTS.md").write_text(original, encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            self.run_cli(root, "bootstrap")

            self.assertEqual(original, (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("@AGENTS.md", (root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("@./AGENTS.md", (root / "GEMINI.md").read_text(encoding="utf-8").splitlines()[0])

    def test_bootstrap_refuses_committed_protected_branch_but_allows_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)

            dry_run = self.run_cli(root, "bootstrap", "--dry-run")
            self.assertIn("Would create: AGENTS.md", dry_run.stdout)
            result = self.run_cli(root, "bootstrap", check=False)
            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())

    def test_bootstrap_treats_trunk_as_protected_without_remote_head(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-b", "trunk")
            git(root, "config", "user.name", "Project Docs Tests")
            git(root, "config", "user.email", "project-docs@example.invalid")
            git(root, "remote", "add", "origin", "git@github.com:example/project.git")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线 trunk", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())

    def test_bootstrap_refuses_committed_detached_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "checkout", "--detach", "HEAD")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线 (detached)", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())

    def test_doctor_reports_broken_links_placeholders_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[missing](docs/ai/missing.md)\n")
                stream.write("<项目名>\n")
                stream.write("api_key = 'abcdefghijklmnop1234'\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)

            self.assertEqual(1, result.returncode)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}
            self.assertTrue(
                {"broken-local-link", "template-placeholder", "high-confidence-secret"}
                <= codes
            )

    def test_doctor_rejects_punctuated_credential_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write('\npassword = "Abc!defghijklmnop"\n')

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("high-confidence-secret", codes)

    def test_doctor_rejects_short_literal_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write('\npassword = "S3cr3t!"\n')

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("high-confidence-secret", codes)

    def test_doctor_allows_environment_credential_references(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\npassword = ${APP_PASSWORD}\ntoken = process.env.API_TOKEN\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(0, result.returncode)
            self.assertNotIn("high-confidence-secret", codes)

    def test_doctor_does_not_treat_code_punctuation_as_a_secret_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    '\nindex($0, "JWT" "_SECRET=") == 1 { print "JWT" "_SECRET=" value }\n'
                )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(0, result.returncode)
            self.assertNotIn("high-confidence-secret", codes)

    def test_doctor_rejects_json_credentials_and_spaced_passphrases(self) -> None:
        values = (
            '"client_secret": "abcdefghijklmnop1234"',
            'password = "correct horse battery staple"',
            "SECRET_KEY=abcdefghijklmnopqrstuvwxyz123456",
            'secretKey: "abcdefghijklmnopqrstuvwxyz123456"',
        )
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n{value}\n")

                result = self.run_cli(root, "doctor", "--format", "json", check=False)
                codes = {
                    finding["code"]
                    for finding in json.loads(result.stdout)["findings"]
                }

                self.assertEqual(1, result.returncode)
                self.assertIn("high-confidence-secret", codes)

    def test_doctor_warns_for_public_ip_but_ignores_linux_kernel_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n- Public endpoint: 8.8.8.8\n"
                    "- Runtime: WSL2 (Linux 6.6.87.2-microsoft-standard-WSL2)\n"
                    "- Misleading host: Linux 1.1.1.1-production\n"
                    "- Misleading WSL host: Linux 9.9.9.9-microsoft-standard-WSL2-production\n"
                    "- Invalid WSL version: Linux 4.2.2.2-microsoft-wsl999\n"
                    "- Linux release: Linux 6.6.87.2-generic\n"
                    "- Semantic release: v1.2.3.4\n"
                )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]
            public_ip_findings = [
                finding for finding in findings if finding["code"] == "public-ip"
            ]

            self.assertEqual(0, result.returncode)
            self.assertEqual(4, len(public_ip_findings))
            messages = {finding["message"] for finding in public_ip_findings}
            self.assertTrue(any("8.8.8.8" in message for message in messages))
            self.assertTrue(any("1.1.1.1" in message for message in messages))
            self.assertTrue(any("9.9.9.9" in message for message in messages))
            self.assertTrue(any("4.2.2.2" in message for message in messages))

    def test_doctor_warns_only_for_global_ipv6_literals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n- Public IPv6: 2606:4700:4700::1111\n"
                    "- Bracketed public IPv6: [2606:4700:4700::1001]:443\n"
                    "- Private IPv6: fd00::1\n"
                    "- Loopback IPv6: ::1\n"
                )

            normal = self.run_cli(root, "doctor", "--format", "json", check=False)
            strict = self.run_cli(
                root, "doctor", "--strict", "--format", "json", check=False
            )
            findings = [
                finding
                for finding in json.loads(normal.stdout)["findings"]
                if finding["code"] == "public-ip"
            ]

            self.assertEqual(0, normal.returncode)
            self.assertEqual(1, strict.returncode)
            self.assertEqual(2, len(findings))
            messages = {finding["message"] for finding in findings}
            self.assertTrue(any("2606:4700:4700::1111" in message for message in messages))
            self.assertTrue(any("2606:4700:4700::1001" in message for message in messages))

    def test_doctor_checks_every_credential_assignment_on_a_line(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\npassword = replace-me-before-running; "
                    "api_key = abcdefghijklmnop1234\n"
                )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("high-confidence-secret", codes)

    def test_doctor_rejects_github_tokens(self) -> None:
        values = (
            "GH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            "github_pat_11AA22BB33CC44DD55EE66FF77GG88HH99II",
            "OAuth credential: gho_abcdefghijklmnopqrstuvwxyz1234567890",
            "App user credential: ghu_abcdefghijklmnopqrstuvwxyz1234567890",
            "App server credential: ghs_abcdefghijklmnopqrstuvwxyz1234567890",
            "Refresh credential: ghr_abcdefghijklmnopqrstuvwxyz1234567890",
        )
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n{value}\n")

                result = self.run_cli(root, "doctor", "--format", "json", check=False)
                codes = {
                    finding["code"]
                    for finding in json.loads(result.stdout)["findings"]
                }

                self.assertEqual(1, result.returncode)
                self.assertIn("high-confidence-secret", codes)

    def test_doctor_scans_markdown_linked_from_knowledge_map(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "ops.md").write_text(
                "# Operations\n\nGH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[operations](docs/guides/ops.md)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "docs/guides/ops.md"
                    for finding in findings
                )
            )

    def test_doctor_scans_backticked_markdown_paths_from_knowledge_map(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "ops.md").write_text(
                "# Operations\n\nGH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n- Operations -> `docs/guides/ops.md`\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "docs/guides/ops.md"
                    for finding in findings
                )
            )

    def test_doctor_rejects_missing_backticked_markdown_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n- Operations -> `docs/guides/missing.md`\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("broken-local-link", codes)

    def test_doctor_scans_nested_repository_root_backticked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            reference_docs = root / "docs" / "reference"
            reference_docs.mkdir(parents=True)
            (reference_docs / "validation.md").write_text(
                "# Validation\n\nGH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "index.md").write_text(
                "# Guide\n\nValidation: `docs/reference/validation.md`\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n- Guide -> `docs/guides/index.md`\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertEqual({"high-confidence-secret"}, {item["code"] for item in findings})
            self.assertEqual("docs/reference/validation.md", findings[0]["path"])

    def test_doctor_falls_back_to_source_relative_backticked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "detail.md").write_text("# Detail\n", encoding="utf-8")
            (guides / "index.md").write_text(
                "# Guide\n\nDetails: `detail.md`\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n- Guide -> `docs/guides/index.md`\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)

            self.assertEqual([], json.loads(result.stdout)["findings"])

    def test_doctor_keeps_markdown_links_relative_to_source_document(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "detail.md").write_text("# Detail\n", encoding="utf-8")
            (guides / "index.md").write_text(
                "# Guide\n\n[Details](detail.md)\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n- Guide -> `docs/guides/index.md`\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)

            self.assertEqual([], json.loads(result.stdout)["findings"])

    def test_doctor_canonicalizes_recursive_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / "a").mkdir()
            (root / "b").mkdir()
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[a](a/../AGENTS.md) [b](b/../AGENTS.md)\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)

    def test_doctor_rejects_routed_symlinked_markdown_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            actual = root / "actual.md"
            actual.write_text(
                "# Operations\n\nghs_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            (guides / "ops.md").symlink_to(actual)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[operations](docs/guides/ops.md)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-knowledge-path", codes)

    def test_doctor_follows_links_with_nested_brackets_in_labels(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "ops.md").write_text(
                "# Operations\n\nghu_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[Ops [runbook]](docs/guides/ops.md)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "docs/guides/ops.md"
                    for finding in findings
                )
            )

    def test_doctor_allows_non_project_docs_template_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nHelm image tag: `{{IMAGE_TAG}}`.\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("template-placeholder", result.stdout)

    def test_doctor_rejects_private_key_pem_variants(self) -> None:
        markers = (
            "-----BEGIN ENCRYPTED PRIVATE KEY-----",
            "-----BEGIN DSA PRIVATE KEY-----",
            "-----BEGIN PGP PRIVATE KEY BLOCK-----",
        )
        for marker in markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n{marker}\n")

                result = self.run_cli(root, "doctor", "--format", "json", check=False)
                codes = {
                    finding["code"]
                    for finding in json.loads(result.stdout)["findings"]
                }

                self.assertEqual(1, result.returncode)
                self.assertIn("high-confidence-secret", codes)

    def test_doctor_allows_site_relative_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[issues](/org/repo/issues)\n[runbook](/docs/runbook.md)\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_allows_explicit_template_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            template = root / "templates"
            template.mkdir()
            (template / "AGENTS.md").write_text(
                "<!-- project-docs: template -->\n# {{PROJECT_NAME}}\n"
                "[details]({{DOC_PATH}})\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("template-placeholder", result.stdout)

    def test_doctor_rejects_template_marker_in_active_map(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / "AGENTS.md").write_text(
                "<!-- project-docs: template -->\n# {{PROJECT_NAME}}\n", encoding="utf-8"
            )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("template-marker-in-active-doc", codes)
            self.assertIn("template-placeholder", codes)

    def test_doctor_keeps_structural_warnings_advisory_unless_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            docs = root / "docs" / "ai"
            docs.mkdir(parents=True)
            (docs / "orphan.md").write_text("# Orphan\n", encoding="utf-8")

            normal = self.run_cli(root, "doctor", check=False)
            strict = self.run_cli(root, "doctor", "--strict", check=False)

            self.assertEqual(0, normal.returncode)
            self.assertIn("orphan-domain-doc", normal.stdout)
            self.assertEqual(1, strict.returncode)

    def test_doctor_does_not_treat_numeric_interval_as_markdown_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nScore headroom \\[0,1\\](cpu/load linear).\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_validates_numeric_label_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw) / "outside.md"
            initialize_repo(root)
            prepare_valid_docs(root)
            outside.write_text("# Outside\n", encoding="utf-8")
            target = os.path.relpath(outside, root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(f"\n[0,1]({target})\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-local-link", codes)

    def test_doctor_treats_even_backslashes_as_an_unescaped_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw) / "outside.md"
            initialize_repo(root)
            prepare_valid_docs(root)
            outside.write_text("# Outside\n", encoding="utf-8")
            target = os.path.relpath(outside, root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(f"\n\\\\[runbook]({target})\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-local-link", codes)

    def test_doctor_follows_even_backslash_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            guides = root / "docs" / "guides"
            guides.mkdir(parents=True)
            (guides / "ops.md").write_text(
                "# Operations\n\ngho_abcdefghijklmnopqrstuvwxyz1234567890\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n\\\\[operations](docs/guides/ops.md)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "docs/guides/ops.md"
                    for finding in findings
                )
            )

    def test_doctor_does_not_treat_inline_code_as_markdown_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nDocument syntax as `[label](not-a-real-file.md)`.\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_allows_missing_gitignored_local_truth_references(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\nLocate the main checkout and read "
                    "`.agents/local/private-hosts.md`.\n"
                )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_does_not_scan_existing_gitignored_local_truth(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            local = root / ".agents" / "local"
            local.mkdir(parents=True)
            (local / "private-hosts.md").write_text(
                "production host = 142.4.215.165\napi_token=ingest-verify-2026\n",
                encoding="utf-8",
            )
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nRead `.agents/local/private-hosts.md`.\n")
            with (root / "GEMINI.md").open("a", encoding="utf-8") as stream:
                stream.write("@./.agents/local/private-hosts.md\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("high-confidence-secret", result.stdout)
            self.assertNotIn("public-ip", result.stdout)

    def test_doctor_accepts_balanced_parentheses_and_protocol_relative_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            docs = root / "docs"
            docs.mkdir()
            (docs / "api_(v2).md").write_text("# API v2\n", encoding="utf-8")
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n[local](docs/api_(v2).md) and "
                    "[escaped](docs/api_\\(v2\\).md) and "
                    "[external](//docs.example.com/runbook).\n"
                )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_validates_reference_style_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[Runbook][ops]\n\n[ops]: docs/ai/missing.md\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {
                finding["code"]
                for finding in json.loads(result.stdout)["findings"]
            }

            self.assertEqual(1, result.returncode)
            self.assertIn("broken-local-link", codes)

    def test_doctor_ignores_escaped_reference_style_examples(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n\\[literal][missing]\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("undefined-link-reference", result.stdout)

    def test_doctor_validates_nested_reference_style_labels(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n[Ops [runbook]][ops]\n\n[ops]: docs/guides/missing.md\n"
                )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("broken-local-link", codes)

    def test_doctor_keeps_percent_encoded_filename_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            docs = root / "docs"
            docs.mkdir()
            (docs / "api#v2.md").write_text("# API\n", encoding="utf-8")
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[valid](docs/api%23v2.md)\n")

            valid = self.run_cli(root, "doctor", check=False)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("[missing](AGENTS.md%23missing)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {
                finding["code"]
                for finding in json.loads(result.stdout)["findings"]
            }

            self.assertEqual(0, valid.returncode)
            self.assertEqual(1, result.returncode)
            self.assertIn("broken-local-link", codes)

    def test_doctor_tracks_markdown_fence_delimiter_length(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n````markdown\n```\n[example](not-a-real-file.md)\n```\n````\n"
                )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_skips_indented_markdown_code_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n    [example](not-a-real-file.md)\n")

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-local-link", result.stdout)

    def test_doctor_prunes_nested_git_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / "third_party" / "dependency"
            nested.mkdir(parents=True)
            initialize_repo(nested, github=False)
            (nested / "AGENTS.md").write_text(
                "# {{UNRENDERED}}\n[missing](not-a-real-file.md)\n", encoding="utf-8"
            )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("third_party/dependency", result.stdout)

    def test_doctor_rejects_symlinked_knowledge_files_without_reading_them(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw) / "AGENTS.md"
            initialize_repo(root)
            prepare_valid_docs(root)
            module = root / "module"
            module.mkdir()
            outside.write_text("# {{SHOULD_NOT_BE_READ}}\n", encoding="utf-8")
            (module / "AGENTS.md").symlink_to(outside)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]
            codes = {finding["code"] for finding in findings}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-knowledge-path", codes)
            self.assertNotIn("template-placeholder", codes)

    def test_doctor_rejects_external_symlinked_knowledge_directories(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (outside / "runbook.md").write_text("# External\n", encoding="utf-8")
            (root / "docs").symlink_to(outside, target_is_directory=True)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n[runbook](docs/runbook.md)\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-knowledge-directory", codes)
            self.assertIn("unsafe-local-link", codes)

    def test_doctor_rejects_symlinked_local_state_directories(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / ".agents").symlink_to(outside, target_is_directory=True)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-local-state-path", codes)

    def test_doctor_reports_local_state_symlink_loops_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / ".agents").symlink_to(".agents", target_is_directory=True)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-local-state-path", codes)
            self.assertNotIn("Traceback", result.stderr)

    def test_doctor_reports_applicable_agent_chain_for_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root, github=False)
            prepare_valid_docs(root)
            source = root / "src"
            source.mkdir()
            (source / "AGENTS.md").write_text("# Source\n\n## Scope\n\n`src/` only.\n", encoding="utf-8")
            (source / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            commit_all(root)
            base = git_output(root, "rev-parse", "HEAD")
            git(root, "switch", "-c", "codex/change")
            (source / "main.py").write_text("VALUE = 2\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--base", base, "--format", "json")
            payload = json.loads(result.stdout)

            self.assertEqual(["src/main.py"], payload["changed_files"])
            self.assertEqual(["AGENTS.md", "src/AGENTS.md"], payload["applicable_agents"])

    def test_doctor_compares_changed_files_from_merge_base(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root, github=False)
            prepare_valid_docs(root)
            for name in ("task", "upstream"):
                module = root / name
                module.mkdir()
                (module / "AGENTS.md").write_text(
                    f"# {name}\n\n## Scope\n\n`{name}/` only.\n",
                    encoding="utf-8",
                )
                (module / "value.txt").write_text("base\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/change")
            (root / "task" / "value.txt").write_text("task\n", encoding="utf-8")
            commit_all(root, "task change")
            git(root, "switch", "main")
            (root / "upstream" / "value.txt").write_text("upstream\n", encoding="utf-8")
            commit_all(root, "upstream change")
            git(root, "switch", "codex/change")

            result = self.run_cli(root, "doctor", "--base", "main", "--format", "json")
            payload = json.loads(result.stdout)

            self.assertEqual(["task/value.txt"], payload["changed_files"])
            self.assertEqual(["AGENTS.md", "task/AGENTS.md"], payload["applicable_agents"])

    def test_doctor_does_not_treat_template_agents_as_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root, github=False)
            prepare_valid_docs(root)
            templates = root / "templates"
            templates.mkdir()
            (templates / "AGENTS.md").write_text(
                "<!-- project-docs: template -->\n# {{PROJECT_NAME}}\n", encoding="utf-8"
            )
            (templates / "example.txt").write_text("before\n", encoding="utf-8")
            commit_all(root)
            base = git_output(root, "rev-parse", "HEAD")
            git(root, "switch", "-c", "codex/template-change")
            (templates / "example.txt").write_text("after\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--base", base, "--format", "json")

            self.assertEqual(["AGENTS.md"], json.loads(result.stdout)["applicable_agents"])

    def test_doctor_requires_thin_claude_bridge_and_ignored_local_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("# Separate truth\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("invalid-claude-bridge", codes)
            self.assertIn("local-secrets-not-ignored", codes)

    def test_doctor_rejects_independent_gemini_truth_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / "GEMINI.md").write_text("# Separate Gemini truth\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("invalid-gemini-bridge", codes)

    def test_doctor_requires_gemini_bridge_after_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            (root / "GEMINI.md").unlink()

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("missing-gemini-bridge", codes)

    def test_doctor_rejects_symlinked_gemini_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            outside = root / "outside-gemini.md"
            outside.write_text("@./AGENTS.md\n", encoding="utf-8")
            (root / "GEMINI.md").unlink()
            (root / "GEMINI.md").symlink_to(outside)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-gemini-bridge", codes)

    def test_doctor_scans_nested_gemini_imports(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / "src"
            nested.mkdir()
            (nested / "AGENTS.md").write_text(valid_root_map("Nested"), encoding="utf-8")
            (nested / "GEMINI.md").write_text(
                "@./AGENTS.md\n@./rules.md\n",
                encoding="utf-8",
            )
            (nested / "rules.md").write_text(
                "password: imported-secret-value\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "src/rules.md"
                    for finding in findings
                )
            )

    def test_doctor_scans_embedded_multiple_and_non_markdown_gemini_imports(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / "src"
            nested.mkdir()
            (nested / "AGENTS.md").write_text(valid_root_map("Nested"), encoding="utf-8")
            (nested / "GEMINI.md").write_text(
                "Use @./AGENTS.md and @./rules.txt for this module.\n",
                encoding="utf-8",
            )
            (nested / "rules.txt").write_text(
                "password: imported-text-secret\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "src/rules.txt"
                    for finding in findings
                )
            )

    def test_doctor_does_not_parse_at_mentions_outside_gemini_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            docs = root / "docs" / "ai"
            docs.mkdir(parents=True)
            (docs / "telegram.md").write_text(
                "Create the bot with @BotFather.\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("broken-gemini-import", result.stdout)

    def test_doctor_keeps_gemini_import_paths_literal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "GEMINI.md").open("a", encoding="utf-8") as stream:
                stream.write("@./secret%20rules.md\n")
            (root / "secret%20rules.md").write_text(
                "password: literal-path-secret\n",
                encoding="utf-8",
            )
            (root / "secret rules.md").write_text("benign\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "high-confidence-secret"
                    and finding["path"] == "secret%20rules.md"
                    for finding in findings
                )
            )

    def test_doctor_allows_nested_gemini_to_bridge_to_ancestor_agents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            module = root / "src"
            nested = module / "feature"
            nested.mkdir(parents=True)
            (module / "AGENTS.md").write_text(valid_root_map("Module"), encoding="utf-8")
            (nested / "GEMINI.md").write_text("@../AGENTS.md\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(0, result.returncode)
            self.assertNotIn("invalid-gemini-bridge", codes)
            self.assertNotIn("unsafe-gemini-import", codes)

    def test_doctor_rejects_nested_gemini_bridge_to_sibling_agents(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / "src"
            sibling = nested / "other"
            sibling.mkdir(parents=True)
            (nested / "AGENTS.md").write_text(valid_root_map("Nested"), encoding="utf-8")
            (sibling / "AGENTS.md").write_text(valid_root_map("Sibling"), encoding="utf-8")
            (nested / "GEMINI.md").write_text("@./other/AGENTS.md\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("invalid-gemini-bridge", codes)

    def test_doctor_rejects_nested_gemini_without_agents_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / "src"
            nested.mkdir()
            (nested / "GEMINI.md").write_text("# Separate nested truth\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            findings = json.loads(result.stdout)["findings"]

            self.assertEqual(1, result.returncode)
            self.assertTrue(
                any(
                    finding["code"] == "invalid-gemini-bridge"
                    and finding["path"] == "src/GEMINI.md"
                    for finding in findings
                )
            )

    def test_doctor_rejects_missing_and_external_gemini_imports(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw) / "outside.md"
            initialize_repo(root)
            prepare_valid_docs(root)
            outside.write_text("external\n", encoding="utf-8")
            with (root / "GEMINI.md").open("a", encoding="utf-8") as stream:
                stream.write("@./missing.md\n")
                stream.write(f"@{outside}\n")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("broken-gemini-import", codes)
            self.assertIn("unsafe-gemini-import", codes)

    def test_doctor_allows_obvious_credential_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\n`password = replace-me-before-running`\n")
                stream.write('\n"password": "replace me before running"\n')

            result = self.run_cli(root, "doctor", check=False)

            self.assertEqual(0, result.returncode)
            self.assertNotIn("high-confidence-secret", result.stdout)

    def test_doctor_rejects_tracked_files_under_local_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            local = root / ".agents" / "local"
            local.mkdir(parents=True)
            (local / "credentials.env").write_text("fixture\n", encoding="utf-8")
            git(root, "add", "-f", ".agents/local/credentials.env")

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("tracked-local-secret", codes)

    def test_doctor_rejects_machine_local_ignore_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as config_raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            excludes = Path(config_raw) / "global-ignore"
            excludes.write_text(".agents/local/\n", encoding="utf-8")
            git(root, "config", "core.excludesFile", str(excludes))

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("local-secrets-not-ignored", codes)

    def test_doctor_rejects_repository_ignore_file_that_ignores_itself(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                ".agents/local/\n.gitignore\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("local-secrets-not-ignored", codes)

    def test_doctor_rejects_local_secret_ignore_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                ".agents/local/*\n!.agents/local/credentials.env\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {
                finding["code"]
                for finding in json.loads(result.stdout)["findings"]
            }

            self.assertEqual(1, result.returncode)
            self.assertIn("local-secrets-not-ignored", codes)

    def test_bootstrap_repairs_local_secret_ignore_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                ".agents/local/\n!.agents/local/\n",
                encoding="utf-8",
            )
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            bootstrap = self.run_cli(root, "bootstrap", "--format", "json")
            doctor = self.run_cli(root, "doctor", "--format", "json")

            self.assertIn(".gitignore:.agents/local/", json.loads(bootstrap.stdout)["created"])
            self.assertEqual([], json.loads(doctor.stdout)["findings"])

    def test_bootstrap_repairs_nested_local_secret_ignore_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            agents_dir = root / ".agents"
            agents_dir.mkdir()
            (agents_dir / ".gitignore").write_text(
                "local/\n!local/\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            bootstrap = self.run_cli(root, "bootstrap", "--format", "json")
            doctor = self.run_cli(root, "doctor", "--format", "json")

            payload = json.loads(bootstrap.stdout)
            self.assertIn(".agents/.gitignore:local/", payload["created"])
            self.assertEqual([], json.loads(doctor.stdout)["findings"])

    def test_bootstrap_does_not_treat_feature_branch_as_unknown_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git(root, "init", "-b", "custom-root")
            git(root, "config", "user.name", "Project Docs Tests")
            git(root, "config", "user.email", "project-docs@example.invalid")
            git(root, "remote", "add", "origin", "git@github.com:example/project.git")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            git(root, "update-ref", "refs/remotes/origin/codex/adopt", "HEAD")
            git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/old")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("远端默认主线:`未识别`", agents)
            self.assertNotIn("远端默认主线:codex/adopt", agents)
            self.assertNotIn("--base 未识别", agents)

    def test_bootstrap_prefers_remote_default_candidates_over_local_branches(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "update-ref", "refs/remotes/origin/master", "HEAD")
            git(root, "switch", "-c", "codex/adopt")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("远端默认主线:`master`", agents)
            self.assertIn("--base origin/master", agents)

    def test_bootstrap_honors_project_declared_protected_branch(self) -> None:
        declarations = (
            ("集成主线是", "feat/platform-refactor"),
            ("发布主线是", "release/current"),
            ("受保护分支：", "support/current"),
            ("Protected branch:", "production/current"),
            ("发布主线是", "release/v1+hotfix"),
            ("受保护分支：", "发布/当前"),
        )
        for phrase, branch in declarations:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n- {phrase} `{branch}`。\n")
                commit_all(root)
                git(root, "switch", "-c", branch)

                result = self.run_cli(root, "bootstrap", check=False)

                self.assertEqual(2, result.returncode)
                self.assertIn(f"受保护主线 {branch}", result.stderr)

    def test_bootstrap_honors_markdown_wrapped_protected_branches(self) -> None:
        declarations = (
            "**`release/current`**",
            "*`release/current`*",
            "**release/current**",
            "[`release/current`](docs/releases.md)",
        )
        for declared in declarations:
            with self.subTest(declared=declared), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n- 发布主线是 {declared}。\n")
                commit_all(root)
                git(root, "switch", "-c", "release/current")

                result = self.run_cli(root, "bootstrap", check=False)

                self.assertEqual(2, result.returncode)
                self.assertIn("受保护主线 release/current", result.stderr)

    def test_bootstrap_preserves_literal_underscores_in_protected_branches(self) -> None:
        for branch in ("_release", "release_", "_release_", "__release__"):
            with self.subTest(branch=branch), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n- 发布主线是 {branch}。\n")
                commit_all(root)
                git(root, "switch", "-c", branch)

                result = self.run_cli(root, "bootstrap", check=False)

                self.assertEqual(2, result.returncode)
                self.assertIn(f"受保护主线 {branch}", result.stderr)

    def test_bootstrap_honors_multiple_and_multiline_protected_branches(self) -> None:
        declarations = (
            "受保护分支包括 **main**, **release/current**。",
            "Protected branches: main / release/current",
            "受保护分支：\n\n- main\n- `release/current`\n",
            "Protected branches include:\n  - release/current\n",
            "受保护分支包括：\n  - release/current\n",
            "Protected branch: [**release/current**](docs/release.md)",
        )
        for declaration in declarations:
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n{declaration}\n")
                commit_all(root)
                git(root, "switch", "-c", "release/current")

                result = self.run_cli(root, "bootstrap", check=False)

                self.assertEqual(2, result.returncode)
                self.assertIn("受保护主线 release/current", result.stderr)

    def test_bootstrap_ignores_unrelated_code_spans_on_protected_branch_lines(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n- `bootstrap` 不覆盖 `AGENTS.md`,不得在受保护主线写入。\n"
                )
            commit_all(root)
            git(root, "switch", "-c", "bootstrap")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(0, result.returncode)

    def test_bootstrap_ignores_descriptive_release_branch_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nRelease branch is used for staging.\n")
            commit_all(root)
            git(root, "switch", "-c", "used")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(0, result.returncode)

    def test_bootstrap_honors_branch_shaped_values_before_prose(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nRelease branch is release/current for staging.\n")
            commit_all(root)
            git(root, "switch", "-c", "release/current")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线 release/current", result.stderr)

    def test_bootstrap_honors_plain_existing_branch_before_prose(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nIntegration branch is staging for releases.\n")
            commit_all(root)
            git(root, "switch", "-c", "staging")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线 staging", result.stderr)

    def test_bootstrap_strips_sentence_period_from_declared_branch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            with (root / "AGENTS.md").open("a", encoding="utf-8") as stream:
                stream.write("\nProtected branch is release/current.\n")
            commit_all(root)
            git(root, "switch", "-c", "release/current")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("受保护主线 release/current", result.stderr)

    def test_bootstrap_rejects_directory_in_place_of_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            (root / "AGENTS.md").mkdir()

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("输出文件位置不是普通文件", result.stderr)

    def test_bootstrap_rejects_fifo_in_place_of_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            os.mkfifo(root / "AGENTS.md")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("输出文件位置不是普通文件: AGENTS.md", result.stderr)

    def test_doctor_preserves_unicode_changed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root, github=False)
            prepare_valid_docs(root)
            module = root / "模块"
            module.mkdir()
            (module / "AGENTS.md").write_text("# 模块\n\n## Scope\n\n模块规则。\n", encoding="utf-8")
            source = module / "入口.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            commit_all(root)
            base = git_output(root, "rev-parse", "HEAD")
            git(root, "switch", "-c", "codex/unicode")
            git(root, "config", "core.quotePath", "true")
            source.write_text("VALUE = 2\n", encoding="utf-8")

            result = self.run_cli(root, "doctor", "--base", base, "--format", "json")
            payload = json.loads(result.stdout)

            self.assertEqual(["模块/入口.py"], payload["changed_files"])
            self.assertEqual(["AGENTS.md", "模块/AGENTS.md"], payload["applicable_agents"])

    def test_bootstrap_rejects_symlinked_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside = Path(outside_raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            (root / ".agents").symlink_to(outside, target_is_directory=True)

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("符号链接", result.stderr)
            self.assertFalse((outside / "local" / "README.md").exists())

    def test_bootstrap_rejects_managed_outputs_inside_nested_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            nested = root / ".github"
            nested.mkdir()
            initialize_repo(nested, github=False)

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("嵌套 Git 仓库", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((nested / "project-docs").exists())

    def test_doctor_rejects_managed_outputs_inside_nested_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            nested = root / ".github"
            nested.mkdir()
            initialize_repo(nested, github=False)
            workflow = nested / "workflows" / "project-docs.yml"
            checker = nested / "project-docs" / "project-docs"
            workflow.parent.mkdir()
            checker.parent.mkdir()
            workflow.write_text(
                "# project-docs: managed-workflow-v1\nname: project-docs\n",
                encoding="utf-8",
            )
            shutil.copy2(SCRIPT, checker)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("unsafe-managed-workflow", codes)

    def test_bootstrap_rejects_symlinked_gitignore_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
            root = Path(raw)
            outside_file = Path(outside_raw) / "shared-ignore"
            outside_file.write_text("keep-me\n", encoding="utf-8")
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            (root / ".gitignore").symlink_to(outside_file)

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("符号链接", result.stderr)
            self.assertEqual("keep-me\n", outside_file.read_text(encoding="utf-8"))

    def test_doctor_returns_structured_report_for_unreadable_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            docs = root / "docs" / "ai"
            docs.mkdir(parents=True)
            unreadable = docs / "unreadable.md"
            unreadable.write_text("# Unreadable\n", encoding="utf-8")
            unreadable.chmod(0)
            try:
                result = self.run_cli(root, "doctor", "--format", "json", check=False)
            finally:
                unreadable.chmod(0o600)
            codes = {
                finding["code"]
                for finding in json.loads(result.stdout)["findings"]
            }

            self.assertEqual(1, result.returncode)
            self.assertIn("unreadable-markdown", codes)

    def test_bootstrap_shell_quotes_nested_project_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            package = root / "apps" / "customer portal"
            package.mkdir(parents=True)
            (package / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            service = root / "services" / "payment api"
            service.mkdir(parents=True)
            (service / "go.mod").write_text("module example.invalid/payment\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            self.assertIn("npm --prefix 'apps/customer portal' run test", agents)
            self.assertIn("(cd 'services/payment api' && go test ./...)", agents)

    def test_bootstrap_safely_renders_backticks_from_repository_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            package = root / "apps`customer"
            package.mkdir()
            (package / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            doctor = self.run_cli(root, "doctor", "--strict", check=False)

            self.assertIn("``apps`customer/``", agents)
            self.assertIn("``npm --prefix 'apps`customer' run test``", agents)
            self.assertEqual(0, doctor.returncode)

    def test_bootstrap_does_not_reexpand_template_tokens_from_repository_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            package = root / "apps{{CI_PATHS}}"
            package.mkdir()
            (package / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            self.run_cli(root, "bootstrap")
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            doctor = self.run_cli(root, "doctor", "--strict", check=False)

            self.assertIn("`apps{{CI_PATHS}}/`", agents)
            self.assertEqual(1, agents.count("<!-- project-docs: ci-start -->"))
            self.assertEqual(0, doctor.returncode)

    def test_bootstrap_rejects_control_characters_from_repository_paths_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            package = root / "apps\ninjected"
            package.mkdir()
            (package / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
            )
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("控制字符", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".github" / "project-docs").exists())

    def test_bootstrap_vendors_self_contained_checker(self) -> None:
        with tempfile.TemporaryDirectory() as tool_raw, tempfile.TemporaryDirectory() as target_raw:
            tool = Path(tool_raw)
            (tool / "bin").mkdir()
            shutil.copy2(SCRIPT, tool / "bin" / "project-docs")
            shutil.copytree(REPO_ROOT / "project-template", tool / "project-template")

            target = Path(target_raw)
            initialize_repo(target)
            (target / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(target)
            git(target, "switch", "-c", "codex/adopt")
            tool_script = tool / "bin" / "project-docs"

            bootstrap = command(
                [str(tool_script), "bootstrap", "--repo", str(target), "--format", "json"],
                cwd=target,
            )
            self.assertIn(
                ".github/workflows/project-docs.yml",
                json.loads(bootstrap.stdout)["created"],
            )
            self.assertIn(
                ".github/project-docs/project-docs",
                json.loads(bootstrap.stdout)["created"],
            )
            self.assertIn(
                "不构成 required hard gate",
                "\n".join(json.loads(bootstrap.stdout)["notices"]),
            )
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(".github/workflows/project-docs.yml", agents)
            self.assertIn("只辅助检查目标为默认分支的 PR", agents)
            workflow = (target / ".github" / "workflows" / "project-docs.yml").read_text(
                encoding="utf-8"
            )
            checker = target / ".github" / "project-docs" / "project-docs"
            self.assertTrue(checker.stat().st_mode & stat.S_IXUSR)
            self.assertIn("python3 trusted/.github/project-docs/project-docs", workflow)
            self.assertNotIn("/.github/actions/project-docs@", workflow)
            self.assertIn("pull_request_target:", workflow)
            self.assertIn("edited, labeled, unlabeled", workflow)
            self.assertIn("github.event.changes.base != null", workflow)
            self.assertIn("trusted/.github/project-docs/project-docs", workflow)
            self.assertIn("allow-unsafe-pr-checkout: true", workflow)
            self.assertNotIn("  pull_request:\n", workflow)
            self.assertNotIn("  push:\n", workflow)
            self.assertNotIn("candidate-doctor", workflow)
            self.assertIn("Advisory only", workflow)
            self.assertIn("Do not configure this job as a required check", workflow)
            self.assertIn("Require the repository default branch as PR base", workflow)
            self.assertIn("PR_BASE_REF: ${{ github.event.pull_request.base.ref }}", workflow)
            self.assertIn("DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}", workflow)
            self.assertIn('if [ "$PR_BASE_REF" != "$DEFAULT_BRANCH" ]', workflow)
            self.assertIn("ref: ${{ github.sha }}", workflow)
            self.assertNotIn("ref: ${{ github.event.pull_request.base.sha }}", workflow)
            self.assertIn("project-docs-upgrade-reviewed", workflow)
            self.assertIn("github.event.action == 'labeled'", workflow)
            self.assertIn("github.event.label.name == 'project-docs-upgrade-reviewed'", workflow)
            self.assertNotIn("pull_request.labels.*.name", workflow)
            self.assertIn("--allow-reviewed-managed-update", workflow)
            self.assertIn("doctor --repo candidate --strict", workflow)
            pull_request_validation = workflow.split(
                "      - name: Validate pull request with trusted gate\n", 1
            )[1].split("      - name: Checkout pushed repository state\n", 1)[0]
            self.assertNotIn(
                "python3 candidate/.github/project-docs",
                pull_request_validation,
            )
            self.assertNotIn("Checkout pushed repository state", workflow)
            self.assertNotIn("Validate pushed repository state", workflow)
            self.assertNotIn("python3 candidate/.github/project-docs", workflow)
            self.assertEqual(tool_script.read_text(encoding="utf-8"), checker.read_text(encoding="utf-8"))
            doctor = command(
                [str(checker), "doctor", "--repo", str(target), "--format", "json"],
                cwd=target,
            )
            self.assertEqual([], json.loads(doctor.stdout)["findings"])
            fake_templates = target / ".github" / "project-template"
            fake_templates.mkdir()
            (fake_templates / "AGENTS.md").write_text("# Fake template\n", encoding="utf-8")
            vendored_bootstrap = command(
                [str(checker), "bootstrap", "--repo", str(target)],
                cwd=target,
                env={"PROJECT_DOCS_SOURCE": str(tool_script)},
            )
            self.assertEqual(0, vendored_bootstrap.returncode)
            self.assertEqual(workflow, (target / ".github" / "workflows" / "project-docs.yml").read_text(encoding="utf-8"))

            with tool_script.open("a", encoding="utf-8") as stream:
                stream.write("\n# newer checker fixture\n")
            stale = command(
                [str(tool_script), "doctor", "--repo", str(target), "--format", "json"],
                cwd=target,
                check=False,
            )
            stale_codes = {
                finding["code"] for finding in json.loads(stale.stdout)["findings"]
            }
            self.assertEqual(1, stale.returncode)
            self.assertIn("stale-managed-checker", stale_codes)

            refreshed = command(
                [str(tool_script), "bootstrap", "--repo", str(target), "--format", "json"],
                cwd=target,
            )
            self.assertIn(
                ".github/project-docs/project-docs",
                json.loads(refreshed.stdout)["updated"],
            )
            self.assertEqual(tool_script.read_text(encoding="utf-8"), checker.read_text(encoding="utf-8"))

    def test_bootstrap_repairs_and_doctor_requires_checker_execute_bit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            self.run_cli(root, "bootstrap")
            checker = root / ".github" / "project-docs" / "project-docs"
            checker.chmod(stat.S_IMODE(checker.stat().st_mode) & ~0o111)

            doctor = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(doctor.stdout)["findings"]}
            repaired = self.run_cli(root, "bootstrap", "--format", "json")

            self.assertEqual(1, doctor.returncode)
            self.assertIn("non-executable-managed-checker", codes)
            self.assertIn(
                ".github/project-docs/project-docs",
                json.loads(repaired.stdout)["updated"],
            )
            self.assertTrue(checker.stat().st_mode & stat.S_IXUSR)

    def test_bootstrap_preserves_unmarked_legacy_workflow_as_user_owned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            workflow = root / ".github" / "workflows" / "project-docs.yml"
            workflow.parent.mkdir(parents=True)
            original = (
                "name: project-docs\n"
                "jobs:\n"
                "  doctor:\n"
                "    steps:\n"
                "      - uses: example/ai-rules/.github/actions/project-docs@"
                + "a" * 40
                + "\n"
                "  custom:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo keep-me\n"
            )
            workflow.write_text(original, encoding="utf-8")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            result = self.run_cli(root, "bootstrap", "--format", "json")
            payload = json.loads(result.stdout)

            self.assertEqual(original, workflow.read_text(encoding="utf-8"))
            self.assertIn(".github/workflows/project-docs.yml", payload["preserved"])
            self.assertFalse((root / ".github" / "project-docs").exists())

    def test_doctor_allows_only_stale_artifacts_for_reviewed_managed_update(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            self.run_cli(root, "bootstrap")
            workflow = root / ".github" / "workflows" / "project-docs.yml"
            checker = root / ".github" / "project-docs" / "project-docs"
            with workflow.open("a", encoding="utf-8") as stream:
                stream.write("\n# independently reviewed update\n")
            with checker.open("a", encoding="utf-8") as stream:
                stream.write("\n# independently reviewed update\n")

            normal = self.run_cli(root, "doctor", "--format", "json", check=False)
            reviewed = self.run_cli(
                root,
                "doctor",
                "--allow-reviewed-managed-update",
                "--strict",
                "--format",
                "json",
                check=False,
            )
            normal_codes = {
                finding["code"] for finding in json.loads(normal.stdout)["findings"]
            }
            reviewed_codes = {
                finding["code"] for finding in json.loads(reviewed.stdout)["findings"]
            }

            self.assertEqual(1, normal.returncode)
            self.assertIn("stale-managed-checker", normal_codes)
            self.assertIn("stale-managed-workflow", normal_codes)
            self.assertEqual(0, reviewed.returncode)
            self.assertNotIn("stale-managed-checker", reviewed_codes)
            self.assertNotIn("stale-managed-workflow", reviewed_codes)

    def test_reviewed_managed_update_still_requires_owned_regular_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            self.run_cli(root, "bootstrap")
            workflow = root / ".github" / "workflows" / "project-docs.yml"
            workflow.write_text("name: unowned\njobs: {}\n", encoding="utf-8")

            reviewed = self.run_cli(
                root,
                "doctor",
                "--allow-reviewed-managed-update",
                "--format",
                "json",
                check=False,
            )
            codes = {
                finding["code"] for finding in json.loads(reviewed.stdout)["findings"]
            }

            self.assertEqual(1, reviewed.returncode)
            self.assertIn("invalid-managed-workflow", codes)

    def test_doctor_rejects_tampered_managed_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            prepare_valid_docs(root)
            workflow = root / ".github" / "workflows" / "project-docs.yml"
            checker = root / ".github" / "project-docs" / "project-docs"
            workflow.parent.mkdir(parents=True)
            checker.parent.mkdir(parents=True)
            workflow.write_text(
                "# project-docs: managed-workflow-v1\n"
                "# .github/project-docs/project-docs\n"
                "jobs: {}\n",
                encoding="utf-8",
            )
            shutil.copy2(SCRIPT, checker)

            result = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}

            self.assertEqual(1, result.returncode)
            self.assertIn("stale-managed-workflow", codes)

    def test_doctor_retains_managed_state_when_workflow_marker_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            self.run_cli(root, "bootstrap")
            workflow = root / ".github" / "workflows" / "project-docs.yml"
            workflow.write_text("name: no-op\njobs: {}\n", encoding="utf-8")

            doctor = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(doctor.stdout)["findings"]}

            self.assertEqual(1, doctor.returncode)
            self.assertIn("stale-managed-workflow", codes)
            refreshed = self.run_cli(root, "bootstrap", "--format", "json")
            self.assertIn(
                ".github/workflows/project-docs.yml",
                json.loads(refreshed.stdout)["updated"],
            )
            self.assertIn("pull_request_target:", workflow.read_text(encoding="utf-8"))

    def test_doctor_rejects_non_regular_managed_workflow_paths(self) -> None:
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as outside_raw:
                root = Path(raw)
                initialize_repo(root)
                prepare_valid_docs(root)
                workflow = root / ".github" / "workflows" / "project-docs.yml"
                workflow.parent.mkdir(parents=True)
                if kind == "symlink":
                    outside = Path(outside_raw) / "workflow.yml"
                    outside.write_text("jobs: {}\n", encoding="utf-8")
                    workflow.symlink_to(outside)
                else:
                    workflow.mkdir()

                result = self.run_cli(root, "doctor", "--format", "json", check=False)
                codes = {
                    finding["code"]
                    for finding in json.loads(result.stdout)["findings"]
                }

                self.assertEqual(1, result.returncode)
                self.assertIn("unsafe-managed-workflow", codes)

    def test_bootstrap_and_doctor_reject_ignored_core_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / ".gitignore").write_text(
                "AGENTS.md\nCLAUDE.md\n.agents/local/\n",
                encoding="utf-8",
            )
            (root / "fixture.txt").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")

            bootstrap = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, bootstrap.returncode)
            self.assertIn("Git 忽略规则", bootstrap.stderr)
            self.assertFalse((root / "AGENTS.md").exists())

            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            doctor = self.run_cli(root, "doctor", "--format", "json", check=False)
            codes = {finding["code"] for finding in json.loads(doctor.stdout)["findings"]}

            self.assertEqual(1, doctor.returncode)
            self.assertIn("ignored-core-artifact", codes)

    def test_bootstrap_preflights_uncommittable_gitignore_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as config_raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            excludes = Path(config_raw) / "global-ignore"
            excludes.write_text(".gitignore\n", encoding="utf-8")
            git(root, "config", "core.excludesFile", str(excludes))

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("忽略配置本身无法提交", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / "CLAUDE.md").exists())
            self.assertFalse((root / ".github").exists())
            self.assertFalse((root / ".gitignore").exists())

    def test_bootstrap_rejects_repository_ignore_file_that_ignores_itself_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            (root / "AGENTS.md").write_text(valid_root_map(), encoding="utf-8")
            (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
            (root / ".gitignore").write_text(
                ".agents/local/\n.gitignore\n",
                encoding="utf-8",
            )

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("忽略配置本身无法提交", result.stderr)
            self.assertFalse((root / ".github").exists())
            self.assertFalse((root / ".agents").exists())

    def test_bootstrap_preflights_non_utf8_gitignore_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            initialize_repo(root)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/adopt")
            (root / ".gitignore").write_bytes(b"\xff\xfe\x00")

            result = self.run_cli(root, "bootstrap", check=False)

            self.assertEqual(2, result.returncode)
            self.assertIn("无法按 UTF-8 读取 .gitignore", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / "CLAUDE.md").exists())
            self.assertFalse((root / ".github").exists())
            self.assertFalse((root / ".agents").exists())

    def test_bootstrap_requires_exact_github_origin_hostname(self) -> None:
        remotes = (
            "https://notgithub.com/example/project.git",
            "https://gitlab.example/example/github.com/project.git",
        )
        for remote in remotes:
            with self.subTest(remote=remote), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                initialize_repo(root, github=False)
                git(root, "remote", "add", "origin", remote)
                (root / "README.md").write_text("fixture\n", encoding="utf-8")
                commit_all(root)
                git(root, "switch", "-c", "codex/adopt")

                result = self.run_cli(root, "bootstrap", "--format", "json")
                payload = json.loads(result.stdout)

                self.assertNotIn(".github/workflows/project-docs.yml", payload["created"])
                self.assertIn("未识别 GitHub origin", "\n".join(payload["notices"]))

    def test_non_git_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = command(
                [str(SCRIPT), "doctor", "--repo", raw],
                cwd=Path(raw),
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("不是 Git 仓库", result.stderr)


    def test_generated_map_points_at_the_installed_tool_location(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-rules-paths-") as raw:
            base = Path(raw)
            rules = base / "rules"
            (rules / "bin").mkdir(parents=True)
            shutil.copy2(SCRIPT, rules / "bin" / "project-docs")
            shutil.copytree(REPO_ROOT / "project-template", rules / "project-template")
            (rules / "global-core.md").write_text("# core\n", encoding="utf-8")

            root = base / "project"
            root.mkdir()
            initialize_repo(root)
            (root / "main.py").write_text("print(1)\n", encoding="utf-8")
            commit_all(root)
            git(root, "switch", "-c", "codex/task")

            command(
                [str(rules / "bin" / "project-docs"), "bootstrap", "--repo", str(root)],
                cwd=root,
            )
            agents = (root / "AGENTS.md").read_text(encoding="utf-8")

            doctor = re.search(
                r"`([^`]*project-docs) doctor --repo \.(?: --base [^`]+)?`", agents
            )
            self.assertIsNotNone(doctor)
            self.assertEqual(
                (rules / "bin" / "project-docs").resolve(),
                Path(os.path.expanduser(doctor.group(1).strip("'\""))).resolve(),
            )

            core = re.search(r"`([^`]*global-core\.md)`", agents)
            self.assertIsNotNone(core)
            self.assertEqual(
                (rules / "global-core.md").resolve(),
                Path(os.path.expanduser(core.group(1).strip("'\""))).resolve(),
            )
            self.assertNotIn("ai-rules", agents)


class GeneralizedPathTests(unittest.TestCase):
    def test_install_root_prefers_env_then_default(self) -> None:
        module = load_checker_module()
        with tempfile.TemporaryDirectory() as raw:
            with mock.patch.dict(os.environ, {"AGENT_RULES_HOME": raw}):
                self.assertEqual(Path(raw), module.install_root())
        with mock.patch.dict(os.environ, {"AGENT_RULES_HOME": ""}):
            self.assertEqual(Path.home() / ".agent-rules", module.install_root())

    def test_shell_path_keeps_tilde_only_when_safe(self) -> None:
        module = load_checker_module()
        home = Path.home()
        self.assertEqual("~/a/b", module.display_path(home / "a" / "b"))
        self.assertEqual("/opt/x", module.display_path(Path("/opt/x")))
        self.assertEqual("~/a/b", module.shell_path(home / "a" / "b"))
        self.assertEqual("/opt/x", module.shell_path(Path("/opt/x")))
        spaced = home / "John Doe" / "x"
        self.assertEqual(shlex.quote(str(spaced)), module.shell_path(spaced))
        tricky = home / "a'b" / "x"
        self.assertEqual(shlex.quote(str(tricky)), module.shell_path(tricky))


def git_output(root: Path, *args: str) -> str:
    return command(["git", *args], cwd=root).stdout.strip()


if __name__ == "__main__":
    unittest.main()
