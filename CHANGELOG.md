# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.3] - 2026-07-30

### Added

- Separate model selection for daily, volume, deep, and subagent profiles.
- Root/subagent usage breakdowns, model event counts, uncached input totals,
  and expanded prompt-intent classification.
- Open-source project metadata, bilingual documentation, community health
  files, automated tests, and a sanitized MCP inventory example.

### Changed

- Profile suggestions use only the newest observed/configured GPT generation.
- Token labels now emphasize observed processing and clarify that values do not
  represent billing, subscription credits, or weekly allowances.
- Installers no longer copy any bundled MCP inventory.

### Fixed

- Historical models such as `gpt-5.3-codex-spark` are not selected for volume
  or subagent profiles when a newer generation is available.
- Short responses such as `pode` and isolated times are treated as control
  messages.

## [0.2.2]

### Changed

- Filtered additional automatic contexts.
- Normalized MCP server and tool names.
- Validated skills against the installed inventory.
- Preferred `last_token_usage` as the usage source.

[Unreleased]: https://github.com/Not-Dev-Tech/codex-insights-local/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/Not-Dev-Tech/codex-insights-local/releases/tag/v0.2.3
[0.2.2]: https://github.com/Not-Dev-Tech/codex-insights-local/releases/tag/v0.2.2
