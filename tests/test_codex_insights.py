from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from datetime import UTC
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_insights as module


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


class CodexInsightsRegressionTests(unittest.TestCase):
    def make_home(self, root: Path) -> Path:
        home = root / ".codex"
        (home / "sessions" / "2026" / "07" / "27").mkdir(parents=True)
        (home / "archived_sessions").mkdir(parents=True)
        (home / "usage-data").mkdir(parents=True)
        (home / "skills" / "tdd-workflow").mkdir(parents=True)
        (home / "skills" / "tdd-workflow" / "SKILL.md").write_text(
            "---\nname: tdd-workflow\n---\n# TDD\n", encoding="utf-8"
        )
        (home / "AGENTS.md").write_text(
            "# Global\nAgent-First\nUse agents proactively without user prompt.\n"
            "Use parallel execution — launch multiple agents simultaneously.\n",
            encoding="utf-8",
        )
        (home / "config.toml").write_text(
            'model = "gpt-5.6-terra"\nmodel_reasoning_effort = "low"\nweb_search = "live"\n'
            'persistent_instructions = "Use available MCP servers when they can help."\n'
            '[features]\nmulti_agent = true\n'
            '[agents]\nmax_threads = 6\nmax_depth = 1\n'
            '[mcp_servers.context7]\ncommand = "npx"\n'
            '[mcp_servers.playwright]\ncommand = "npx"\n'
            '[mcp_servers.chrome-devtools]\ncommand = "bunx"\n'
            '[mcp_servers.sequential-thinking]\ncommand = "npx"\n'
            '[profiles.strict]\napproval_policy = "on-request"\n',
            encoding="utf-8",
        )
        (home / "daily.config.toml").write_text(
            'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "medium"\n', encoding="utf-8"
        )
        (home / "usage-data" / "mcp-verbose.txt").write_text(
            "  • context7\n    • Tools: query-docs, resolve-library-id\n    • Resources: (none)\n",
            encoding="utf-8",
        )
        return home

    def root_records(self) -> list[dict]:
        injected = "# AGENTS.md instructions for X\n<INSTRUCTIONS>\n### Available skills\n- fake\n</INSTRUCTIONS>\n<environment_context>ctx</environment_context>"
        return [
            {"timestamp": "2026-07-27T10:00:00Z", "type": "session_meta", "payload": {
                "id": "root-1", "cwd": "/workspace/app", "model_provider": "openai", "cli_version": "0.200.0"
            }},
            {"timestamp": "2026-07-27T10:00:01Z", "type": "turn_context", "payload": {
                "model": "gpt-5.6-sol", "effort": "ultra", "service_tier": "default"
            }},
            {"timestamp": "2026-07-27T10:00:02Z", "type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": injected}]
            }},
            {"timestamp": "2026-07-27T10:00:02.100Z", "type": "event_msg", "payload": {
                "type": "user_message", "message": "# AGENTS.md instructions <INSTRUCTIONS>automatic</INSTRUCTIONS>"
            }},
            {"timestamp": "2026-07-27T10:00:02.200Z", "type": "event_msg", "payload": {
                "type": "user_message", "message": "<subagent_notification>{\"status\":\"done\"}</subagent_notification>"
            }},
            {"timestamp": "2026-07-27T10:00:03Z", "type": "event_msg", "payload": {
                "type": "user_message", "message": "Corrija o login e adicione testes usando $GITHUB_PAT e $env"
            }},
            {"timestamp": "2026-07-27T10:00:04Z", "type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Corrija o login e adicione testes usando $GITHUB_PAT e $env"}]
            }},
            {"timestamp": "2026-07-27T10:00:05Z", "type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "skill", "name": "tdd-workflow", "path": "/skills/tdd-workflow/SKILL.md"}]
            }},
            {"timestamp": "2026-07-27T10:00:06Z", "type": "event_msg", "payload": {"type": "task_started"}},
            {"timestamp": "2026-07-27T10:00:07Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 900, "cached_input_tokens": 400, "output_tokens": 100, "reasoning_output_tokens": 20, "total_tokens": 1000},
                "last_token_usage": {"input_tokens": 900, "cached_input_tokens": 400, "output_tokens": 100, "reasoning_output_tokens": 20, "total_tokens": 1000}
            }}},
            {"timestamp": "2026-07-27T10:00:08Z", "type": "event_msg", "payload": {"type": "mcp_tool_call_begin", "call_id": "m1", "invocation": {
                "server": "context7", "tool": "query_docs", "arguments": {"q": "auth"}
            }}},
            {"timestamp": "2026-07-27T10:00:08.500Z", "type": "response_item", "payload": {
                "type": "function_call", "call_id": "m1", "name": "query-docs", "arguments": "{}"
            }},
            {"timestamp": "2026-07-27T10:00:09Z", "type": "event_msg", "payload": {"type": "mcp_tool_call_end", "call_id": "m1", "invocation": {
                "server": "context7", "tool": "query_docs"
            }, "success": True}},
            {"timestamp": "2026-07-27T10:00:10Z", "type": "response_item", "payload": {
                "type": "function_call", "call_id": "a1", "name": "spawn_agent", "arguments": "{}"
            }},
            {"timestamp": "2026-07-27T10:00:11Z", "type": "response_item", "payload": {
                "type": "function_call", "call_id": "s1", "name": "shell_command",
                "arguments": {"command": "cat /home/user/.codex/skills/tdd-workflow/SKILL.md"}
            }},
            {"timestamp": "2026-07-27T10:00:12Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 1800, "cached_input_tokens": 1000, "output_tokens": 200, "reasoning_output_tokens": 50, "total_tokens": 2000},
                "last_token_usage": {"input_tokens": 900, "cached_input_tokens": 600, "output_tokens": 100, "reasoning_output_tokens": 30, "total_tokens": 1000}
            }}},
            {"timestamp": "2026-07-27T10:00:20Z", "type": "event_msg", "payload": {"type": "task_complete"}},
        ]

    def subagent_records(self) -> list[dict]:
        return [
            {"timestamp": "2026-07-27T10:00:10Z", "type": "session_meta", "payload": {
                "id": "sub-1", "cwd": "/workspace/app", "model_provider": "openai",
                "source": {"subagent": {"parent_thread_id": "root-1", "agent_role": "reviewer"}}
            }},
            {"timestamp": "2026-07-27T10:00:11Z", "type": "turn_context", "payload": {"model": "gpt-5.6-terra", "effort": "medium"}},
            {"timestamp": "2026-07-27T10:00:12Z", "type": "event_msg", "payload": {"type": "task_started"}},
            {"timestamp": "2026-07-27T10:00:13Z", "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 450, "output_tokens": 50, "reasoning_output_tokens": 10, "total_tokens": 500}
            }}},
            {"timestamp": "2026-07-27T10:00:15Z", "type": "event_msg", "payload": {"type": "task_complete"}},
        ]

    def test_corrected_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = self.make_home(root)
            root_path = home / "sessions" / "2026" / "07" / "27" / "rollout-root.jsonl"
            sub_path = home / "sessions" / "2026" / "07" / "27" / "rollout-sub.jsonl"
            duplicate_path = home / "archived_sessions" / "rollout-root-copy.jsonl"
            write_jsonl(root_path, self.root_records())
            write_jsonl(sub_path, self.subagent_records())
            write_jsonl(duplicate_path, self.root_records()[:6])
            out = root / "out"
            args = argparse.Namespace(
                codex_home=str(home), days=30, all_time=True, include_archived=True,
                exclude_subagents=False, include_full_prompts=False,
                mcp_verbose_file=None, output_dir=str(out), top=30,
            )
            report, output_dir = module.make_report(args)
            summary = report["summary"]
            self.assertEqual(summary["sessions"], 2)
            self.assertEqual(summary["root_sessions"], 1)
            self.assertEqual(summary["subagent_sessions"], 1)
            self.assertEqual(summary["usage_root"]["total_tokens"], 2000)
            self.assertEqual(summary["usage_subagents"]["total_tokens"], 500)
            self.assertEqual(summary["usage_all"]["total_tokens"], 2500)
            self.assertEqual(summary["usage_all"]["reasoning_output_tokens"], 60)
            self.assertEqual(summary["turns_root"], 1)
            self.assertEqual(summary["turns_subagents"], 1)
            self.assertEqual(summary["human_prompts"], 1)
            self.assertEqual(report["breakdowns"]["models"].get("openai"), None)
            self.assertEqual(report["breakdowns"]["models"]["gpt-5.6-sol"], 1)
            self.assertEqual(report["breakdowns"]["providers"]["openai"], 2)
            self.assertEqual(report["breakdowns"]["mcp_servers"]["context7"], 1)
            self.assertEqual(report["breakdowns"]["mcp_tools"]["context7::query-docs"], 1)
            self.assertEqual(report["breakdowns"]["tools"]["context7::query-docs"], 1)
            self.assertEqual(report["breakdowns"]["tools"]["spawn_agent"], 1)
            self.assertIn("tdd-workflow", report["breakdowns"]["skills"])
            self.assertNotIn("fake", report["breakdowns"]["skills"])
            self.assertNotIn("github-pat", report["breakdowns"]["skills"])
            self.assertNotIn("env", report["breakdowns"]["skills"])
            self.assertGreaterEqual(report["breakdowns"]["excluded_messages"].get("agents-context", 0), 2)
            self.assertGreaterEqual(report["breakdowns"]["excluded_messages"].get("automatic-control-context", 0), 1)
            self.assertEqual(len(report["deduplicated_files"]), 1)
            self.assertIn("strict", report["config_inventory"]["legacy_nested_profiles"])
            self.assertTrue((output_dir / "suggested-profiles" / "daily.config.toml").is_file())
            self.assertTrue((output_dir / "report.md").is_file())
            self.assertIn("Sessões principais", (output_dir / "report.md").read_text(encoding="utf-8"))

    def test_mcp_verbose_parser_handles_wrapping(self) -> None:
        text = """
  • chrome-devtools
    • Auth: Unsupported
    • Tools: click, evaluate_script, lighthouse_audit,
    performance_start_trace, performance_stop_trace
    • Resources: (none)
  • context7
    • Auth: Unsupported
    • Tools: query-docs, resolve-library-id
    • Resources: (none)
"""
        result = module.parse_mcp_verbose(text)
        self.assertEqual(result["context7"], ["query-docs", "resolve-library-id"])
        self.assertIn("performance_stop_trace", result["chrome-devtools"])
        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / "mcp.txt"
            inventory.write_text(text, encoding="utf-8")
            _servers, reverse = module.load_mcp_inventory(inventory, Path(temp))
            self.assertEqual(reverse["query_docs"], ("context7", "query-docs"))

    def test_control_prompt_is_not_substantive(self) -> None:
        self.assertTrue(module.is_control_prompt("continue"))
        self.assertTrue(module.is_control_prompt("Aprovado."))
        self.assertTrue(module.is_control_prompt("1"))
        self.assertTrue(module.is_control_prompt("pode"))
        self.assertTrue(module.is_control_prompt("8:20 PM"))
        self.assertTrue(module.is_control_prompt("</image>"))
        self.assertFalse(module.is_control_prompt("Continue corrigindo o módulo de autenticação"))

    def test_profile_models_stay_on_latest_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = self.make_home(root)
            sol = module.SessionRecord(path="sol")
            sol.models["gpt-5.6-sol"] = 1
            terra = module.SessionRecord(path="terra")
            terra.models["gpt-5.6-terra"] = 1
            spark = module.SessionRecord(path="spark")
            spark.models["gpt-5.3-codex-spark"] = 1
            inventory = module.config_inventory(home, [])
            selection = module.select_profile_models([sol, terra, spark], inventory)
            self.assertEqual(selection["generation"], "5.6")
            self.assertEqual(selection["deep"], "gpt-5.6-sol")
            self.assertEqual(selection["volume"], "gpt-5.6-terra")
            self.assertEqual(selection["subagent"], "gpt-5.6-terra")
            self.assertIn("gpt-5.3-codex-spark", selection["historical_ignored"])

    def test_intent_taxonomy_for_common_prompts(self) -> None:
        self.assertEqual(module.classify_intent("# Conventional Commit\nCreate and execute the commit"), "version-control")
        self.assertEqual(module.classify_intent("Audite SEO, AEO, GEO e sitemap"), "seo/visibility")
        self.assertEqual(module.classify_intent("Troque o login Google por email e senha"), "authentication/access")

    def test_timestamp_parsing_and_redaction_edge_cases(self) -> None:
        self.assertIsNone(module.parse_ts(None))
        self.assertIsNone(module.parse_ts(""))
        self.assertIsNone(module.parse_ts(object()))
        self.assertIsNone(module.parse_ts("not-a-timestamp"))
        self.assertIsNone(module.parse_ts(float("inf")))

        seconds = module.parse_ts(1_700_000_000)
        milliseconds = module.parse_ts(1_700_000_000_000)
        iso = module.parse_ts("2026-07-30T10:00:00Z")
        naive = module.parse_ts("2026-07-30T10:00:00")
        numeric = module.parse_ts("1700000000")

        self.assertEqual(seconds, milliseconds)
        self.assertEqual(seconds, numeric)
        self.assertEqual(iso.tzinfo, UTC)
        self.assertEqual(naive.tzinfo, UTC)
        self.assertEqual(
            module.redact_obj(
                {
                    "api_key": "fixture-value",
                    "items": ["sk-" + ("x" * 24), 42],
                }
            ),
            {"api_key": "[REDACTED]", "items": ["[REDACTED]", 42]},
        )

    def test_safe_jsonl_and_content_helpers_ignore_invalid_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.jsonl"
            path.write_text(
                "\nnot-json\n[]\n{\"ok\": true}\n",
                encoding="utf-8",
            )
            self.assertEqual(list(module.safe_jsonl(path)), [(4, {"ok": True})])
            self.assertEqual(list(module.safe_jsonl(Path(temp) / "missing.jsonl")), [])

        texts, skills = module.content_items(
            [
                "plain",
                {"type": "input_text", "text": "structured"},
                {"type": "skill", "name": "tdd-workflow", "path": "/skills/tdd-workflow/SKILL.md"},
                123,
            ]
        )
        self.assertEqual(texts, ["plain", "structured"])
        self.assertEqual(skills, [("tdd-workflow", "/skills/tdd-workflow/SKILL.md")])
        self.assertEqual(module.content_items({"message": "one"})[0], ["one"])
        self.assertEqual(module.content_items(None), ([], []))

        nested = {"outer": [{"target": "value"}]}
        self.assertEqual(module.recursive_find_first(nested, {"target"}), "value")
        self.assertIsNone(module.recursive_find_first(nested, {"missing"}))
        self.assertEqual(module.model_value("gpt-example"), "gpt-example")
        self.assertIsNone(module.model_value("openai"))
        self.assertIsNone(module.model_value(123))
        self.assertEqual(module.scalar_name({"mode": "deep"}), "deep")
        self.assertIsNone(module.scalar_name(123))

    def test_main_prints_generated_report_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp)
            report = {
                "summary": {
                    "root_sessions": 2,
                    "subagent_sessions": 1,
                    "usage_root": {"total_tokens": 100},
                    "usage_subagents": {"total_tokens": 20},
                    "tool_calls_all": 3,
                }
            }
            with (
                mock.patch.object(module, "make_report", return_value=(report, output_dir)),
                mock.patch("builtins.print") as printer,
            ):
                result = module.main(["--all-time"])

        self.assertEqual(result, 0)
        rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("principais=2 subagentes=1", rendered)
        self.assertIn(str(output_dir / "report.html"), rendered)


if __name__ == "__main__":
    unittest.main()
