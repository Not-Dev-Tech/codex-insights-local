---
name: codex-insights
description: Gere um relatório local e somente leitura sobre sessões, tokens, modelos, reasoning effort, profiles, MCPs, ferramentas, skills, prompts repetidos, finalidades e objetivos do Codex CLI. Use para auditoria de consumo e recomendações de configuração.
---

# Codex Insights

Use o coletor determinístico instalado. Não abra todos os rollouts com o modelo e não use subagentes para gerar o relatório.

## Procedimento

1. Interprete os argumentos. Padrões: `days=30`, inclui sessões principais e subagentes, não inclui arquivos arquivados.
2. Execute uma vez:

```bash
codex-insights report --days <dias>
```

Adicione quando solicitado:

- `--all-time`
- `--include-archived`
- `--exclude-subagents`
- `--include-full-prompts`
- `--mcp-verbose-file <arquivo>`

3. Leia primeiro `report.md`. Consulte `report.json` somente para detalhes estruturados. Não reabra os JSONL brutos.
4. Diferencie explicitamente:
   - medido nos rollouts/configs;
   - derivado deterministicamente;
   - heurístico;
   - indisponível.
5. Destaque:
   - tokens de sessões principais e subagentes separadamente;
   - distribuição por modelo, effort, projeto e profile;
   - MCPs, skills e falhas;
   - prompts substantivos repetidos;
   - contexto automático excluído;
   - profiles sugeridos em `suggested-profiles/`;
   - cobertura e limitações.
6. Não altere configs, profiles, MCPs ou skills sem pedido separado e explícito.
7. Não exponha credenciais, tokens, cookies ou texto integral de prompts sem solicitação explícita.

## Invocação sugerida

```text
$codex-insights days=30
```
