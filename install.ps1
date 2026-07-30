$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$AppHome = Join-Path $HOME ".local\share\codex-insights"
$BinHome = Join-Path $HOME ".local\bin"
$SkillHome = Join-Path $CodexHome "skills\codex-insights"
New-Item -ItemType Directory -Force -Path $AppHome, $BinHome, $SkillHome | Out-Null
Copy-Item (Join-Path $Root "codex_insights.py") (Join-Path $AppHome "codex_insights.py") -Force
Copy-Item (Join-Path $Root "skill\SKILL.md") (Join-Path $SkillHome "SKILL.md") -Force
$UsageHome = Join-Path $CodexHome "usage-data"
New-Item -ItemType Directory -Force -Path $UsageHome | Out-Null
@"
@echo off
python "%USERPROFILE%\.local\share\codex-insights\codex_insights.py" %*
"@ | Set-Content -Encoding ASCII (Join-Path $BinHome "codex-insights.cmd")
@"
@echo off
if "%~1"=="" (echo Uso: codex-profile profile [args] 1>&2 & exit /b 2)
set PROFILE=%~1
shift
codex-insights launch %PROFILE% %*
"@ | Set-Content -Encoding ASCII (Join-Path $BinHome "codex-profile.cmd")
Write-Host "Codex Insights instalado em $AppHome"
Write-Host "Adicione $BinHome ao PATH."
Write-Host "Relatório: codex-insights report --days 30"
Write-Host 'No Codex: $codex-insights days=30'
Write-Host "Para mapear logs antigos de MCP, salve /mcp verbose em $CodexHome\usage-data\mcp-verbose.txt"
Write-Host "Ou use: codex-insights report --mcp-verbose-file <arquivo>"
