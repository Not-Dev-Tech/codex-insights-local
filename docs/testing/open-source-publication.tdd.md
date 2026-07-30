# Open-source publication TDD evidence

## Source

The user supplied the publication requirements directly in the task. No
external `*.plan.md` file was used.

## User journeys

- As a prospective user, I can clone and install a distribution that does not
  contain another person's Codex or MCP data.
- As a contributor, I can verify packaging, behavior, and the 80% coverage
  threshold with documented commands.
- As a maintainer, I can publish version 0.2.3 with recognized licensing,
  security guidance, contribution templates, and CI checks.

## RED and GREEN evidence

### Distribution hygiene

RED command:

```text
python -m unittest tests.test_repository_hygiene -v
```

Initial result:

```text
Ran 5 tests
FAILED (failures=2, errors=3)
```

The failures proved that the root MCP inventory was still present, installers
still copied it, and the public metadata/documentation files did not yet exist.

GREEN command:

```text
python -m unittest discover -s tests -v
```

Final result:

```text
Ran 13 tests
OK
```

### Packaging

RED command:

```text
uv build
```

Initial result:

```text
setuptools.errors.InvalidConfigError:
License classifiers have been superseded by license expressions
```

The modern SPDX expression `license = "MIT"` was retained and the superseded
license classifier was removed.

GREEN command:

```text
uv build
```

Final result:

```text
Successfully built dist/codex_insights_local-0.2.3.tar.gz
Successfully built dist/codex_insights_local-0.2.3-py3-none-any.whl
```

## Test specification

| # | Guarantee | Test or command | Type | Result |
|---|---|---|---|---|
| 1 | No root MCP inventory is distributable and the example is sanitized | `test_distribution_contains_only_a_sanitized_mcp_example` | security/regression | PASS |
| 2 | Installers never copy a bundled MCP inventory | `test_installers_never_copy_a_bundled_mcp_inventory` | integration | PASS |
| 3 | Reports, local Codex data, MCP inventories, and secrets are ignored | `test_sensitive_local_outputs_are_ignored` | security/regression | PASS |
| 4 | Python metadata names version 0.2.3, requires 3.11+, and has no runtime dependencies | `test_python_project_metadata_matches_the_release` | packaging | PASS |
| 5 | Both READMEs use the canonical repository and include the independence/privacy notices | `test_public_documentation_uses_the_canonical_repository` | documentation | PASS |
| 6 | Existing rollout parsing and report behavior remain correct | `tests/test_codex_insights.py` | unit/integration | PASS |
| 7 | The module compiles | `python -m py_compile codex_insights.py` | build | PASS |
| 8 | Source and wheel distributions build successfully | `uv build` | packaging | PASS |

## Coverage and known gaps

Command:

```text
uv run --with coverage coverage run -m unittest discover -s tests -v
uv run --with coverage coverage report
```

Result:

```text
codex_insights.py    1329 statements    230 missed    83%
```

The configured gate enforces at least 80% line coverage. Branch coverage was
measured separately at 75% during this work but is not currently a CI gate.
The largest remaining gaps are malformed rollout variants and the successful
`os.execv` profile-launch path, which would replace the test process.

## Merge evidence

The first public commit preserves the test files and this report, so the RED
and GREEN evidence remains available even though the new repository starts
with a single release commit.
