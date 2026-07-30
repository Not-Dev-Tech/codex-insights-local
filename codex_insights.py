#!/usr/bin/env python3
"""Codex Insights Local.

A local-first, read-only analyzer for Codex CLI rollout JSONL files.
It does not call an LLM, MCP server, OpenAI API, or the network.

The parser deliberately distinguishes:
- measured: values directly present in rollout/config records;
- derived: deterministic aggregation such as session duration;
- heuristic: prompt intent, objective, and historical profile inference;
- unavailable: telemetry that the local rollout did not record.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

VERSION = "0.2.3"

SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|cookie|credential|bearer)"
)
SECRET_PATTERNS = [
    re.compile(r"(?i)\bsk-[a-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[a-z0-9]{20,}\b"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/-]{12,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
]

URL_RE = re.compile(r"https?://\S+")
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s'\"`<>]+")
UNIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s'\"`<>/]+/)*[^\s'\"`<>/]+")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)
HEX_RE = re.compile(r"\b[0-9a-f]{12,}\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
EXPLICIT_SKILL_RE = re.compile(r"(?<![\w-])\$([A-Za-z][A-Za-z0-9-]{1,100})(?![A-Za-z0-9_])")
VALID_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SKILL_MD_RE = re.compile(r"(?i)(?:^|[\\/])([^\\/\s]+)[\\/]SKILL\.md(?:$|[\s'\"`])")
MODEL_RE = re.compile(r"(?i)(?:^|[-_/])(gpt|codex|o\d|chatgpt|claude|gemini|llama|qwen|mistral)")

CONTROL_PROMPT_RE = re.compile(
    r"(?is)^\s*(?:continue|continue\.|continuar|continue daí|prossiga|pode continuar|"
    r"ok|okay|sim|yes|aprovado|approved|go ahead|faça|pode|pode fazer|segue|next|retry|"
    r"tente novamente|[0-9]{1,2})\s*[.!?]*\s*$"
)
TIME_ONLY_RE = re.compile(r"(?i)^\s*(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*[ap]\.?m\.?)?\s*$")
MODEL_VERSION_RE = re.compile(r"(?i)gpt-(\d+)\.(\d+)")

INJECTED_STARTS = (
    "<environment_context>",
    "<permissions instructions>",
    "<apps_instructions>",
    "<collaboration_mode>",
    "<INSTRUCTIONS>",
    "# AGENTS.md instructions",
    "# Developer instructions",
    "You are ChatGPT,",
    "<turn_aborted>",
    "<subagent_notification>",
    "<codex_internal_context",
    "<recommended_plugins>",
)

AGENT_TOOL_NAMES = {
    "spawn_agent", "wait_agent", "send_message", "list_agents", "interrupt_agent",
    "followup_task", "agent", "spawn", "wait", "close_agent",
}
SHELL_TOOL_NAMES = {
    "exec_command", "shell_command", "shell", "command_execution", "container.exec", "exec",
    "run_command", "run", "powershell", "bash",
}
PATCH_TOOL_NAMES = {
    "apply_patch", "patch", "file_change", "write_file", "create_file", "update_file",
}

INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("version-control", ("conventional commit", "faça o commit", "faca o commit", "commit each", "faça o push", "faca o push", "git commit", "git push", "pull request", "merge request", "crie uma branch", "create branch")),
    ("seo/visibility", ("seo", "aeo", "geo", "search console", "sitemap", "schema.org", "dados estruturados", "structured data", "core web vitals", "cwv")),
    ("authentication/access", ("login", "autentica", "authentication", "authorization", "email e senha", "password", "cadastro de usuários", "cadastro de usuarios", "controle de acesso", "permission")),
    ("media/video", ("vídeo", "video", "render", "footage", "ffmpeg", "storyboard", "hyperframes", "shotlist")),
    ("debug/correction", ("bug", "debug", "erro", "error", "corrig", "fix", "falha", "exception", "regress")),
    ("implementation/feature", ("implemente", "implement", "adicione", "create", "crie", "feature", "funcionalidade", "build")),
    ("review/audit", ("review", "revise", "audite", "audit", "code review", "auditoria")),
    ("performance", ("performance", "desempenho", "fps", "latência", "latency", "profil", "otimiz", "lento", "slow")),
    ("testing/qa", ("test", "teste", "coverage", "e2e", "unitário", "playwright", "cypress", "qa")),
    ("refactor/maintenance", ("refactor", "refatore", "cleanup", "limpe", "migre", "migration", "upgrade", "dependên")),
    ("research/comparison", ("pesquise", "research", "compare", "benchmark", "paper", "documentação", "docs", "@search", "web search")),
    ("planning/architecture", ("plano", "planeje", "arquitet", "design", "estratégia", "roadmap", "especificação", "spec")),
    ("devops/deploy", ("deploy", "vercel", "docker", "kubernetes", "ci/cd", "pipeline", "infra", "terraform", "cloudflare")),
    ("ui/frontend", ("frontend", "interface", "layout", "css", "tailwind", "animação", "animation", "figma", "responsiv", "ui/ux")),
    ("data/analytics", ("sql", "dados", "analytics", "métrica", "dashboard", "csv", "planilha", "dataframe")),
    ("documentation/writing", ("documente", "documentation", "readme", "relatório", "report", "escreva", "rewrite", "texto")),
    ("agent/configuration", ("mcp", "skill", "agents.md", "codex", "config.toml", "profile", "subagent", "agente")),
]
SIMPLE_INTENTS = {"documentation/writing", "testing/qa", "refactor/maintenance", "version-control"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, tz=UTC)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            result = datetime.fromisoformat(value)
            if result.tzinfo is None:
                result = result.replace(tzinfo=UTC)
            return result.astimezone(UTC)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except (ValueError, OSError, OverflowError):
                return None
    return None


def redact_text(text: str) -> str:
    result = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            result = pattern.sub(lambda match: (match.group(1) or "") + "[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


def redact_obj(value: Any, key: str = "") -> Any:
    if key and SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_obj(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(item, key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def safe_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, 1):
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield line_number, value
    except OSError:
        return


def normalize_prompt(text: str) -> str:
    text = redact_text(text).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def template_prompt(text: str) -> str:
    text = normalize_prompt(text)
    text = URL_RE.sub("<url>", text)
    text = WINDOWS_PATH_RE.sub("<path>", text)
    text = UNIX_PATH_RE.sub("<path>", text)
    text = UUID_RE.sub("<id>", text)
    text = HEX_RE.sub("<hash>", text)
    text = re.sub(r"`[^`]{1,500}`", "<code>", text)
    text = re.sub(r'"[^"\n]{1,200}"|\'[^\'\n]{1,200}\'', "<value>", text)
    text = NUMBER_RE.sub("<n>", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_id(text: str) -> str:
    return hashlib.sha256(normalize_prompt(text).encode("utf-8", "replace")).hexdigest()[:12]


def classify_intent(text: str) -> str:
    lowered = normalize_prompt(text)
    scored: list[tuple[int, int, str]] = []
    for index, (name, needles) in enumerate(INTENT_RULES):
        score = sum(lowered.count(needle) for needle in needles)
        if score:
            scored.append((score, -index, name))
    return max(scored)[2] if scored else "other/unclear"


def objective_preview(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", redact_text(text)).strip()
    clean = re.sub(r"^(?:@search|@web\s+search)\s*", "", clean, flags=re.IGNORECASE)
    if not clean:
        return "[sem objetivo textual detectável]"
    for separator in (". ", "? ", "! "):
        if separator in clean:
            first = clean.split(separator, 1)[0]
            if len(first) >= 35:
                clean = first
                break
    return clean[:limit] + ("…" if len(clean) > limit else "")


def is_control_prompt(text: str) -> bool:
    stripped = text.strip()
    if CONTROL_PROMPT_RE.match(stripped) or TIME_ONLY_RE.fullmatch(stripped):
        return True
    return bool(re.fullmatch(r"(?is)</?image(?:\s+[^>]*)?>", stripped))


def injected_reason(text: str) -> str | None:
    stripped = text.lstrip()
    lowered = stripped.lower()
    if lowered.startswith("# agents.md instructions") and "<instructions>" in lowered[:2000]:
        return "agents-context"
    if lowered.startswith(("<turn_aborted>", "<subagent_notification>", "<codex_internal_context", "<recommended_plugins>")):
        return "automatic-control-context"
    if re.fullmatch(r"(?is)</?image(?:\s+[^>]*)?>", stripped.strip()):
        return "attachment-metadata"
    for prefix in INJECTED_STARTS:
        if stripped.startswith(prefix):
            return "automatic-context"
    if "<environment_context>" in lowered and ("<instructions>" in lowered or len(stripped) > 1200):
        return "environment-context"
    if "### available skills" in lowered and ("skill.md" in lowered or "plugin" in lowered) and len(stripped) > 1000:
        return "skill-catalog-context"
    if "you have " in lowered and "weighted tokens left" in lowered:
        return "runtime-context"
    return None


def content_items(content: Any) -> tuple[list[str], list[tuple[str, str | None]]]:
    texts: list[str] = []
    skills: list[tuple[str, str | None]] = []
    if isinstance(content, str):
        return [content], skills
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return texts, skills
    for item in content:
        if isinstance(item, str):
            texts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type == "skill":
            name = item.get("name") or item.get("skill_name")
            path = item.get("path")
            if isinstance(name, str) and name:
                skills.append((name, str(path) if path else None))
            continue
        for key in ("text", "input_text", "message"):
            value = item.get(key)
            if isinstance(value, str) and value:
                texts.append(value)
                break
    return texts, skills


def recursive_find_first(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in keys and item not in (None, ""):
                return item
        for item in value.values():
            result = recursive_find_first(item, keys)
            if result not in (None, ""):
                return result
    elif isinstance(value, list):
        for item in value:
            result = recursive_find_first(item, keys)
            if result not in (None, ""):
                return result
    return None


def model_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() in {"openai", "azure", "default", "unknown"}:
        return None
    return value if MODEL_RE.search(value) else None


def scalar_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("kind", "mode", "name", "type"):
            if isinstance(value.get(key), str):
                return value[key]
    return None


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> Usage:
        raw = raw or {}
        def number(*names: str) -> int:
            for name in names:
                value = raw.get(name)
                if isinstance(value, (int, float)):
                    return max(0, int(value))
            return 0
        input_tokens = number("input_tokens", "input")
        output_tokens = number("output_tokens", "output")
        total = number("total_tokens", "total")
        # Reasoning output is normally a subset of output tokens; never add it again.
        if not total:
            total = input_tokens + output_tokens
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=number("cached_input_tokens", "cached_input"),
            cache_write_input_tokens=number("cache_write_input_tokens", "cache_write_input"),
            output_tokens=output_tokens,
            reasoning_output_tokens=number("reasoning_output_tokens", "reasoning_output"),
            total_tokens=total,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }

    def add(self, other: Usage) -> None:
        for key in self.as_dict():
            setattr(self, key, getattr(self, key) + getattr(other, key))


@dataclass
class PromptRecord:
    timestamp: str | None
    text: str
    source: str
    exact_id: str
    template: str
    intent: str
    objective: str
    control: bool


@dataclass
class SkillUse:
    name: str
    evidence: set[str] = field(default_factory=set)
    count: int = 0


@dataclass
class ToolCall:
    call_id: str
    name: str = "unknown"
    category: str = "other"
    server: str | None = None
    tool: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    success: bool | None = None
    sources: set[str] = field(default_factory=set)


@dataclass
class SessionRecord:
    path: str
    file_size: int = 0
    records: int = 0
    parse_errors: int = 0
    session_id: str = "unknown"
    cwd: str | None = None
    originator: str | None = None
    cli_version: str | None = None
    model_provider: str | None = None
    parent_thread_id: str | None = None
    agent_role: str | None = None
    agent_nickname: str | None = None
    source_kind: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    models: Counter[str] = field(default_factory=Counter)
    efforts: Counter[str] = field(default_factory=Counter)
    service_tiers: Counter[str] = field(default_factory=Counter)
    collaboration_modes: Counter[str] = field(default_factory=Counter)
    prompts: list[PromptRecord] = field(default_factory=list)
    excluded_messages: Counter[str] = field(default_factory=Counter)
    skills: dict[str, SkillUse] = field(default_factory=dict)
    tool_calls: dict[str, ToolCall] = field(default_factory=dict)
    turns_started: int = 0
    turns_completed: int = 0
    turns_aborted: int = 0
    active_turn_start: datetime | None = None
    active_turn_duration_ms: int = 0
    cumulative_usage: Usage = field(default_factory=Usage)
    cumulative_usage_first: Usage | None = None
    cumulative_usage_seen: bool = False
    last_usage_events: list[Usage] = field(default_factory=list)
    current_last_usage: Usage | None = None
    per_turn_usage: list[Usage] = field(default_factory=list)
    token_events: int = 0
    latest_rate_limits: dict[str, Any] = field(default_factory=dict)
    compactions: int = 0
    warnings: list[str] = field(default_factory=list)
    profile_name: str | None = None
    profile_confidence: str = "unknown"
    _prompt_seen: dict[str, datetime | None] = field(default_factory=dict, repr=False)

    def update_ts(self, timestamp: datetime | None) -> None:
        if not timestamp:
            return
        if self.first_ts is None or timestamp < self.first_ts:
            self.first_ts = timestamp
        if self.last_ts is None or timestamp > self.last_ts:
            self.last_ts = timestamp

    def add_skill(self, name: str, evidence: str) -> None:
        name = name.strip().lower().replace("_", "-")
        if not name or not VALID_SKILL_NAME_RE.fullmatch(name):
            return
        use = self.skills.setdefault(name, SkillUse(name=name))
        use.evidence.add(evidence)
        use.count += 1

    def add_prompt(self, text: str, source: str, timestamp: datetime | None) -> None:
        text = text.strip()
        if not text:
            return
        reason = injected_reason(text)
        if reason:
            self.excluded_messages[reason] += 1
            return
        exact = stable_id(text)
        previous = self._prompt_seen.get(exact)
        if previous is not None and timestamp is not None and abs((timestamp - previous).total_seconds()) <= 3:
            return
        if previous is None and exact in self._prompt_seen:
            return
        self._prompt_seen[exact] = timestamp
        control = is_control_prompt(text)
        self.prompts.append(PromptRecord(
            timestamp=timestamp.isoformat() if timestamp else None,
            text=redact_text(text),
            source=source,
            exact_id=exact,
            template=template_prompt(text),
            intent="control/continuation" if control else classify_intent(text),
            objective=objective_preview(text),
            control=control,
        ))
        for skill in EXPLICIT_SKILL_RE.findall(text):
            self.add_skill(skill, "explicit-user-text")

    def get_tool(self, call_id: str, name: str = "unknown", source: str = "unknown") -> ToolCall:
        call = self.tool_calls.get(call_id)
        if call is None:
            call = ToolCall(call_id=call_id, name=name or "unknown")
            self.tool_calls[call_id] = call
        elif call.name == "unknown" and name:
            call.name = name
        call.sources.add(source)
        return call

    def close_turn(self, timestamp: datetime | None, aborted: bool = False) -> None:
        if aborted:
            self.turns_aborted += 1
        else:
            self.turns_completed += 1
        if self.active_turn_start and timestamp and timestamp >= self.active_turn_start:
            self.active_turn_duration_ms += int((timestamp - self.active_turn_start).total_seconds() * 1000)
        self.active_turn_start = None
        self.current_last_usage = None

    def is_subagent(self) -> bool:
        if self.parent_thread_id or self.agent_role or self.agent_nickname:
            return True
        return bool(self.source_kind and any(token in self.source_kind.lower() for token in ("subagent", "agent", "spawn")))

    def dominant(self, counter: Counter[str]) -> str | None:
        return counter.most_common(1)[0][0] if counter else None

    def dominant_model(self) -> str | None:
        return self.dominant(self.models)

    def dominant_effort(self) -> str | None:
        return self.dominant(self.efforts)

    def dominant_tier(self) -> str | None:
        return self.dominant(self.service_tiers)

    def substantive_prompts(self) -> list[PromptRecord]:
        return [prompt for prompt in self.prompts if not prompt.control]

    def objective(self) -> str:
        prompts = self.substantive_prompts()
        return prompts[0].objective if prompts else "[sem objetivo humano substantivo detectado]"

    def intent(self) -> str:
        prompts = self.substantive_prompts()
        return prompts[0].intent if prompts else "other/unclear"

    def duration_ms(self) -> int:
        if self.first_ts and self.last_ts and self.last_ts >= self.first_ts:
            return int((self.last_ts - self.first_ts).total_seconds() * 1000)
        return 0

    def turns(self) -> int:
        observed = max(self.turns_started, self.turns_completed + self.turns_aborted)
        return observed or len(self.prompts)

    def usage(self) -> tuple[Usage, str]:
        # Per-call last_token_usage is the safest local basis. Depending on the
        # Codex build, total_token_usage can include resumed history or work
        # aggregated from related rollouts.
        if self.last_usage_events:
            total = Usage()
            for usage in self.last_usage_events:
                total.add(usage)
            return total, "sum-last-token-usage-events"
        if self.per_turn_usage:
            total = Usage()
            for usage in self.per_turn_usage:
                total.add(usage)
            return total, "derived-from-last-turn-snapshots"
        if self.cumulative_usage_seen:
            return self.cumulative_usage, "cumulative-snapshot-upper-bound"
        return Usage(), "unavailable"


def classify_tool(name: str, server: str | None = None) -> str:
    lowered = name.lower()
    if server:
        return "mcp"
    if lowered in AGENT_TOOL_NAMES or "agent" in lowered and lowered in {"agent", "wait_agent", "spawn_agent"}:
        return "agent"
    if lowered in SHELL_TOOL_NAMES or "shell" in lowered or lowered.startswith("exec_"):
        return "shell"
    if lowered in PATCH_TOOL_NAMES or "patch" in lowered or "file_change" in lowered:
        return "file-change"
    if "web_search" in lowered or lowered in {"search", "search_query"}:
        return "web-search"
    if lowered.startswith("browser_") or lowered in {"click", "take_screenshot", "evaluate_script", "navigate_page"}:
        return "browser"
    return "other"


def call_id_from(payload: Mapping[str, Any], fallback: str) -> str:
    for key in ("call_id", "callId", "id", "tool_call_id", "toolCallId"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def success_from(payload: Mapping[str, Any]) -> bool | None:
    if isinstance(payload.get("success"), bool):
        return bool(payload["success"])
    if payload.get("error") not in (None, "", False):
        return False
    for key in ("exit_code", "exitCode"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return int(value) == 0
    result = payload.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("is_error"), bool):
            return not result["is_error"]
        if result.get("error") not in (None, "", False):
            return False
    return None


def extract_skill_paths(value: Any) -> list[str]:
    candidates: list[str] = []
    if isinstance(value, str):
        if "SKILL.md" in value or "skill.md" in value:
            candidates.extend(match.group(1) for match in SKILL_MD_RE.finditer(value + " "))
    elif isinstance(value, dict):
        for item in value.values():
            candidates.extend(extract_skill_paths(item))
    elif isinstance(value, list):
        for item in value:
            candidates.extend(extract_skill_paths(item))
    return candidates


def parse_rollout(path: Path, mcp_tool_map: Mapping[str, tuple[str, str]]) -> SessionRecord:
    record = SessionRecord(path=str(path))
    try:
        record.file_size = path.stat().st_size
    except OSError:
        pass

    for line_number, obj in safe_jsonl(path):
        record.records += 1
        timestamp = parse_ts(obj.get("timestamp") or obj.get("ts"))
        record.update_ts(timestamp)
        top_type = str(obj.get("type") or "")
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        fallback_id = f"{path.name}:{line_number}:{top_type}"

        if top_type == "session_meta":
            record.session_id = str(
                payload.get("id") or payload.get("session_id") or payload.get("thread_id")
                or payload.get("conversation_id") or record.session_id
            )
            record.cwd = str(payload.get("cwd")) if payload.get("cwd") else record.cwd
            record.originator = str(payload.get("originator")) if payload.get("originator") else record.originator
            record.cli_version = str(payload.get("cli_version")) if payload.get("cli_version") else record.cli_version
            record.model_provider = str(payload.get("model_provider")) if payload.get("model_provider") else record.model_provider
            direct_model = model_value(payload.get("model"))
            if direct_model:
                record.models[direct_model] += 1
            record.parent_thread_id = str(recursive_find_first(payload, {"parent_thread_id", "parentThreadId"}) or record.parent_thread_id or "") or None
            record.agent_role = str(recursive_find_first(payload, {"agent_role", "agentRole", "role"}) or record.agent_role or "") or None
            record.agent_nickname = str(recursive_find_first(payload, {"agent_nickname", "agentNickname", "nickname"}) or record.agent_nickname or "") or None
            source = payload.get("source")
            if isinstance(source, str):
                record.source_kind = source
            elif isinstance(source, dict):
                record.source_kind = str(source.get("type") or source.get("kind") or next(iter(source), "")) or record.source_kind

        elif top_type == "turn_context":
            model = model_value(payload.get("model"))
            effort = payload.get("effort") or payload.get("reasoning_effort") or payload.get("model_reasoning_effort")
            tier = payload.get("service_tier")
            collaboration = scalar_name(payload.get("collaboration_mode") or payload.get("multi_agent_mode"))
            if model:
                record.models[model] += 1
            if isinstance(effort, str) and effort:
                record.efforts[effort] += 1
            if isinstance(tier, str) and tier:
                record.service_tiers[tier] += 1
            if collaboration:
                record.collaboration_modes[collaboration] += 1
            if payload.get("cwd") and not record.cwd:
                record.cwd = str(payload["cwd"])

        elif top_type == "event_msg":
            event_type = str(payload.get("type") or "")
            if event_type == "user_message":
                message = payload.get("message") or payload.get("text")
                if isinstance(message, str):
                    record.add_prompt(message, "event_msg.user_message", timestamp)
                for name, _path in content_items(payload.get("content"))[1]:
                    record.add_skill(name, "structured-user-skill")

            elif event_type in {"task_started", "turn_started", "turn_start"}:
                record.turns_started += 1
                record.active_turn_start = timestamp or record.active_turn_start
                collaboration = scalar_name(payload.get("collaboration_mode_kind") or payload.get("collaboration_mode"))
                if collaboration:
                    record.collaboration_modes[collaboration] += 1

            elif event_type in {"task_complete", "turn_complete", "turn_completed"}:
                record.close_turn(timestamp, aborted=False)

            elif event_type in {"turn_aborted", "task_aborted", "turn_failed"}:
                record.close_turn(timestamp, aborted=True)

            elif event_type == "thread_settings_applied":
                settings = payload.get("thread_settings") if isinstance(payload.get("thread_settings"), dict) else payload
                model = model_value(settings.get("model"))
                effort = settings.get("reasoning_effort") or settings.get("model_reasoning_effort")
                tier = settings.get("service_tier")
                collaboration = scalar_name(settings.get("collaboration_mode"))
                if model:
                    record.models[model] += 1
                if isinstance(effort, str) and effort:
                    record.efforts[effort] += 1
                if isinstance(tier, str) and tier:
                    record.service_tiers[tier] += 1
                if collaboration:
                    record.collaboration_modes[collaboration] += 1

            elif event_type == "token_count":
                record.token_events += 1
                info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                cumulative_raw = info.get("total_token_usage") or payload.get("total_token_usage")
                last_raw = info.get("last_token_usage") or payload.get("last_token_usage") or payload.get("usage")
                cumulative = Usage.from_mapping(cumulative_raw if isinstance(cumulative_raw, dict) else {})
                last = Usage.from_mapping(last_raw if isinstance(last_raw, dict) else {})
                # Prefer per-call usage. Keep cumulative only as a fallback/upper bound.
                if cumulative.total_tokens:
                    if record.cumulative_usage_first is None:
                        record.cumulative_usage_first = cumulative
                    if cumulative.total_tokens > record.cumulative_usage.total_tokens:
                        record.cumulative_usage = cumulative
                    record.cumulative_usage_seen = True
                if last.total_tokens:
                    record.last_usage_events.append(last)
                    record.current_last_usage = last
                limits = payload.get("rate_limits") or info.get("rate_limit_snapshot") or info.get("rate_limits")
                if isinstance(limits, dict):
                    record.latest_rate_limits = redact_obj(limits)

            elif event_type in {"mcp_tool_call_begin", "mcp_tool_call_start"}:
                invocation = payload.get("invocation") if isinstance(payload.get("invocation"), dict) else payload
                server = invocation.get("server") or invocation.get("server_name")
                tool = invocation.get("tool") or invocation.get("tool_name") or invocation.get("name")
                call_id = call_id_from(payload, fallback_id)
                normalized_server = canonical_mcp_server(str(server)) if server else None
                normalized_tool = canonical_mcp_tool(str(tool)) if tool else None
                display = f"{normalized_server}::{normalized_tool}" if normalized_server and normalized_tool else str(normalized_tool or "mcp-tool")
                call = record.get_tool(call_id, display, event_type)
                call.server = normalized_server or call.server
                call.tool = normalized_tool or call.tool
                call.name = f"{call.server}::{call.tool}" if call.server and call.tool else call.name
                call.category = "mcp"
                call.started_at = timestamp or call.started_at

            elif event_type in {"mcp_tool_call_end", "mcp_tool_call_complete"}:
                invocation = payload.get("invocation") if isinstance(payload.get("invocation"), dict) else payload
                server = invocation.get("server") or invocation.get("server_name")
                tool = invocation.get("tool") or invocation.get("tool_name") or invocation.get("name")
                call_id = call_id_from(payload, fallback_id)
                normalized_server = canonical_mcp_server(str(server)) if server else None
                normalized_tool = canonical_mcp_tool(str(tool)) if tool else None
                display = f"{normalized_server}::{normalized_tool}" if normalized_server and normalized_tool else str(normalized_tool or "mcp-tool")
                call = record.get_tool(call_id, display, event_type)
                call.server = normalized_server or call.server
                call.tool = normalized_tool or call.tool
                call.name = f"{call.server}::{call.tool}" if call.server and call.tool else call.name
                call.category = "mcp"
                call.ended_at = timestamp or call.ended_at
                result = success_from(payload)
                if result is not None:
                    call.success = result

            elif event_type in {"exec_command_begin", "command_execution_begin"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "exec_command", event_type)
                call.category = "shell"
                call.started_at = timestamp or call.started_at

            elif event_type in {"exec_command_end", "command_execution_complete"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "exec_command", event_type)
                call.category = "shell"
                call.ended_at = timestamp or call.ended_at
                result = success_from(payload)
                if result is not None:
                    call.success = result

            elif event_type in {"web_search_begin", "web_search_start"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "web_search", event_type)
                call.category = "web-search"
                call.started_at = timestamp or call.started_at

            elif event_type in {"web_search_end", "web_search_complete"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "web_search", event_type)
                call.category = "web-search"
                call.ended_at = timestamp or call.ended_at
                result = success_from(payload)
                if result is not None:
                    call.success = result

            elif event_type in {"patch_apply_begin", "apply_patch_begin"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "apply_patch", event_type)
                call.category = "file-change"
                call.started_at = timestamp or call.started_at

            elif event_type in {"patch_apply_end", "apply_patch_end"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "apply_patch", event_type)
                call.category = "file-change"
                call.ended_at = timestamp or call.ended_at
                result = success_from(payload)
                if result is not None:
                    call.success = result

            elif "compact" in event_type:
                record.compactions += 1

        elif top_type == "response_item":
            item_type = str(payload.get("type") or "")
            role = str(payload.get("role") or "").lower()
            if item_type == "message" and role == "user":
                texts, selected_skills = content_items(payload.get("content"))
                for text in texts:
                    record.add_prompt(text, "response_item.user_message", timestamp)
                for name, _path in selected_skills:
                    record.add_skill(name, "structured-user-skill")

            elif item_type in {"function_call", "custom_tool_call"}:
                name = str(payload.get("name") or payload.get("tool_name") or "unknown")
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, name, f"response_item.{item_type}")
                server: str | None = None
                tool: str | None = None
                match = re.match(r"(?i)^mcp__([^_]+)__(.+)$", name)
                if match:
                    server, tool = match.group(1), match.group(2)
                elif name in mcp_tool_map or canonical_tool_name(name) in mcp_tool_map:
                    mapped = mcp_tool_map.get(name) or mcp_tool_map.get(canonical_tool_name(name))
                    if mapped:
                        server, tool = mapped
                if server:
                    server = canonical_mcp_server(str(server))
                    tool = canonical_mcp_tool(str(tool or name))
                    call.server, call.tool, call.category = server, tool, "mcp"
                    call.name = f"{server}::{tool}"
                else:
                    call.category = classify_tool(name)
                arguments = payload.get("arguments") or payload.get("input")
                for skill_name in extract_skill_paths(arguments):
                    record.add_skill(skill_name, "tool-read-skill-path")

            elif item_type in {"function_call_output", "custom_tool_call_output"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "unknown", f"response_item.{item_type}")
                result = success_from(payload)
                if result is not None:
                    call.success = result

            elif item_type in {"web_search_call", "web_search"}:
                call_id = call_id_from(payload, fallback_id)
                call = record.get_tool(call_id, "web_search", f"response_item.{item_type}")
                call.category = "web-search"

        elif top_type == "compacted":
            record.compactions += 1

    if record.active_turn_start is not None:
        # Do not manufacture a completion. Per-call usage was already collected.
        record.current_last_usage = None

    # If no session id was parsed, the filename still provides a stable file-level identity.
    if record.session_id == "unknown":
        record.session_id = path.stem
        record.warnings.append("session_meta ausente ou ilegível")
    return record


def read_toml(path: Path) -> dict[str, Any]:
    if tomllib is None or not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, tomllib.TOMLDecodeError):
        return {}


def discover_project_configs(cwds: Iterable[str | None], current: Path) -> list[Path]:
    found: set[Path] = set()
    candidates: list[Path] = [current]
    for cwd in cwds:
        if cwd:
            path = Path(cwd).expanduser()
            if path.exists():
                candidates.append(path)
    for start in candidates:
        try:
            start = start.resolve()
        except OSError:
            continue
        for parent in (start, *start.parents):
            config = parent / ".codex" / "config.toml"
            if config.is_file():
                found.add(config)
            if (parent / ".git").exists():
                break
    return sorted(found)


def discover_agents_docs(codex_home: Path, cwds: Iterable[str | None]) -> list[dict[str, Any]]:
    paths: set[Path] = set()
    global_doc = codex_home / "AGENTS.md"
    if global_doc.is_file():
        paths.add(global_doc)
    for cwd in cwds:
        if not cwd:
            continue
        start = Path(cwd).expanduser()
        if not start.exists():
            continue
        for parent in (start, *start.parents):
            doc = parent / "AGENTS.md"
            if doc.is_file():
                paths.add(doc)
            if (parent / ".git").exists():
                break
    result: list[dict[str, Any]] = []
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        flags = []
        lowered = text.lower()
        for label, needle in (
            ("agent-first", "agent-first"),
            ("proactive-agents", "use agents proactively"),
            ("parallel-agents", "launch multiple agents simultaneously"),
            ("mandatory-tdd", "tdd workflow (mandatory)"),
            ("broad-mcp", "use available mcp servers when they can help"),
        ):
            if needle in lowered:
                flags.append(label)
        result.append({
            "path": str(path),
            "lines": len(text.splitlines()),
            "bytes": len(text.encode("utf-8")),
            "flags": flags,
            "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
        })
    return result


def discover_skills(codex_home: Path, cwds: Iterable[str | None], current: Path) -> dict[str, list[str]]:
    roots: set[Path] = {
        codex_home / "skills",
        Path.home() / ".agents" / "skills",
        current / ".agents" / "skills",
        current / ".codex" / "skills",
    }
    for cwd in cwds:
        if not cwd:
            continue
        path = Path(cwd).expanduser()
        if path.exists():
            roots.add(path / ".agents" / "skills")
            roots.add(path / ".codex" / "skills")
    result: defaultdict[str, list[str]] = defaultdict(list)
    for root in roots:
        if not root.exists():
            continue
        for skill_file in root.rglob("SKILL.md"):
            name = skill_file.parent.name
            try:
                head = skill_file.read_text(encoding="utf-8", errors="replace")[:3000]
                front_name = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", head)
                if front_name:
                    name = front_name.group(1).strip()
            except OSError:
                pass
            result[name].append(str(skill_file))
    return dict(sorted(result.items()))


def collect_mcp_servers(configs: Sequence[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source, config in configs:
        servers = config.get("mcp_servers")
        if not isinstance(servers, dict):
            continue
        for name, spec in servers.items():
            normalized_name = canonical_mcp_server(str(name))
            entry = result.setdefault(normalized_name, {
                "sources": [], "enabled_values": [], "enabled_tools": [], "disabled_tools": [],
            })
            entry["sources"].append(source)
            if isinstance(spec, dict):
                if "enabled" in spec:
                    entry["enabled_values"].append(bool(spec.get("enabled")))
                if isinstance(spec.get("enabled_tools"), list):
                    entry["enabled_tools"].extend(str(item) for item in spec["enabled_tools"])
                if isinstance(spec.get("disabled_tools"), list):
                    entry["disabled_tools"].extend(str(item) for item in spec["disabled_tools"])
    return result


def config_inventory(codex_home: Path, project_configs: list[Path]) -> dict[str, Any]:
    global_path = codex_home / "config.toml"
    global_config = read_toml(global_path)
    standalone_profiles: dict[str, Any] = {}
    for path in sorted(codex_home.glob("*.config.toml")):
        if path.name == "config.toml":
            continue
        name = path.name[:-len(".config.toml")]
        standalone_profiles[name] = {"path": str(path), "config": read_toml(path), "format": "standalone-current"}
    nested_profiles: dict[str, Any] = {}
    raw_nested = global_config.get("profiles")
    if isinstance(raw_nested, dict):
        for name, config in raw_nested.items():
            if isinstance(config, dict):
                nested_profiles[str(name)] = {"path": str(global_path), "config": config, "format": "nested-legacy"}
    projects = {str(path): read_toml(path) for path in project_configs}
    config_sources: list[tuple[str, dict[str, Any]]] = [("global", global_config)]
    config_sources.extend((f"profile:{name}", info["config"]) for name, info in standalone_profiles.items())
    config_sources.extend((f"legacy-profile:{name}", info["config"]) for name, info in nested_profiles.items())
    config_sources.extend((f"project:{path}", config) for path, config in projects.items())
    return {
        "global_path": str(global_path),
        "global": redact_obj(global_config),
        "standalone_profiles": {name: {**info, "config": redact_obj(info["config"])} for name, info in standalone_profiles.items()},
        "legacy_nested_profiles": {name: {**info, "config": redact_obj(info["config"])} for name, info in nested_profiles.items()},
        "project_configs": {path: redact_obj(config) for path, config in projects.items()},
        "mcp_servers": collect_mcp_servers(config_sources),
    }


def parse_mcp_verbose(text: str) -> dict[str, list[str]]:
    servers: defaultdict[str, list[str]] = defaultdict(list)
    current: str | None = None
    collecting = False
    tool_buffer = ""

    def flush() -> None:
        nonlocal tool_buffer
        if current and tool_buffer:
            for item in tool_buffer.split(","):
                name = item.strip().rstrip(".")
                if name and name not in servers[current]:
                    servers[current].append(name)
        tool_buffer = ""

    for raw in text.splitlines():
        server_match = re.match(r"^\s{2}[•*-]\s+([^:]+?)\s*$", raw)
        if server_match and not raw.startswith("    "):
            flush()
            current = server_match.group(1).strip()
            collecting = False
            continue
        if current and re.match(r"^\s{4}[•*-]\s+Tools:\s*", raw):
            flush()
            tool_buffer = re.split(r"Tools:\s*", raw, maxsplit=1)[1]
            collecting = True
            continue
        if collecting:
            if re.match(r"^\s{4}[•*-]\s+(Auth|Resources|Resource templates):", raw):
                flush()
                collecting = False
            elif raw.strip():
                tool_buffer += " " + raw.strip()
    flush()
    return dict(servers)


def canonical_tool_name(name: str) -> str:
    return re.sub(r"[-.]", "_", name.strip().lower())


def canonical_mcp_server(name: str) -> str:
    value = re.sub(r"[\s_]+", "-", name.strip().lower())
    return re.sub(r"-+", "-", value).strip("-")


def canonical_mcp_tool(name: str) -> str:
    value = name.strip()
    if not value:
        return value
    if "." not in value:
        value = value.replace("_", "-")
    return value.lower()


def load_mcp_inventory(path: Path | None, codex_home: Path) -> tuple[dict[str, list[str]], dict[str, tuple[str, str]]]:
    candidate = path
    if candidate is None:
        default = codex_home / "usage-data" / "mcp-verbose.txt"
        if default.is_file():
            candidate = default
    if candidate is None or not candidate.is_file():
        return {}, {}
    try:
        servers = parse_mcp_verbose(candidate.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}, {}
    normalized_servers: dict[str, list[str]] = {}
    reverse: defaultdict[str, set[tuple[str, str]]] = defaultdict(set)
    for raw_server, tools in servers.items():
        server = canonical_mcp_server(raw_server)
        normalized_tools = normalized_servers.setdefault(server, [])
        for raw_tool in tools:
            tool = canonical_mcp_tool(raw_tool)
            if tool not in normalized_tools:
                normalized_tools.append(tool)
            pair = (server, tool)
            for key in {raw_tool, canonical_tool_name(raw_tool), tool, canonical_tool_name(tool)}:
                reverse[key].add(pair)
    unique: dict[str, tuple[str, str]] = {}
    for tool_key, pairs in reverse.items():
        if len(pairs) == 1:
            unique[tool_key] = next(iter(pairs))
    return normalized_servers, unique


def deduplicate_sessions(sessions: list[SessionRecord]) -> tuple[list[SessionRecord], list[dict[str, Any]]]:
    groups: defaultdict[str, list[SessionRecord]] = defaultdict(list)
    for session in sessions:
        groups[session.session_id].append(session)
    selected: list[SessionRecord] = []
    duplicates: list[dict[str, Any]] = []
    for session_id, group in groups.items():
        if len(group) == 1:
            selected.append(group[0])
            continue
        # Archived/current copies usually contain the same rollout. Keep the richest copy.
        winner = max(group, key=lambda item: (item.records, item.file_size, item.last_ts or datetime.min.replace(tzinfo=UTC)))
        selected.append(winner)
        duplicates.append({
            "session_id": session_id,
            "kept": winner.path,
            "ignored": [item.path for item in group if item is not winner],
            "reason": "same session_id; kept rollout with most records/bytes",
        })
    selected.sort(key=lambda item: item.first_ts or datetime.min.replace(tzinfo=UTC))
    return selected, duplicates


def profile_signature(config: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, alias in (("model", "model"), ("model_reasoning_effort", "effort"), ("service_tier", "tier")):
        value = config.get(key)
        if isinstance(value, str) and value:
            result[alias] = value
    return result


def load_profile_ledger(codex_home: Path, since: datetime | None) -> list[dict[str, Any]]:
    path = codex_home / "usage-data" / "profile-ledger.jsonl"
    events: list[dict[str, Any]] = []
    for _line, obj in safe_jsonl(path):
        timestamp = parse_ts(obj.get("timestamp"))
        if since and timestamp and timestamp < since:
            continue
        obj["_timestamp"] = timestamp
        events.append(obj)
    return events


def assign_profiles(sessions: list[SessionRecord], inventory: Mapping[str, Any], ledger: list[dict[str, Any]]) -> None:
    profiles: dict[str, Mapping[str, Any]] = {}
    for name, info in inventory.get("standalone_profiles", {}).items():
        profiles[name] = info.get("config", {})
    for name, info in inventory.get("legacy_nested_profiles", {}).items():
        profiles[f"legacy:{name}"] = info.get("config", {})
    signatures = {name: profile_signature(config) for name, config in profiles.items()}

    for session in sessions:
        best: tuple[float, dict[str, Any]] | None = None
        for event in ledger:
            event_ts = event.get("_timestamp")
            if not isinstance(event_ts, datetime) or not session.first_ts:
                continue
            delta = abs((session.first_ts - event_ts).total_seconds())
            if delta > 240:
                continue
            event_cwd = event.get("cwd")
            if event_cwd and session.cwd and os.path.normcase(str(event_cwd)) != os.path.normcase(str(session.cwd)):
                continue
            if best is None or delta < best[0]:
                best = (delta, event)
        if best:
            session.profile_name = str(best[1].get("profile") or "default")
            session.profile_confidence = "recorded-by-wrapper"
            continue

        observed = {
            "model": session.dominant_model(),
            "effort": session.dominant_effort(),
            "tier": session.dominant_tier(),
        }
        matches = [
            name for name, signature in signatures.items()
            if signature and all(observed.get(key) == value for key, value in signature.items())
        ]
        if len(matches) == 1:
            session.profile_name = matches[0]
            session.profile_confidence = "inferred-from-resolved-settings"
        elif len(matches) > 1:
            session.profile_name = " | ".join(sorted(matches))
            session.profile_confidence = "ambiguous-inference"
        else:
            session.profile_name = "default/override/unknown"
            session.profile_confidence = "unknown"


def model_rank(name: str) -> int:
    lowered = name.lower()
    if any(token in lowered for token in ("luna", "mini", "nano", "spark", "small")):
        return 1
    if "terra" in lowered:
        return 2
    if any(token in lowered for token in ("sol", "pro", "max")):
        return 4
    return 3


def model_generation(name: str) -> tuple[int, int] | None:
    match = MODEL_VERSION_RE.search(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def all_model_candidates(sessions: list[SessionRecord], inventory: Mapping[str, Any]) -> list[str]:
    values: set[str] = {session.dominant_model() for session in sessions if session.dominant_model()}
    global_model = model_value(inventory.get("global", {}).get("model"))
    if global_model:
        values.add(global_model)
    for collection in ("standalone_profiles", "legacy_nested_profiles"):
        for info in inventory.get(collection, {}).values():
            candidate = model_value(info.get("config", {}).get("model"))
            if candidate:
                values.add(candidate)
    return sorted(values, key=lambda value: (model_rank(value), value))


def select_profile_models(sessions: list[SessionRecord], inventory: Mapping[str, Any]) -> dict[str, Any]:
    candidates = all_model_candidates(sessions, inventory)
    if not candidates:
        return {"daily": None, "volume": None, "deep": None, "subagent": None, "generation": None, "historical_ignored": []}

    generations = [model_generation(name) for name in candidates if model_generation(name) is not None]
    current_generation = max(generations) if generations else None
    current = [name for name in candidates if current_generation is None or model_generation(name) == current_generation]
    historical = [name for name in candidates if name not in current]

    root_counts = Counter(
        session.dominant_model() for session in sessions
        if not session.is_subagent() and session.dominant_model() in current
    )

    def first_matching(tokens: Sequence[str], pool: Sequence[str]) -> str | None:
        for token in tokens:
            match = next((name for name in pool if token in name.lower()), None)
            if match:
                return match
        return None

    high_model = first_matching(("sol", "pro", "max"), current)
    if not high_model:
        high_model = max(current, key=lambda name: (model_rank(name), root_counts[name], name))

    daily_model = root_counts.most_common(1)[0][0] if root_counts else high_model
    # Never select an older historical model merely because it looks cheaper.
    # Prefer the economical member of the newest observed/configured generation.
    low_model = first_matching(("luna", "terra", "mini", "nano", "spark", "small"), current)
    if not low_model:
        low_model = min(current, key=lambda name: (model_rank(name), -root_counts[name], name))

    return {
        "daily": daily_model,
        "volume": low_model,
        "deep": high_model,
        "subagent": low_model,
        "generation": f"{current_generation[0]}.{current_generation[1]}" if current_generation else None,
        "candidates_current_generation": current,
        "historical_ignored": historical,
    }


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_profile_files(
    out_dir: Path,
    sessions: list[SessionRecord],
    inventory: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    selection = select_profile_models(sessions, inventory)
    if not selection.get("daily"):
        return {}
    low_model = str(selection["volume"])
    high_model = str(selection["deep"])
    daily_model = str(selection["daily"])
    subagent_model = str(selection["subagent"])
    configured_mcp = sorted(inventory.get("mcp_servers", {}).keys())

    def mcp_blocks(enabled: set[str]) -> list[str]:
        lines: list[str] = []
        for server in configured_mcp:
            lines.extend(["", f"[mcp_servers.{server}]", f"enabled = {'true' if server in enabled else 'false'}"])
        return lines

    profiles: dict[str, dict[str, Any]] = {}
    base_daily = [
        f"model = {toml_string(daily_model)}",
        'model_reasoning_effort = "medium"',
        'plan_mode_reasoning_effort = "high"',
        'model_reasoning_summary = "concise"',
        'model_verbosity = "low"',
        'web_search = "disabled"',
        "",
        "[features]",
        "multi_agent = false",
        "fast_mode = false",
        "",
        "[agents]",
        "enabled = false",
    ] + mcp_blocks(set())
    profiles["daily.config.toml"] = {
        "purpose": "Tarefas cotidianas com um único agente e ferramentas externas desligadas.",
        "content": "\n".join(base_daily) + "\n",
    }

    volume_lines = [
        f"model = {toml_string(low_model)}",
        'model_reasoning_effort = "low"',
        'plan_mode_reasoning_effort = "medium"',
        'model_reasoning_summary = "concise"',
        'model_verbosity = "low"',
        'web_search = "disabled"',
        "",
        "[features]",
        "multi_agent = false",
        "fast_mode = false",
        "",
        "[agents]",
        "enabled = false",
    ] + mcp_blocks(set())
    profiles["volume.config.toml"] = {
        "purpose": "Alterações mecânicas, testes, documentação e planos já definidos.",
        "content": "\n".join(volume_lines) + "\n",
    }

    deep_lines = [
        f"model = {toml_string(high_model)}",
        'model_reasoning_effort = "xhigh"',
        'plan_mode_reasoning_effort = "xhigh"',
        'model_reasoning_summary = "concise"',
        'model_verbosity = "medium"',
        'web_search = "disabled"',
        "",
        "[features]",
        "multi_agent = false",
        "fast_mode = false",
        "",
        "[agents]",
        "enabled = false",
    ] + mcp_blocks(set())
    profiles["deep.config.toml"] = {
        "purpose": "Debugging difícil e arquitetura, sem delegação automática.",
        "content": "\n".join(deep_lines) + "\n",
    }

    parallel_lines = [
        f"model = {toml_string(high_model)}",
        'model_reasoning_effort = "high"',
        'plan_mode_reasoning_effort = "high"',
        'model_reasoning_summary = "concise"',
        'model_verbosity = "low"',
        'web_search = "disabled"',
        "",
        "[features]",
        "multi_agent = true",
        "fast_mode = false",
        "",
        "[agents]",
        "enabled = true",
        "max_concurrent_threads_per_session = 2",
        "max_depth = 1",
        f"default_subagent_model = {toml_string(subagent_model)}",
        'default_subagent_reasoning_effort = "medium"',
    ] + mcp_blocks(set())
    profiles["parallel.config.toml"] = {
        "purpose": "Tarefas realmente paralelizáveis com orçamento explícito de dois subagentes.",
        "content": "\n".join(parallel_lines) + "\n",
    }

    specialized = {
        "research.config.toml": ({"context7", "exa"}, "Pesquisa de documentação e fontes externas."),
        "browser.config.toml": ({"playwright"}, "Automação funcional do navegador."),
        "performance.config.toml": ({"chrome-devtools"}, "Lighthouse, traces, heap e diagnóstico de runtime."),
        "deploy.config.toml": ({"vercel"}, "Leitura e operações explícitas relacionadas à Vercel."),
        "remote-git.config.toml": ({"github"}, "Issues, pull requests e operações remotas no GitHub."),
    }
    configured_set = set(configured_mcp)
    for filename, (servers, purpose) in specialized.items():
        enabled = servers & configured_set
        if not enabled:
            continue
        lines = [
            f"model = {toml_string(daily_model)}",
            'model_reasoning_effort = "high"',
            'plan_mode_reasoning_effort = "high"',
            'model_reasoning_summary = "concise"',
            'model_verbosity = "low"',
            'web_search = "live"' if filename == 'research.config.toml' else 'web_search = "disabled"',
            "",
            "[features]",
            "multi_agent = false",
            "fast_mode = false",
            "",
            "[agents]",
            "enabled = false",
        ] + mcp_blocks(enabled)
        profiles[filename] = {"purpose": purpose, "content": "\n".join(lines) + "\n"}

    target = out_dir / "suggested-profiles"
    target.mkdir(parents=True, exist_ok=True)
    for filename, spec in profiles.items():
        (target / filename).write_text(spec["content"], encoding="utf-8")
    return profiles


def aggregate_usage(sessions: Iterable[SessionRecord]) -> tuple[Usage, int, Counter[str]]:
    total = Usage()
    covered = 0
    sources: Counter[str] = Counter()
    for session in sessions:
        usage, source = session.usage()
        sources[source] += 1
        if source != "unavailable":
            covered += 1
            total.add(usage)
    return total, covered, sources


def build_recommendations(
    sessions: list[SessionRecord],
    inventory: Mapping[str, Any],
    agents_docs: list[dict[str, Any]],
    installed_skills: Mapping[str, list[str]],
    template_counts: Counter[str],
    mcp_verbose_servers: Mapping[str, list[str]],
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []
    global_config = inventory.get("global", {})
    features = global_config.get("features") if isinstance(global_config.get("features"), dict) else {}
    agents = global_config.get("agents") if isinstance(global_config.get("agents"), dict) else {}

    if features.get("multi_agent") is True or agents.get("enabled") is True:
        threads = agents.get("max_concurrent_threads_per_session") or agents.get("max_threads") or "padrão"
        recommendations.append({
            "priority": "critical",
            "type": "global-multi-agent",
            "evidence": f"Multi-agent está habilitado globalmente; limite de threads: {threads}.",
            "action": "Desative-o no config global e mantenha-o apenas em parallel.config.toml.",
        })

    if isinstance(agents.get("max_threads"), int) and agents["max_threads"] > 2:
        recommendations.append({
            "priority": "high",
            "type": "agent-thread-budget",
            "evidence": f"agents.max_threads={agents['max_threads']}.",
            "action": "Use max_concurrent_threads_per_session=2 no profile paralelo e nenhuma thread no profile diário.",
        })

    if str(global_config.get("web_search") or "").lower() == "live":
        recommendations.append({
            "priority": "high",
            "type": "global-web-search",
            "evidence": "web_search=live está configurado globalmente.",
            "action": "Troque o padrão para disabled e deixe live somente no profile research.",
        })

    persistent = str(global_config.get("persistent_instructions") or "")
    if "mcp" in persistent.lower() and "when they can help" in persistent.lower():
        recommendations.append({
            "priority": "high",
            "type": "broad-persistent-instruction",
            "evidence": "A instrução persistente incentiva MCPs em todas as tarefas.",
            "action": "Exija necessidade explícita da tarefa e o menor conjunto suficiente de ferramentas.",
        })

    if inventory.get("legacy_nested_profiles"):
        names = ", ".join(sorted(inventory["legacy_nested_profiles"]))
        recommendations.append({
            "priority": "high",
            "type": "legacy-profile-format",
            "evidence": f"Profiles aninhados detectados: {names}.",
            "action": "Migre-os para arquivos separados <nome>.config.toml no CODEX_HOME.",
        })

    heavy_docs = [doc for doc in agents_docs if doc["lines"] > 160 or doc["bytes"] > 20_000 or doc["flags"]]
    if heavy_docs:
        evidence = "; ".join(f"{Path(doc['path']).name}: {doc['lines']} linhas, flags={','.join(doc['flags']) or 'tamanho'}" for doc in heavy_docs[:8])
        recommendations.append({
            "priority": "critical" if any("proactive-agents" in doc["flags"] for doc in heavy_docs) else "high",
            "type": "agents-context-overhead",
            "evidence": evidence,
            "action": "Reduza o AGENTS global a regras universais e mova catálogos/workflows para skills ou AGENTS por projeto.",
        })

    root_sessions_for_effort = [session for session in sessions if not session.is_subagent()]
    elevated_root = [session for session in root_sessions_for_effort if session.dominant_effort() in {"high", "xhigh", "max", "ultra"}]
    high_simple = [session for session in elevated_root if session.intent() in SIMPLE_INTENTS]
    if elevated_root:
        recommendations.append({
            "priority": "high",
            "type": "effort-routing",
            "evidence": f"{len(elevated_root)}/{len(root_sessions_for_effort)} sessões principais usaram high/xhigh/max/ultra; {len(high_simple)} eram de finalidade previsível.",
            "action": "Use daily/volume para tarefas claras e escale para deep somente após evidência de dificuldade.",
        })

    agent_calls = sum(1 for session in sessions for call in session.tool_calls.values() if call.category == "agent")
    if agent_calls:
        recommendations.append({
            "priority": "critical" if agent_calls > max(20, len(sessions)) else "high",
            "type": "agent-call-volume",
            "evidence": f"{agent_calls} chamadas únicas de ferramentas de agente foram detectadas.",
            "action": "Meça novamente após desativar multi-agent global e limitar o profile parallel a duas threads.",
        })

    repeated = [(template, count) for template, count in template_counts.items() if count >= 3 and len(template) >= 35]
    if repeated:
        repeated.sort(key=lambda item: (-item[1], item[0]))
        recommendations.append({
            "priority": "medium",
            "type": "repeated-prompt-to-skill",
            "evidence": f"{len(repeated)} templates substantivos se repetem 3+ vezes; maior frequência: {repeated[0][1]}.",
            "action": "Converta os padrões estáveis em skills parametrizadas; não transforme prompts de controle em skills.",
        })

    configured_mcp = set(inventory.get("mcp_servers", {}))
    used_mcp = Counter(
        call.server for session in sessions for call in session.tool_calls.values()
        if call.category == "mcp" and call.server
    )
    mcp_calls = sum(used_mcp.values())
    if configured_mcp and mcp_calls:
        unused = sorted(configured_mcp - set(used_mcp))
        if unused:
            recommendations.append({
                "priority": "medium",
                "type": "unused-mcp",
                "evidence": f"MCPs configurados sem chamada identificada no período: {', '.join(unused)}.",
                "action": "Desabilite-os no daily; confirme com uma janela maior antes de removê-los definitivamente.",
            })
    elif configured_mcp and not mcp_calls:
        recommendations.append({
            "priority": "informational",
            "type": "mcp-telemetry-coverage",
            "evidence": "Há MCPs configurados, mas nenhuma chamada pôde ser atribuída com confiança.",
            "action": "Salve a saída de /mcp verbose em ~/.codex/usage-data/mcp-verbose.txt e gere o relatório novamente.",
        })

    if {"playwright", "chrome-devtools"}.issubset(configured_mcp):
        recommendations.append({
            "priority": "medium",
            "type": "browser-tool-overlap",
            "evidence": "Playwright e Chrome DevTools estão disponíveis no mesmo baseline.",
            "action": "Use browser.config.toml para Playwright e performance.config.toml para Chrome DevTools.",
        })

    if "sequential-thinking" in configured_mcp:
        recommendations.append({
            "priority": "medium",
            "type": "sequential-thinking-overlap",
            "evidence": "Sequential Thinking está configurado junto a modelos com reasoning effort.",
            "action": "Deixe-o desabilitado no daily e valide ganho mensurável antes de habilitar em outro profile.",
        })

    root_sessions = [session for session in sessions if not session.is_subagent()]
    _, covered, _ = aggregate_usage(root_sessions)
    if root_sessions and covered / len(root_sessions) < 0.8:
        recommendations.append({
            "priority": "informational",
            "type": "token-telemetry-coverage",
            "evidence": f"Tokens locais disponíveis em {covered}/{len(root_sessions)} sessões principais.",
            "action": "Interprete os tokens como amostra local, não como fatura ou consumo integral da assinatura.",
        })

    unused_skills = [name for name in installed_skills if not any(name in session.skills for session in sessions)]
    if unused_skills:
        recommendations.append({
            "priority": "low",
            "type": "skill-inventory",
            "evidence": f"{len(unused_skills)} skills instaladas sem evidência estruturada de uso no período.",
            "action": "Não remova automaticamente; revise por projeto, porque algumas ativações antigas podem não gerar evento dedicado.",
        })

    if not recommendations:
        recommendations.append({
            "priority": "low", "type": "no-strong-signal",
            "evidence": "Nenhum limiar automático foi atingido.",
            "action": "Aumente a janela e compare por projeto antes de alterar configurações.",
        })
    return recommendations


def serialize_session(session: SessionRecord, full_prompts: bool) -> dict[str, Any]:
    usage, usage_source = session.usage()
    tools = Counter(call.name for call in session.tool_calls.values())
    categories = Counter(call.category for call in session.tool_calls.values())
    mcp_servers = Counter(call.server for call in session.tool_calls.values() if call.server)
    mcp_tools = Counter(f"{call.server}::{call.tool}" for call in session.tool_calls.values() if call.server and call.tool)
    failures = sum(call.success is False for call in session.tool_calls.values())
    return {
        "path": session.path,
        "file_size": session.file_size,
        "records": session.records,
        "session_id": session.session_id,
        "cwd": session.cwd,
        "originator": session.originator,
        "cli_version": session.cli_version,
        "model_provider": session.model_provider,
        "parent_thread_id": session.parent_thread_id,
        "agent_role": session.agent_role,
        "agent_nickname": session.agent_nickname,
        "source_kind": session.source_kind,
        "is_subagent": session.is_subagent(),
        "first_timestamp": session.first_ts.isoformat() if session.first_ts else None,
        "last_timestamp": session.last_ts.isoformat() if session.last_ts else None,
        "duration_ms": session.duration_ms(),
        "active_turn_duration_ms": session.active_turn_duration_ms,
        "turns": session.turns(),
        "turns_started": session.turns_started,
        "turns_completed": session.turns_completed,
        "turns_aborted": session.turns_aborted,
        "dominant_model": session.dominant_model(),
        "dominant_effort": session.dominant_effort(),
        "dominant_service_tier": session.dominant_tier(),
        "models": dict(session.models),
        "efforts": dict(session.efforts),
        "service_tiers": dict(session.service_tiers),
        "collaboration_modes": dict(session.collaboration_modes),
        "profile": session.profile_name,
        "profile_confidence": session.profile_confidence,
        "intent_heuristic": session.intent(),
        "objective_heuristic": session.objective(),
        "usage": usage.as_dict(),
        "usage_source": usage_source,
        "token_events": session.token_events,
        "latest_rate_limits": session.latest_rate_limits,
        "tools": dict(tools),
        "tool_categories": dict(categories),
        "tool_details": [
            {
                "call_id": call.call_id, "name": call.name, "category": call.category,
                "server": call.server, "tool": call.tool, "success": call.success,
                "sources": sorted(call.sources),
                "started_at": call.started_at.isoformat() if call.started_at else None,
                "ended_at": call.ended_at.isoformat() if call.ended_at else None,
            }
            for call in session.tool_calls.values()
        ],
        "mcp_servers": dict(mcp_servers),
        "mcp_tools": dict(mcp_tools),
        "tool_failures": failures,
        "skills": {name: {"count": use.count, "evidence": sorted(use.evidence)} for name, use in session.skills.items()},
        "excluded_messages": dict(session.excluded_messages),
        "compactions": session.compactions,
        "warnings": session.warnings,
        "prompts": [
            {
                "timestamp": prompt.timestamp,
                "source": prompt.source,
                "exact_id": prompt.exact_id,
                "template": prompt.template,
                "intent_heuristic": prompt.intent,
                "objective_heuristic": prompt.objective,
                "control": prompt.control,
                **({"text": prompt.text} if full_prompts else {"text_preview": objective_preview(prompt.text, 180)}),
            }
            for prompt in session.prompts
        ],
    }


def format_int(value: float | None) -> str:
    return f"{int(value or 0):,}".replace(",", ".")


def md_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> str:
    rows = list(rows)
    if not rows:
        return "Nenhum dado detectado."
    def cell(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")
    output = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(output)


def write_outputs(report: dict[str, Any], out_dir: Path, top: int) -> None:
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    breakdowns = report["breakdowns"]
    coverage = report["coverage"]

    markdown: list[str] = [
        "# Codex Insights — relatório local corrigido",
        "",
        f"Gerado em: `{report['generated_at']}`  ",
        f"Janela: `{coverage['since'] or 'todo o histórico disponível'}` até agora  ",
        f"Sessões principais: **{summary['root_sessions']}**; subagentes: **{summary['subagent_sessions']}**; prompts humanos: **{summary['human_prompts']}**.",
        "",
        "> **Escopo da medição:** os valores representam tokens processados nas chamadas observadas. Eles não são cobrança, créditos nem equivalência direta da cota semanal. Sessões principais e subagentes são apresentados separadamente.",
        "",
        "## Resumo executivo",
        "",
        md_table(["Métrica", "Sessões principais", "Subagentes", "Soma bruta dos rollouts**"], [
            ("Sessões", summary["root_sessions"], summary["subagent_sessions"], summary["sessions"]),
            ("Tokens processados observados*", format_int(summary["usage_root"]["total_tokens"]), format_int(summary["usage_subagents"]["total_tokens"]), format_int(summary["usage_all"]["total_tokens"])),
            ("Eventos de uso do modelo", summary["model_usage_events_root"], summary["model_usage_events_subagents"], summary["model_usage_events_all"]),
            ("Input tokens", format_int(summary["usage_root"]["input_tokens"]), format_int(summary["usage_subagents"]["input_tokens"]), format_int(summary["usage_all"]["input_tokens"])),
            ("Input não cacheado", format_int(summary["uncached_input_root"]), format_int(summary["uncached_input_subagents"]), format_int(summary["uncached_input_all"])),
            ("Cached input", format_int(summary["usage_root"]["cached_input_tokens"]), format_int(summary["usage_subagents"]["cached_input_tokens"]), format_int(summary["usage_all"]["cached_input_tokens"])),
            ("Output tokens", format_int(summary["usage_root"]["output_tokens"]), format_int(summary["usage_subagents"]["output_tokens"]), format_int(summary["usage_all"]["output_tokens"])),
            ("Reasoning output*", format_int(summary["usage_root"]["reasoning_output_tokens"]), format_int(summary["usage_subagents"]["reasoning_output_tokens"]), format_int(summary["usage_all"]["reasoning_output_tokens"])),
            ("Cobertura de tokens", f"{summary['token_covered_root']}/{summary['root_sessions']}", f"{summary['token_covered_subagents']}/{summary['subagent_sessions']}", f"{summary['token_covered_all']}/{summary['sessions']}"),
            ("Turnos detectados", summary["turns_root"], summary["turns_subagents"], summary["turns_all"]),
            ("Tool calls únicas", summary["tool_calls_root"], summary["tool_calls_subagents"], summary["tool_calls_all"]),
            ("Soma das durações de rollout", f"{summary['duration_root_ms']/60000:.1f} min", f"{summary['duration_subagents_ms']/60000:.1f} min", f"{summary['duration_all_ms']/60000:.1f} min"),
        ]),
        "",
        "*Tokens processados observados somam `last_token_usage` por chamada registrada; são volume de processamento, não saldo consumido. Reasoning output é subconjunto informativo do output e não é somado novamente.*",
        "",
        "**A soma bruta dos rollouts pode sobrepor trabalho quando a sessão principal agrega subagentes; não use essa coluna para estimar cobrança ou limite.**",
        "",
        f"Fontes de tokens — principais: `{summary['token_sources_root']}`; subagentes: `{summary['token_sources_subagents']}`.",
        "Valores provenientes de `cumulative-snapshot-upper-bound` são limites superiores, não consumo exato.",
    ]

    for title, key in (
        ("Modelos — todos os rollouts", "models"), ("Modelos — sessões principais", "models_root"),
        ("Modelos — subagentes", "models_subagents"), ("Providers", "providers"),
        ("Efforts — todos os rollouts", "efforts"), ("Efforts — sessões principais", "efforts_root"),
        ("Efforts — subagentes", "efforts_subagents"),
        ("Profiles", "profiles"), ("Projetos", "projects"),
        ("Finalidades [heurística]", "intents"), ("Categorias de ferramentas", "tool_categories"),
        ("Ferramentas", "tools"), ("MCPs", "mcp_servers"), ("Ferramentas MCP", "mcp_tools"),
        ("Skills com evidência", "skills"), ("Candidatos de skill rejeitados", "rejected_skill_candidates"),
        ("Mensagens automáticas excluídas", "excluded_messages"),
    ):
        rows = sorted(breakdowns[key].items(), key=lambda item: (-item[1], item[0]))[:top]
        markdown.extend(["", f"## {title}", "", md_table(["Item", "Uso"], rows)])

    markdown.extend(["", "## Prompts repetidos", "", "### Repetições substantivas exatas", ""])
    markdown.append(md_table(
        ["Qtd.", "ID", "Finalidade", "Exemplo"],
        [(item["count"], item["exact_id"], item["intent_heuristic"], item["example"]) for item in report["repeated_prompts"]["exact"]],
    ))
    markdown.extend(["", "### Templates substantivos semelhantes [heurística]", ""])
    markdown.append(md_table(
        ["Qtd.", "Finalidade", "Template", "Exemplo"],
        [(item["count"], item["intent_heuristic"], item["template"][:180], item["example"]) for item in report["repeated_prompts"]["templates"]],
    ))
    markdown.extend(["", "### Prompts de controle", ""])
    markdown.append(md_table(["Prompt normalizado", "Qtd."], report["repeated_prompts"]["control"]))

    markdown.extend(["", "## Objetivos das conversas [extração heurística]", ""])
    objective_rows = []
    for session in report["sessions"]:
        if session["is_subagent"]:
            continue
        objective_rows.append((
            session["first_timestamp"] or "", Path(session["cwd"] or "unknown").name,
            session["dominant_model"] or "", session["dominant_effort"] or "",
            session["profile"], session["intent_heuristic"], session["objective_heuristic"],
        ))
    markdown.append(md_table(["Data", "Projeto", "Modelo", "Effort", "Profile", "Finalidade", "Objetivo"], objective_rows[:max(top, 100)]))

    markdown.extend(["", "## Recomendações", ""])
    for index, recommendation in enumerate(report["recommendations"], 1):
        markdown.extend([
            f"### {index}. {recommendation['type']} — prioridade {recommendation['priority']}", "",
            f"**Evidência:** {recommendation['evidence']}", "",
            f"**Ação:** {recommendation['action']}", "",
        ])

    markdown.extend(["## Profiles sugeridos", ""])
    selection = report.get("profile_model_selection", {})
    markdown.append("Os arquivos prontos ficam em `suggested-profiles/` e usam o formato atual de profiles separados (`<nome>.config.toml`).")
    if selection:
        markdown.append(
            f"A seleção considera a geração mais recente observada/configurada (`GPT {selection.get('generation') or 'não identificada'}`): "
            f"daily={selection.get('daily')}, volume={selection.get('volume')}, deep={selection.get('deep')}, subagentes={selection.get('subagent')}."
        )
        if selection.get("historical_ignored"):
            markdown.append(f"Modelos históricos ignorados na geração de profiles: `{selection['historical_ignored']}`.")
    for filename, spec in report.get("suggested_profiles", {}).items():
        markdown.extend(["", f"### `{filename}`", "", spec["purpose"], "", "```toml", spec["content"].rstrip(), "```"])

    markdown.extend(["", "## Cobertura e limitações", ""])
    for limitation in coverage["limitations"]:
        markdown.append(f"- {limitation}")
    if report.get("deduplicated_files"):
        markdown.append(f"- {len(report['deduplicated_files'])} grupo(s) de arquivos duplicados por session_id foram deduplicados.")
    (out_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")

    with (out_dir / "sessions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "first_timestamp", "session_id", "is_subagent", "parent_thread_id", "project", "cwd",
            "model", "provider", "effort", "tier", "profile", "profile_confidence", "intent_heuristic",
            "objective_heuristic", "usage_source", "total_tokens", "turns", "duration_ms", "tool_calls",
            "mcp_calls", "agent_calls", "tool_failures", "excluded_context_messages",
        ])
        for session in report["sessions"]:
            categories = session["tool_categories"]
            writer.writerow([
                session["first_timestamp"], session["session_id"], session["is_subagent"], session["parent_thread_id"],
                Path(session["cwd"] or "unknown").name, session["cwd"], session["dominant_model"], session["model_provider"],
                session["dominant_effort"], session["dominant_service_tier"], session["profile"], session["profile_confidence"],
                session["intent_heuristic"], session["objective_heuristic"], session["usage_source"], session["usage"]["total_tokens"],
                session["turns"], session["duration_ms"], sum(session["tools"].values()), categories.get("mcp", 0),
                categories.get("agent", 0), session["tool_failures"], sum(session["excluded_messages"].values()),
            ])

    with (out_dir / "prompts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session_id", "timestamp", "control", "exact_id", "intent_heuristic", "objective_heuristic", "template", "text_or_preview"])
        for session in report["sessions"]:
            for prompt in session["prompts"]:
                writer.writerow([
                    session["session_id"], prompt["timestamp"], prompt["control"], prompt["exact_id"], prompt["intent_heuristic"],
                    prompt["objective_heuristic"], prompt["template"], prompt.get("text") or prompt.get("text_preview"),
                ])

    with (out_dir / "tools.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session_id", "is_subagent", "call_id", "tool", "category", "mcp_server", "mcp_tool", "success", "sources"])
        for session in report["sessions"]:
            for call in session.get("tool_details", []):
                writer.writerow([
                    session["session_id"], session["is_subagent"], call.get("call_id"), call.get("name"),
                    call.get("category"), call.get("server"), call.get("tool"), call.get("success"),
                    ",".join(call.get("sources", [])),
                ])

    # Self-contained HTML with the same core results.
    recommendation_html = "".join(
        f"<article><h3>{index}. {html.escape(item['type'])} <small>{html.escape(item['priority'])}</small></h3>"
        f"<p><strong>Evidência:</strong> {html.escape(item['evidence'])}</p>"
        f"<p><strong>Ação:</strong> {html.escape(item['action'])}</p></article>"
        for index, item in enumerate(report["recommendations"], 1)
    )
    sections = []
    for title, key in (("Modelos", "models"), ("Efforts", "efforts"), ("MCPs", "mcp_servers"), ("Skills", "skills"), ("Finalidades", "intents")):
        rows = sorted(breakdowns[key].items(), key=lambda item: (-item[1], item[0]))[:top]
        maximum = max((value for _name, value in rows), default=1)
        bars = "".join(
            f"<div class='barrow'><span>{html.escape(str(name))}</span><div class='bar'><i style='width:{100*value/maximum:.1f}%'></i></div><b>{value}</b></div>"
            for name, value in rows
        ) or "<p>Nenhum dado detectado.</p>"
        sections.append(f"<section><h2>{html.escape(title)}</h2>{bars}</section>")
    html_document = f"""<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Codex Insights</title><style>
