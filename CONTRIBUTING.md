# Contributing

Thank you for helping improve Codex Insights Local.

## Before you start

- Search existing issues and discussions before proposing a duplicate.
- Do not attach real Codex sessions, reports, prompts, credentials, local
  paths, or MCP inventories to a public issue.
- For suspected vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of
  opening a public issue.

## Development setup

Requirements:

- Python 3.11 or newer;
- Git;
- Codex CLI only when manually testing against your own local data.

Clone the repository and run the test suite:

```bash
git clone https://github.com/Not-Dev-Tech/codex-insights-local.git
cd codex-insights-local
python -m py_compile codex_insights.py
python -m pip install -e ".[test]"
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python codex_insights.py --version
```

The runtime intentionally has no third-party Python dependencies.

## Making changes

1. Create a focused branch from `main`.
2. Add or update tests before changing behavior.
3. Keep processing local and deterministic; do not add telemetry or network
   calls without an explicit project decision.
4. Preserve input data. The analyzer must never modify Codex session or
   configuration files.
5. Validate all file and command-line input at the boundary.
6. Use Conventional Commits, for example
   `fix(parser): handle missing token telemetry`.

Run all checks before opening a pull request:

```bash
python -m py_compile codex_insights.py
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python codex_insights.py --version
```

## Test fixtures

Use synthetic values only. Replace usernames, project paths, repository names,
tokens, server names, and prompts with obviously fictional data. A fixture
must not be copied from a real `~/.codex` directory.

## Pull requests

Explain what changed, why it changed, and how it was tested. Keep pull requests
small enough to review, update user-facing documentation when behavior changes,
and confirm that generated reports or local data are not included.

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
