# Codex Insights Local

[English](README.md)

Analytics local-first e somente leitura para sessões do OpenAI Codex CLI,
modelos, esforço de raciocínio, subagentes, ferramentas MCP, skills e prompts
repetidos.

> [!IMPORTANT]
> Codex Insights Local é um projeto comunitário independente.
> It is not affiliated with, maintained by, sponsored by, or endorsed by
> OpenAI. “OpenAI” e “Codex” são marcas de seu respectivo proprietário.

O Codex Insights Local transforma rollouts locais do Codex CLI em relatórios
determinísticos HTML, Markdown, JSON e CSV. Ele ajuda a entender o uso de
modelos, reasoning effort, profiles, subagentes, servidores MCP, ferramentas e
skills sem enviar sessões para a rede nem pedir que outro modelo as analise.

O repositório canônico é
<https://github.com/Not-Dev-Tech/codex-insights-local>.

## O que ele analisa

- tokens processados observados, separando sessões principais e subagentes;
- distribuições por modelo, provider, reasoning effort, projeto e profile;
- turnos, duração observada, ferramentas, falhas e criação de subagentes;
- servidores e ferramentas MCP;
- skills instaladas e observadas;
- prompts substantivos repetidos, mensagens de controle, finalidade inferida e
  contexto automático excluído;
- inventário de configuração do Codex com campos semelhantes a credenciais
  mascarados;
- sugestões determinísticas de profiles, geradas em arquivos separados.

O analisador não altera sessões nem arquivos de configuração do Codex. Ele não
chama LLMs, servidores MCP, a API da OpenAI nem qualquer serviço de rede.

## Exemplo

Um resumo Markdown gerado começa com métricas semelhantes a estas:

```text
Sessões
  Sessões principais:         24
  Subagentes:                  8

Tokens processados observados
  Sessões principais:  1.250.400
  Subagentes:             318.900

Modelos mais usados
  gpt-example-a                 18
  gpt-example-b                 14
```

Os valores acima são fictícios e não são dados reais empacotados.

## Privacidade e segurança

Todo o processamento ocorre localmente e o aplicativo não contém chamadas de
rede. Ele lê rollouts/configurações do Codex e grava relatórios no disco.

Por padrão, os prompts aparecem apenas como previews redigidos. Ainda assim,
relatórios podem conter nomes de projetos, caminhos locais, metadados de
configuração ou trechos curtos de mensagens. Revise todo relatório antes de
compartilhá-lo.

`--include-full-prompts` é opcional e deve ser usado com cuidado. Os relatórios
gerados com essa opção podem conter código-fonte, caminhos locais, nomes de
projetos, mensagens e outros dados sensíveis. Não publique relatórios sem
inspecioná-los e sanitizá-los.

O projeto nunca distribui um inventário MCP real. O arquivo em `examples/` é
sintético. Para melhorar a atribuição de MCP em rollouts antigos, gere sua
própria saída de `/mcp verbose` e mantenha-a local.

## Requisitos

- Python 3.11 ou superior (`tomllib` faz parte da biblioteca padrão);
- Codex CLI instalado para uso normal e para o launcher opcional de profiles;
- nenhuma dependência Python em runtime.

## Instalação

### Windows PowerShell

```powershell
git clone https://github.com/Not-Dev-Tech/codex-insights-local.git
cd codex-insights-local
.\install.ps1
```

Adicione `%USERPROFILE%\.local\bin` ao `PATH`, se necessário.

### Linux, macOS ou WSL

```bash
git clone https://github.com/Not-Dev-Tech/codex-insights-local.git
cd codex-insights-local
chmod +x install.sh
./install.sh
```

Adicione `~/.local/bin` ao `PATH`, se necessário.

### Pacote Python

Também é possível instalar diretamente de um clone:

```bash
python -m pip install .
```

## Uso

Gere um relatório dos últimos 30 dias:

```bash
codex-insights report --days 30
```

Variações comuns:

```bash
codex-insights report --days 90 --include-archived
codex-insights report --all-time
codex-insights report --days 30 --exclude-subagents
codex-insights report --days 30 --output-dir ./relatorio-privado
```

