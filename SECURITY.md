# Security Policy

## Supported versions

Security fixes are provided for the latest published release.

## Reporting a vulnerability

Please do not open public issues for suspected security vulnerabilities.

Use
[GitHub Private Vulnerability Reporting](https://github.com/Not-Dev-Tech/codex-insights-local/security/advisories/new)
when available.

Include:

- affected version;
- operating system;
- reproduction steps using synthetic data;
- potential impact;
- suggested mitigation, if known.

Do not include real credentials, session files, prompts, reports, or MCP
inventories. The maintainers will acknowledge a report as soon as practical,
investigate it privately, and coordinate disclosure after a fix is available.

## Sensitive data

Codex Insights Local analyzes local Codex session files. Before sharing reports
publicly, review them carefully. Reports generated with
`--include-full-prompts` may contain source code, local paths, project names,
user messages, or other sensitive information.

The application does not call the network, but generated files are written to
disk. Store and share them according to the sensitivity of the source sessions.