body{{font:15px/1.5 system-ui,-apple-system,sans-serif;margin:0;background:#f5f5f5;color:#181818}}main{{max-width:1180px;margin:auto;padding:28px}}header,section,article{{background:#fff;border:1px solid #ddd;border-radius:12px;padding:20px;margin:0 0 18px}}h1,h2{{margin-top:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}.metric{{background:#fafafa;border:1px solid #e5e5e5;border-radius:10px;padding:14px}}.metric b{{display:block;font-size:23px}}.barrow{{display:grid;grid-template-columns:minmax(150px,270px) 1fr 70px;gap:12px;align-items:center;margin:9px 0}}.bar{{height:12px;background:#eee;border-radius:9px;overflow:hidden}}.bar i{{display:block;height:100%;background:#222}}small{{font-weight:500;color:#666}}code{{background:#eee;padding:2px 5px;border-radius:5px}}.notice{{border-left:5px solid #555}}@media(max-width:700px){{main{{padding:12px}}.barrow{{grid-template-columns:1fr}}}}</style></head><body><main>
<header><h1>Codex Insights — relatório corrigido</h1><p>Gerado em <code>{html.escape(report['generated_at'])}</code></p></header>
<section class='notice'><strong>Importante:</strong> tokens são volume processado nas chamadas observadas, não equivalência direta de cobrança ou cota; sessões principais e subagentes são separados.</section>
<section><h2>Resumo</h2><div class='grid'>
<div class='metric'><span>Sessões principais</span><b>{summary['root_sessions']}</b></div>
<div class='metric'><span>Subagentes</span><b>{summary['subagent_sessions']}</b></div>
<div class='metric'><span>Tokens processados — principais</span><b>{format_int(summary['usage_root']['total_tokens'])}</b></div>
<div class='metric'><span>Tokens processados — subagentes</span><b>{format_int(summary['usage_subagents']['total_tokens'])}</b></div>
<div class='metric'><span>Tool calls únicas</span><b>{format_int(summary['tool_calls_all'])}</b></div>
<div class='metric'><span>Prompts humanos</span><b>{format_int(summary['human_prompts'])}</b></div>
</div></section>{''.join(sections)}
<section><h2>Recomendações</h2>{recommendation_html}</section>
<section><h2>Arquivos detalhados</h2><p><code>report.json</code>, <code>report.md</code>, <code>sessions.csv</code>, <code>prompts.csv</code>, <code>tools.csv</code> e <code>suggested-profiles/</code>.</p></section>
</main></body></html>"""
    (out_dir / "report.html").write_text(html_document, encoding="utf-8")


def make_report(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    since = None if args.all_time else utcnow() - timedelta(days=args.days)
    mcp_verbose_path = Path(args.mcp_verbose_file).expanduser() if args.mcp_verbose_file else None
    mcp_verbose_servers, mcp_tool_map = load_mcp_inventory(mcp_verbose_path, codex_home)

    roots = [codex_home / "sessions"]
    if args.include_archived:
        roots.extend([codex_home / "archived_sessions", codex_home / "sessions_archive"])
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(root.rglob("*.jsonl"))
    paths = sorted(set(paths))
    if since:
        filtered: list[Path] = []
        for path in paths:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if modified >= since - timedelta(days=3):
                filtered.append(path)
        paths = filtered

    parsed = [parse_rollout(path, mcp_tool_map) for path in paths]
    if since:
        parsed = [session for session in parsed if session.last_ts is None or session.last_ts >= since]
    sessions, duplicate_files = deduplicate_sessions(parsed)
    if args.exclude_subagents:
        sessions = [session for session in sessions if not session.is_subagent()]

    project_configs = discover_project_configs((session.cwd for session in sessions), Path.cwd())
    inventory = config_inventory(codex_home, project_configs)
    installed_skills = discover_skills(codex_home, (session.cwd for session in sessions), Path.cwd())
    agents_docs = discover_agents_docs(codex_home, (session.cwd for session in sessions))
    ledger = load_profile_ledger(codex_home, since)
    assign_profiles(sessions, inventory, ledger)

    root_sessions = [session for session in sessions if not session.is_subagent()]
    subagent_sessions = [session for session in sessions if session.is_subagent()]
    usage_root, covered_root, usage_sources_root = aggregate_usage(root_sessions)
    usage_subagents, covered_subagents, usage_sources_subagents = aggregate_usage(subagent_sessions)
    usage_all = Usage(); usage_all.add(usage_root); usage_all.add(usage_subagents)

    substantive_prompts = [prompt for session in root_sessions for prompt in session.prompts if not prompt.control]
    control_prompts = [prompt for session in root_sessions for prompt in session.prompts if prompt.control]
    exact_counts = Counter(prompt.exact_id for prompt in substantive_prompts)
    template_counts = Counter(prompt.template for prompt in substantive_prompts if prompt.template)
    exact_example: dict[str, PromptRecord] = {}
    template_example: dict[str, PromptRecord] = {}
    for prompt in substantive_prompts:
        exact_example.setdefault(prompt.exact_id, prompt)
        template_example.setdefault(prompt.template, prompt)

    models = Counter(session.dominant_model() or "unknown" for session in sessions)
    models_root = Counter(session.dominant_model() or "unknown" for session in root_sessions)
    models_subagents = Counter(session.dominant_model() or "unknown" for session in subagent_sessions)
    providers = Counter(session.model_provider or "unknown" for session in sessions)
    efforts = Counter(session.dominant_effort() or "unknown" for session in sessions)
    efforts_root = Counter(session.dominant_effort() or "unknown" for session in root_sessions)
    efforts_subagents = Counter(session.dominant_effort() or "unknown" for session in subagent_sessions)
    profiles = Counter(f"{session.profile_name} [{session.profile_confidence}]" for session in root_sessions)
    projects = Counter(Path(session.cwd).name if session.cwd else "unknown" for session in root_sessions)
    intents = Counter(session.intent() for session in root_sessions)
    tools: Counter[str] = Counter()
    tool_categories: Counter[str] = Counter()
    mcp_servers: Counter[str] = Counter()
    mcp_tools: Counter[str] = Counter()
    skills: Counter[str] = Counter()
    rejected_skill_candidates: Counter[str] = Counter()
    installed_skill_lookup = {name.lower().replace("_", "-"): name for name in installed_skills}
    excluded_messages: Counter[str] = Counter()
    for session in sessions:
        for call in session.tool_calls.values():
            tools[call.name] += 1
            tool_categories[call.category] += 1
            if call.server:
                mcp_servers[call.server] += 1
            if call.server and call.tool:
                mcp_tools[f"{call.server}::{call.tool}"] += 1
        for name, use in session.skills.items():
            canonical_name = name.lower().replace("_", "-")
            strong_evidence = bool(use.evidence & {"structured-user-skill", "tool-read-skill-path"})
            if canonical_name in installed_skill_lookup:
                skills[installed_skill_lookup[canonical_name]] += use.count
            elif strong_evidence and VALID_SKILL_NAME_RE.fullmatch(canonical_name):
                skills[canonical_name] += use.count
            else:
                rejected_skill_candidates[canonical_name] += use.count
        excluded_messages.update(session.excluded_messages)

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else codex_home / "usage-data" / f"local-insights-{utcnow().strftime('%Y%m%d-%H%M%S')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    suggested_profiles = write_profile_files(output_dir, sessions, inventory)
    recommendations = build_recommendations(
        sessions, inventory, agents_docs, installed_skills, template_counts, mcp_verbose_servers,
    )

    report = {
        "schema_version": 2,
        "generator": {"name": "codex-insights-local", "version": VERSION},
        "generated_at": utcnow().isoformat(),
        "coverage": {
            "codex_home": str(codex_home),
            "since": since.isoformat() if since else None,
            "days": None if args.all_time else args.days,
            "include_archived": args.include_archived,
            "exclude_subagents": args.exclude_subagents,
            "rollout_files_found": len(paths),
            "sessions_after_deduplication": len(sessions),
            "mcp_verbose_inventory_loaded": bool(mcp_verbose_servers),
            "limitations": [
                "last_token_usage é somado por chamada observada e representa tokens processados; total_token_usage é usado apenas como fallback/limite superior quando não há telemetria por chamada.",
                "cached_input_tokens é subconjunto de input_tokens; reasoning_output_tokens normalmente é subconjunto de output_tokens e não é somado novamente.",
                "algumas versões/modos interativos do Codex não persistem token_count; sessões sem telemetria são marcadas como unavailable.",
                "a soma combinada de rollouts não é fatura, saldo de créditos ou equivalência da cota semanal e pode sobrepor trabalho caso a sessão principal agregue subagentes; use as colunas separadas.",
                "nome histórico do profile só é exato quando iniciado por codex-profile; demais casos são inferências pelos settings resolvidos.",
                "finalidade e objetivo são heurísticas locais aplicadas apenas a mensagens humanas após excluir AGENTS, contexto interno, notificações de subagente e metadados de anexos.",
                "skills automáticas sem evento estruturado podem ficar ausentes; o relatório não interpreta catálogos de skills como execução.",
                "MCPs são atribuídos pelo invocation.server/tool; logs antigos podem exigir o arquivo opcional de /mcp verbose.",
            ],
        },
        "summary": {
            "sessions": len(sessions),
            "root_sessions": len(root_sessions),
            "subagent_sessions": len(subagent_sessions),
            "human_prompts": len(substantive_prompts) + len(control_prompts),
            "substantive_prompts": len(substantive_prompts),
            "control_prompts": len(control_prompts),
            "usage_root": usage_root.as_dict(),
            "usage_subagents": usage_subagents.as_dict(),
            "usage_all": usage_all.as_dict(),
            "token_covered_root": covered_root,
            "token_covered_subagents": covered_subagents,
            "token_covered_all": covered_root + covered_subagents,
            "token_sources_root": dict(usage_sources_root),
            "token_sources_subagents": dict(usage_sources_subagents),
            "model_usage_events_root": sum(len(session.last_usage_events) for session in root_sessions),
            "model_usage_events_subagents": sum(len(session.last_usage_events) for session in subagent_sessions),
            "model_usage_events_all": sum(len(session.last_usage_events) for session in sessions),
            "uncached_input_root": max(0, usage_root.input_tokens - usage_root.cached_input_tokens),
            "uncached_input_subagents": max(0, usage_subagents.input_tokens - usage_subagents.cached_input_tokens),
            "uncached_input_all": max(0, usage_all.input_tokens - usage_all.cached_input_tokens),
            "turns_root": sum(session.turns() for session in root_sessions),
            "turns_subagents": sum(session.turns() for session in subagent_sessions),
            "turns_all": sum(session.turns() for session in sessions),
            "duration_root_ms": sum(session.duration_ms() for session in root_sessions),
            "duration_subagents_ms": sum(session.duration_ms() for session in subagent_sessions),
            "duration_all_ms": sum(session.duration_ms() for session in sessions),
            "tool_calls_root": sum(len(session.tool_calls) for session in root_sessions),
            "tool_calls_subagents": sum(len(session.tool_calls) for session in subagent_sessions),
            "tool_calls_all": sum(len(session.tool_calls) for session in sessions),
            "tool_failures": sum(call.success is False for session in sessions for call in session.tool_calls.values()),
            "compactions": sum(session.compactions for session in sessions),
        },
        "breakdowns": {
            "models": dict(models), "models_root": dict(models_root), "models_subagents": dict(models_subagents),
            "providers": dict(providers), "efforts": dict(efforts), "efforts_root": dict(efforts_root),
            "efforts_subagents": dict(efforts_subagents), "profiles": dict(profiles), "projects": dict(projects), "intents": dict(intents),
            "tools": dict(tools), "tool_categories": dict(tool_categories),
            "mcp_servers": dict(mcp_servers), "mcp_tools": dict(mcp_tools),
            "skills": dict(skills), "rejected_skill_candidates": dict(rejected_skill_candidates),
            "excluded_messages": dict(excluded_messages),
        },
        "repeated_prompts": {
            "exact": [
                {"count": count, "exact_id": key, "intent_heuristic": exact_example[key].intent, "example": exact_example[key].objective}
                for key, count in exact_counts.most_common(args.top) if count >= 2
            ],
            "templates": [
                {"count": count, "template": key, "intent_heuristic": template_example[key].intent, "example": template_example[key].objective}
                for key, count in template_counts.most_common(args.top) if count >= 2
            ],
            "control": Counter(normalize_prompt(prompt.text) for prompt in control_prompts).most_common(args.top),
        },
        "config_inventory": inventory,
        "agents_docs": agents_docs,
        "installed_skills": installed_skills,
        "mcp_verbose_inventory": mcp_verbose_servers,
        "suggested_profiles": suggested_profiles,
        "recommendations": recommendations,
        "deduplicated_files": duplicate_files,
        "sessions": [serialize_session(session, args.include_full_prompts) for session in sessions],
    }

    write_outputs(report, output_dir, args.top)
    usage_dir = codex_home / "usage-data"
    usage_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("report.json", "report.md", "report.html", "sessions.csv", "prompts.csv", "tools.csv"):
        source = output_dir / filename
        if source.exists():
            try:
                shutil.copy2(source, usage_dir / f"latest-{filename}")
            except OSError:
                pass
    return report, output_dir


def launch_profile(args: argparse.Namespace) -> int:
    codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    ledger = codex_home / "usage-data" / "profile-ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": utcnow().isoformat(),
        "profile": args.profile,
        "cwd": str(Path.cwd()),
        "argv": args.codex_args,
    }
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    executable = shutil.which("codex")
    if not executable:
        print("Erro: executável 'codex' não encontrado no PATH.", file=sys.stderr)
        return 127
    argv = [executable]
    if args.profile not in {"default", "none", "-"}:
        argv.extend(["--profile", args.profile])
    argv.extend(args.codex_args)
    os.execv(executable, argv)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-insights", description="Relatório local de sessões, tokens, modelos, efforts, profiles, MCPs, skills e prompts do Codex CLI.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    report = subparsers.add_parser("report", help="Gerar relatório (comando padrão).")
    for target in (parser, report):
        target.add_argument("--days", type=int, default=30, help="Janela em dias (padrão: 30).")
        target.add_argument("--all-time", action="store_true", help="Analisar todo o histórico disponível.")
        target.add_argument("--include-archived", action="store_true", help="Incluir diretórios de sessões arquivadas.")
        target.add_argument("--exclude-subagents", action="store_true", help="Excluir rollouts identificados como subagentes.")
        target.add_argument("--include-subagents", action="store_true", help="Compatibilidade: subagentes já são incluídos por padrão.")
        target.add_argument("--include-full-prompts", action="store_true", help="Incluir texto completo redigido dos prompts; padrão: preview.")
        target.add_argument("--mcp-verbose-file", help="Arquivo contendo a saída de /mcp verbose para mapear ferramentas antigas.")
        target.add_argument("--codex-home", help="Sobrescrever CODEX_HOME.")
        target.add_argument("--output-dir", help="Diretório de saída.")
        target.add_argument("--top", type=int, default=30, help="Quantidade máxima por ranking.")

    launch = subparsers.add_parser("launch", help="Abrir Codex por um profile e registrar o nome exato para relatórios futuros.")
    launch.add_argument("profile", help="Nome do profile; use default para iniciar sem --profile.")
    launch.add_argument("codex_args", nargs=argparse.REMAINDER, help="Argumentos adicionais do Codex.")
    launch.add_argument("--codex-home", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "launch":
        return launch_profile(args)
    report, output_dir = make_report(args)
    summary = report["summary"]
    print(f"Relatório gerado: {output_dir}")
    print(
        f"principais={summary['root_sessions']} subagentes={summary['subagent_sessions']} "
        f"tokens_principais={summary['usage_root']['total_tokens']} "
        f"tokens_subagentes={summary['usage_subagents']['total_tokens']} "
        f"tools={summary['tool_calls_all']}"
    )
    print(f"HTML: {output_dir / 'report.html'}")
    print(f"Markdown: {output_dir / 'report.md'}")
    print(f"JSON: {output_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
