## What

Describe the change.

## Why

Explain the user problem or maintenance need.

## How

Summarize the implementation and any compatibility decisions.

## Testing

- [ ] `python -m py_compile codex_insights.py`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python codex_insights.py --version`
- [ ] Manual testing performed when applicable

## Privacy and security

- [ ] No real Codex sessions, reports, prompts, local paths, credentials, or
      MCP inventories are included.
- [ ] New file or command-line input is validated.
- [ ] The analyzer still makes no network calls.
- [ ] Generated output and documentation explain any new sensitive-data risk.

## Checklist

- [ ] Tests were added or updated before behavior changed.
- [ ] User-facing documentation was updated.
- [ ] The full diff was self-reviewed.
- [ ] The change follows the Code of Conduct and contribution guidelines.
