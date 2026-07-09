# Installs VideoShorts plugin to Cursor local plugins folder.
# From plugin root: .\install-plugin.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $env:USERPROFILE ".cursor\plugins\local\videoshorts"

Write-Host "VideoShorts: copying..." -ForegroundColor Cyan
Write-Host "  from: $here"
Write-Host "  to:   $dest"

if (Test-Path $dest) {
  try {
    Remove-Item -Path $dest -Recurse -Force
  } catch {
    Write-Host "  destination is busy; using overlay copy without removing root" -ForegroundColor Yellow
  }
}
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path (Join-Path $here "*") -Destination $dest -Recurse -Force

$ver = (Get-Content (Join-Path $here '.cursor-plugin\plugin.json') -Raw | ConvertFrom-Json).version

# Task subagents → user + project .cursor/agents
$agentSrc = Join-Path $here "agents"
$taskUser = Join-Path $env:USERPROFILE ".cursor\agents"
New-Item -ItemType Directory -Force -Path $taskUser | Out-Null
Copy-Item -Path (Join-Path $agentSrc "videoshorts*.md") -Destination $taskUser -Force
Write-Host "Task subagents (user): $taskUser" -ForegroundColor Cyan

$taskProj = Join-Path $here ".cursor\agents"
New-Item -ItemType Directory -Force -Path $taskProj | Out-Null
Copy-Item -Path (Join-Path $agentSrc "videoshorts*.md") -Destination $taskProj -Force
Write-Host "Task subagents (project): $taskProj" -ForegroundColor Cyan

$taskPlugin = Join-Path $dest ".cursor\agents"
New-Item -ItemType Directory -Force -Path $taskPlugin | Out-Null
Copy-Item -Path (Join-Path $agentSrc "videoshorts*.md") -Destination $taskPlugin -Force
Write-Host "Task subagents (plugin): $taskPlugin" -ForegroundColor Cyan

# Canvas files → Cursor project canvases directory
$canvasSrc = Join-Path $here "canvases"
if (Test-Path $canvasSrc) {
  $projectRoot = (Resolve-Path $here).Path
  $projectSlugRaw = ($projectRoot -replace ':', '' -replace '[\\/ ]+', '-')
  $projectSlug = $projectSlugRaw.Substring(0, 1).ToLower() + $projectSlugRaw.Substring(1)
  $canvasDest = Join-Path $env:USERPROFILE ".cursor\projects\$projectSlug\canvases"
  New-Item -ItemType Directory -Force -Path $canvasDest | Out-Null
  Copy-Item -Path (Join-Path $canvasSrc "*.canvas.tsx") -Destination $canvasDest -Force
  Write-Host "Canvases (project): $canvasDest" -ForegroundColor Cyan
}

$uploadHtml = Join-Path $here "ui\videoshorts-upload.html"
$resultsHtml = Join-Path $here "ui\videoshorts-results.html"
if (Test-Path $uploadHtml) {
  Write-Host "Local HTML upload:  $uploadHtml" -ForegroundColor Cyan
}
if (Test-Path $resultsHtml) {
  Write-Host "Local HTML results: $resultsHtml" -ForegroundColor Cyan
}

Write-Host "Done. Restart Cursor to load plugin v$ver." -ForegroundColor Green
Write-Host "First run: .\bootstrap-videoshorts.ps1" -ForegroundColor Cyan
Write-Host "Docs: README.md" -ForegroundColor DarkGray
