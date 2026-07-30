# Codex Insights Local

[Português (Brasil)](README.pt-BR.md)

Local-first, read-only analytics for OpenAI Codex CLI sessions, models,
reasoning effort, subagents, MCP tools, skills, and repeated prompts.

> [!IMPORTANT]
> Codex Insights Local is an independent community project.
> It is not affiliated with, maintained by, sponsored by, or endorsed by
> OpenAI. “OpenAI” and “Codex” are trademarks of their respective owner.

Codex Insights Local turns local Codex CLI rollout files into deterministic
HTML, Markdown, JSON, and CSV reports. It helps you understand how you use
models, reasoning effort, profiles, subagents, MCP servers, tools, and skills
without uploading your sessions or asking another model to analyze them.

The canonical repository is
<https://github.com/Not-Dev-Tech/codex-insights-local>.

## What it reports

- observed token processing for root sessions and subagents, reported
  separately;
- model, provider, reasoning-effort, project, and profile distributions;
- root and subagent turn counts and observed durations;
- MCP server/tool usage, generic tool usage, failures, and subagent launches;
- installed and observed Codex skills;
- repeated substantive prompts, control messages, inferred intent, and
  excluded automatic context;
- current Codex configuration inventory with credential-like fields redacted;
- deterministic, separately generated profile suggestions.

The analyzer does not modify Codex sessions or configuration files. It does not
call an LLM, an MCP server, the OpenAI API, or any other network service.

## Example

A generated Markdown summary begins with metrics like these:

```text
Sessions
  Root sessions:             24
  Subagent sessions:          8

Observed processed tokens
  Root sessions:        1,250,400
  Subagents:              318,900

Top models
  gpt-example-a                 18
  gpt-example-b                 14
```

Every report records its coverage, measurement source, and limitations. Values
shown above are fictional and are not bundled report data.

## Privacy and safety

Processing happens locally and the application has no network code. It reads
Codex rollout/configuration files and writes report files to disk.

By default, prompt text is represented by redacted previews. Even so, generated
reports can contain project names, local paths, configuration metadata, or
short excerpts from messages. Review every report before sharing it.

`--include-full-prompts` is deliberately opt-in. Reports created with it may
contain source code, local paths, project names, user messages, and other
sensitive information. Do not publish generated reports unless you have
inspected and sanitized them.

Codex Insights Local never ships an MCP inventory. The file under `examples/`
is synthetic. If older rollouts need MCP attribution, generate your own
`/mcp verbose` output and keep it local.

## Requirements

- Python 3.11 or newer (`tomllib` is used from the standard library);
- Codex CLI installed for normal use and for the optional profile launcher;
- no Python runtime dependencies.

## Installation

### Windows PowerShell

```powershell
git clone https://github.com/Not-Dev-Tech/codex-insights-local.git
cd codex-insights-local
.\install.ps1
```

Add `%USERPROFILE%\.local\bin` to `PATH` if it is not already present.

### Linux, macOS, or WSL

```bash
git clone https://github.com/Not-Dev-Tech/codex-insights-local.git
cd codex-insights-local
chmod +x install.sh
./install.sh
```

Add `~/.local/bin` to `PATH` if needed.

### Python package

You can also install directly from a clone:

```bash
python -m pip install .
```

## Usage

Generate a report for the last 30 days:

```bash
codex-insights report --days 30
```

Common variants:

```bash
codex-insights report --days 90 --include-archived
codex-insights report --all-time
codex-insights report --days 30 --exclude-subagents
codex-insights report --days 30 --output-dir ./private-report
```

Inside Codex, after installing the bundled skill:

```text
$codex-insights days=30
```

Track the exact profile name for future reports:

```bash
codex-profile daily
codex-profile deep -C /path/to/project
codex-profile parallel
```

### Commands and options

| Command or option | Purpose |
|---|---|
| `report` | Generate reports; this is the default command |
| `launch PROFILE` | Start Codex with a profile and record its exact name locally |
| `--days N` | Analyze the last `N` days; default is 30 |
| `--all-time` | Analyze all available sessions |
| `--include-archived` | Include archived session directories |
| `--exclude-subagents` | Exclude detected subagent rollouts |
| `--include-full-prompts` | Include full redacted prompt text; use with care |
| `--mcp-verbose-file PATH` | Read an optional user-provided `/mcp verbose` file |
| `--codex-home PATH` | Override the Codex home directory |
| `--output-dir PATH` | Select the report output directory |
| `--top N` | Limit ranking tables; default is 30 |

Run `codex-insights --help` for the complete CLI help.

## Optional MCP inventory

Modern rollouts can identify many MCP calls directly. Older rollouts may need a
local inventory:

1. Run `/mcp verbose` in Codex.
2. Save the output outside the repository, for example at
   `~/.codex/usage-data/mcp-verbose.txt`.
3. Either let Codex Insights discover that default path or pass it explicitly:

```bash
codex-insights report --days 90 --mcp-verbose-file /private/path/mcp-verbose.txt
```

The installer never copies or creates this inventory.

## Outputs

Unless `--output-dir` is supplied, reports are written under:

```text
~/.codex/usage-data/local-insights-<timestamp>/
├── report.html
├── report.md
├── report.json
├── sessions.csv
├── prompts.csv
├── tools.csv
└── suggested-profiles/
    ├── daily.config.toml
    ├── volume.config.toml
    ├── deep.config.toml
    └── parallel.config.toml
```

Convenience copies named `latest-report.*` and `latest-*.csv` are also written
under the local usage-data directory. These files are ignored by this
repository because they may contain sensitive data.

## Interpreting token data

The preferred source is `last_token_usage`, summed for each observed model
usage event. When that field is unavailable, the largest
`total_token_usage` value is reported as a cumulative snapshot upper bound,
not as exact consumption.

`cached_input_tokens` is a subset of input tokens.
`reasoning_output_tokens` is normally a subset of output tokens and is not
added to the total again.

Root sessions and subagents are shown separately. Their combined value may
overlap when a root session already aggregates subagent work. The report is not
an invoice and is not guaranteed to match subscription credits, rate limits,
or weekly allowances.

## Limitations

- Codex CLI versions and execution modes do not all persist the same telemetry.
- Sessions without `token_count` events are reported as unavailable.
- Historical profile names are exact only when launched through
  `codex-profile`; other matches are inferred from resolved settings.
- Prompt intent and objective labels are local heuristics, not model judgments.
- Automatic context and skill execution formats can change between Codex
  versions.
- Old MCP calls may remain unattributed without a user-provided inventory.
- The current implementation is intentionally a single Python module. A future
  release may migrate it to a `src/codex_insights/` package.

## Development

```bash
python -m py_compile codex_insights.py
python -m pip install -e ".[test]"
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python codex_insights.py --version
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Report
suspected vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Community participation is governed by
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

Codex Insights Local is available under the [MIT License](LICENSE).

## Trademark notice

This project uses the terms “OpenAI” and “Codex” only to describe
compatibility. It does not use OpenAI logos and does not claim an official
partnership, sponsorship, or endorsement.
