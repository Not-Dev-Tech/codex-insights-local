from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_distribution_contains_only_a_sanitized_mcp_example(self) -> None:
        example = ROOT / "examples" / "mcp-verbose.example.txt"

        self.assertFalse((ROOT / "mcp-verbose.txt").exists())
        self.assertTrue(example.is_file())

        contents = example.read_text(encoding="utf-8")
        self.assertIn("context7", contents)
        self.assertNotRegex(
            contents,
            re.compile(
                r"github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|"
                r"sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+"
            ),
        )

    def test_installers_never_copy_a_bundled_mcp_inventory(self) -> None:
        powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")
        shell = (ROOT / "install.sh").read_text(encoding="utf-8")

        self.assertNotIn('$Root "mcp-verbose.txt"', powershell)
        self.assertNotIn('$ROOT/mcp-verbose.txt', shell)
        self.assertIn("/mcp verbose", powershell)
        self.assertIn("/mcp verbose", shell)

    def test_sensitive_local_outputs_are_ignored(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        expected = {
            ".codex/",
            "mcp-verbose.txt",
            "profile-ledger.jsonl",
            "report.html",
            "report.md",
            "report.json",
            "sessions.csv",
            "prompts.csv",
            "tools.csv",
            ".env",
            ".env.*",
        }

        self.assertTrue(expected.issubset(set(ignored)))

    def test_python_project_metadata_matches_the_release(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]

        self.assertEqual(project["name"], "codex-insights-local")
        self.assertEqual(project["version"], "0.2.3")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project.get("dependencies", []), [])
        self.assertIn(
            "coverage>=7.10",
            project["optional-dependencies"]["test"],
        )
        self.assertEqual(
            project["scripts"]["codex-insights"],
            "codex_insights:main",
        )

    def test_public_documentation_uses_the_canonical_repository(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        readme_pt = (ROOT / "README.pt-BR.md").read_text(encoding="utf-8")
        canonical = "https://github.com/Not-Dev-Tech/codex-insights-local"

        for contents in (readme, readme_pt):
            self.assertIn(canonical, contents)
            self.assertIn("not affiliated", contents.lower())
            self.assertIn("--include-full-prompts", contents)

        for filename in (
            "LICENSE",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
        ):
            self.assertTrue((ROOT / filename).is_file(), filename)


if __name__ == "__main__":
    unittest.main()