Dentro do Codex, após instalar a skill incluída:

```text
$codex-insights days=30
```

Registre o nome exato do profile para relatórios futuros:

```bash
codex-profile daily
codex-profile deep -C /caminho/do/projeto
codex-profile parallel
```

### Comandos e opções

| Comando ou opção | Finalidade |
|---|---|
| `report` | Gera relatórios; é o comando padrão |
| `launch PROFILE` | Inicia o Codex com um profile e registra seu nome localmente |
| `--days N` | Analisa os últimos `N` dias; padrão: 30 |
| `--all-time` | Analisa todo o histórico disponível |
| `--include-archived` | Inclui diretórios de sessões arquivadas |
| `--exclude-subagents` | Exclui rollouts identificados como subagentes |
| `--include-full-prompts` | Inclui prompts redigidos completos; use com cuidado |
| `--mcp-verbose-file PATH` | Lê um `/mcp verbose` opcional fornecido pelo usuário |
| `--codex-home PATH` | Sobrescreve o diretório home do Codex |
| `--output-dir PATH` | Escolhe o diretório de saída |
| `--top N` | Limita rankings; padrão: 30 |

Execute `codex-insights --help` para ver a ajuda completa.

## Inventário MCP opcional

Rollouts modernos identificam muitas chamadas MCP diretamente. Logs antigos
podem precisar de um inventário local:

1. Execute `/mcp verbose` no Codex.
2. Salve a saída fora do repositório, por exemplo em
   `~/.codex/usage-data/mcp-verbose.txt`.
3. Use o caminho padrão acima ou informe o arquivo:

```bash
codex-insights report --days 90 --mcp-verbose-file /caminho/privado/mcp-verbose.txt
```

O instalador nunca copia nem cria esse inventário.

## Saídas

Sem `--output-dir`, os relatórios são gravados em:

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

Cópias de conveniência `latest-report.*` e `latest-*.csv` também são gravadas
no diretório local `usage-data`. Elas são ignoradas pelo repositório porque
podem conter dados sensíveis.

## Interpretação dos tokens

A fonte preferencial é `last_token_usage`, somada por evento observado de uso
do modelo. Quando ela não existe, o maior `total_token_usage` é apresentado
como limite superior de um snapshot cumulativo, não como consumo exato.

`cached_input_tokens` é subconjunto dos tokens de entrada.
`reasoning_output_tokens` normalmente é subconjunto dos tokens de saída e não
é somado novamente ao total.

Sessões principais e subagentes aparecem separadamente. O total combinado pode
ter sobreposição quando a sessão principal já agrega o trabalho de subagentes.
O relatório não é uma fatura nem tem equivalência garantida com créditos,
limites ou cotas semanais.

## Limitações

- Versões e modos do Codex CLI não persistem a mesma telemetria.
- Sessões sem eventos `token_count` são marcadas como indisponíveis.
- O nome histórico do profile só é exato quando iniciado por `codex-profile`;
  outros casos são inferidos pelas configurações resolvidas.
- Finalidade e objetivo dos prompts são heurísticas locais.
- Formatos de contexto automático e execução de skills podem mudar.
- MCPs antigos podem ficar sem atribuição sem um inventário do próprio usuário.
- A implementação atual permanece em um único módulo Python; uma versão futura
  poderá migrar para `src/codex_insights/`.

## Desenvolvimento e contribuição

```bash
python -m py_compile codex_insights.py
python -m pip install -e ".[test]"
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python codex_insights.py --version
```

Leia [CONTRIBUTING.md](CONTRIBUTING.md) antes de abrir um pull request. Relate
vulnerabilidades de forma privada conforme [SECURITY.md](SECURITY.md). A
participação comunitária segue [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Licença

Codex Insights Local está disponível sob a [licença MIT](LICENSE).

## Aviso de marcas

Este projeto usa “OpenAI” e “Codex” apenas para descrever compatibilidade. Ele
não usa logotipos da OpenAI nem sugere parceria, patrocínio ou endosso oficial.
