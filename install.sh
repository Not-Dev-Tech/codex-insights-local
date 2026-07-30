#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
APP_HOME="${CODEX_INSIGHTS_HOME:-$HOME/.local/share/codex-insights}"
BIN_HOME="$HOME/.local/bin"
SKILL_HOME="$CODEX_HOME/skills/codex-insights"
mkdir -p "$APP_HOME" "$BIN_HOME" "$SKILL_HOME"
install -m 0755 "$ROOT/codex_insights.py" "$APP_HOME/codex_insights.py"
install -m 0755 "$ROOT/bin/codex-insights" "$BIN_HOME/codex-insights"
install -m 0755 "$ROOT/bin/codex-profile" "$BIN_HOME/codex-profile"
install -m 0644 "$ROOT/skill/SKILL.md" "$SKILL_HOME/SKILL.md"
mkdir -p "$CODEX_HOME/usage-data"
printf '\nCodex Insights %s instalado.\n' "$(python3 "$APP_HOME/codex_insights.py" --version | awk '{print $2}')"
printf 'Adicione %s ao PATH, se necessário.\n' "$BIN_HOME"
printf 'Relatório: codex-insights report --days 30\n'
printf 'No Codex: $codex-insights days=30\n'
printf 'Profile rastreável: codex-profile daily\n'
printf 'MCP antigo: salve /mcp verbose em %s/usage-data/mcp-verbose.txt\n' "$CODEX_HOME"
printf 'Ou use: codex-insights report --mcp-verbose-file <arquivo>\n'
