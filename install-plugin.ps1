# Installs Hyperion (Гиперион) plugin to Cursor local plugins folder.
# From plugin root: .\install-plugin.ps1
#
# IMPORTANT: cookies / Playwright storage_state live in
#   videoshorts-memory/secrets/*.json
# They are gitignored and MUST survive reinstall. This script stashes them
# from legacy VideoShorts + existing Hyperion BEFORE any Remove-Item,
# then restores into the new install (same as keeping Dzen cookies).

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $env:USERPROFILE ".cursor\plugins\local\hyperion"
$legacyDest = Join-Path $env:USERPROFILE ".cursor\plugins\local\videoshorts"
$stashRoot = Join-Path $env:TEMP ("hyperion-install-stash-" + [guid]::NewGuid().ToString("N"))
$stashSecrets = Join-Path $stashRoot "secrets"
$stashEnv = Join-Path $stashRoot "env"

function Get-SecretsDir([string]$pluginRoot) {
  Join-Path $pluginRoot "videoshorts-memory\secrets"
}

function Save-CookieFiles([string]$pluginRoot, [string]$label) {
  $src = Get-SecretsDir $pluginRoot
  if (-not (Test-Path $src)) {
    Write-Host "  [$label] secrets: none" -ForegroundColor DarkGray
    return 0
  }
  New-Item -ItemType Directory -Force -Path $stashSecrets | Out-Null
  $saved = 0
  Get-ChildItem -Path $src -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne ".gitkeep" } |
    ForEach-Object {
      $target = Join-Path $stashSecrets $_.Name
      $shouldCopy = $true
      if (Test-Path $target) {
        $prev = Get-Item $target
        # Keep newer cookie file; if same time, keep larger (more cookies).
        if ($prev.LastWriteTime -gt $_.LastWriteTime) {
          $shouldCopy = $false
        } elseif ($prev.LastWriteTime -eq $_.LastWriteTime -and $prev.Length -ge $_.Length) {
          $shouldCopy = $false
        }
      }
      if ($shouldCopy) {
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        $saved++
        Write-Host "  [$label] saved cookie: $($_.Name) ($([math]::Round($_.Length/1KB,1)) KB)" -ForegroundColor DarkGray
      } else {
        Write-Host "  [$label] keep newer stash: $($_.Name)" -ForegroundColor DarkGray
      }
    }

  $envFile = Join-Path $pluginRoot "videoshorts.local.env"
  if (Test-Path $envFile) {
    New-Item -ItemType Directory -Force -Path $stashEnv | Out-Null
    $envTarget = Join-Path $stashEnv "videoshorts.local.env"
    if (-not (Test-Path $envTarget) -or (Get-Item $envFile).LastWriteTime -ge (Get-Item $envTarget).LastWriteTime) {
      Copy-Item -LiteralPath $envFile -Destination $envTarget -Force
      Write-Host "  [$label] saved videoshorts.local.env" -ForegroundColor DarkGray
    }
  }
  return $saved
}

function Restore-CookieFiles([string]$pluginRoot) {
  $destSecrets = Get-SecretsDir $pluginRoot
  New-Item -ItemType Directory -Force -Path $destSecrets | Out-Null
  if (-not (Test-Path (Join-Path $destSecrets ".gitkeep"))) {
    Set-Content -Path (Join-Path $destSecrets ".gitkeep") -Value "" -Encoding ascii
  }

  $restored = 0
  if (Test-Path $stashSecrets) {
    Get-ChildItem -Path $stashSecrets -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $destSecrets $_.Name) -Force
      $restored++
      Write-Host "  restored cookie: $($_.Name)" -ForegroundColor Green
    }
  }

  $envStash = Join-Path $stashEnv "videoshorts.local.env"
  if (Test-Path $envStash) {
    Copy-Item -LiteralPath $envStash -Destination (Join-Path $pluginRoot "videoshorts.local.env") -Force
    Write-Host "  restored videoshorts.local.env" -ForegroundColor Green
  }
  return $restored
}

Write-Host "Hyperion: copying..." -ForegroundColor Cyan
Write-Host "  from: $here"
Write-Host "  to:   $dest"
Write-Host "  stash: $stashRoot" -ForegroundColor DarkGray

# 1) Stash cookies BEFORE any delete (existing Hyperion first, then legacy VideoShorts).
Write-Host "Preserving publish cookies (Dzen/VK/RuTube/TikTok)..." -ForegroundColor Cyan
[void](Save-CookieFiles -pluginRoot $dest -label "hyperion")
[void](Save-CookieFiles -pluginRoot $legacyDest -label "legacy-videoshorts")
# Also keep cookies from the package source if someone committed/copied them locally.
[void](Save-CookieFiles -pluginRoot $here -label "package-source")

$stashedCount = 0
if (Test-Path $stashSecrets) {
  $stashedCount = @(Get-ChildItem $stashSecrets -File -Force -ErrorAction SilentlyContinue).Count
}
Write-Host "  cookie files stashed: $stashedCount" -ForegroundColor Cyan

# 2) Remove legacy VideoShorts only after stash.
if (Test-Path $legacyDest) {
  try {
    Remove-Item -Path $legacyDest -Recurse -Force
    Write-Host "  removed legacy plugin folder: $legacyDest" -ForegroundColor DarkGray
  } catch {
    Write-Host "  legacy folder busy (ok to ignore): $legacyDest" -ForegroundColor Yellow
  }
}

# 3) Replace Hyperion install tree (cookies already stashed).
if (Test-Path $dest) {
  try {
    Remove-Item -Path $dest -Recurse -Force
  } catch {
    Write-Host "  destination is busy; overlay copy without removing root" -ForegroundColor Yellow
  }
}
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path (Join-Path $here "*") -Destination $dest -Recurse -Force

# 4) Put cookies back — always wins over empty package secrets/.
Write-Host "Restoring publish cookies into Hyperion..." -ForegroundColor Cyan
$restored = Restore-CookieFiles -pluginRoot $dest
Write-Host "  cookie files restored: $restored" -ForegroundColor Cyan

# 4b) Ensure Playwright monitor defaults in local env (user #1 = rightmost)
function Ensure-PlaywrightMonitorEnv([string]$pluginRoot) {
  $envPath = Join-Path $pluginRoot "videoshorts.local.env"
  $examplePath = Join-Path $pluginRoot "videoshorts.local.env.example"
  $block = @"

# Playwright window: user display #1 = rightmost, #2 = primary/main, #3 = top
PLAYWRIGHT_MONITOR=1
PLAYWRIGHT_MONITOR_LAYOUT=1:right,2:primary,3:top
"@
  foreach ($path in @($envPath, $examplePath, (Join-Path $pluginRoot "videoshorts.env.example"))) {
    if (-not (Test-Path $path)) {
      if ($path -eq $envPath) {
        Set-Content -Path $path -Value $block.TrimStart() -Encoding UTF8
        Write-Host "  created $([IO.Path]::GetFileName($path)) with PLAYWRIGHT_MONITOR=1" -ForegroundColor Green
      }
      continue
    }
    $text = Get-Content -Path $path -Raw -ErrorAction SilentlyContinue
    if ($null -eq $text) { $text = "" }
    if ($text -notmatch "(?m)^PLAYWRIGHT_MONITOR=") {
      Add-Content -Path $path -Value $block -Encoding UTF8
      Write-Host "  appended PLAYWRIGHT_MONITOR to $([IO.Path]::GetFileName($path))" -ForegroundColor Green
    } else {
      $text2 = [regex]::Replace($text, '(?m)^PLAYWRIGHT_MONITOR=.*$', 'PLAYWRIGHT_MONITOR=1')
      if ($text2 -notmatch '(?m)^PLAYWRIGHT_MONITOR_LAYOUT=') {
        $text2 = $text2.TrimEnd() + "`r`nPLAYWRIGHT_MONITOR_LAYOUT=1:right,2:primary,3:top`r`n"
      }
      Set-Content -Path $path -Value $text2 -Encoding UTF8
      Write-Host "  ensured PLAYWRIGHT_MONITOR=1 in $([IO.Path]::GetFileName($path))" -ForegroundColor DarkGray
    }
  }
}
Ensure-PlaywrightMonitorEnv -pluginRoot $dest
Ensure-PlaywrightMonitorEnv -pluginRoot $here

# Cleanup stash
try {
  Remove-Item -Path $stashRoot -Recurse -Force -ErrorAction SilentlyContinue
} catch {
  Write-Host "  stash cleanup skipped: $stashRoot" -ForegroundColor Yellow
}

$ver = (Get-Content (Join-Path $here ".cursor-plugin\plugin.json") -Raw | ConvertFrom-Json).version

# Task subagents -> user + project .cursor/agents
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

# Canvas files -> Cursor project canvases directory
$canvasSrc = Join-Path $here "canvases"
if (Test-Path $canvasSrc) {
  $projectRoot = (Resolve-Path $here).Path
  $projectSlugRaw = ($projectRoot -replace ":", "" -replace "[\\/ ]+", "-")
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
Write-Host "Cookies path: $dest\videoshorts-memory\secrets\" -ForegroundColor Cyan
Write-Host "First run: .\bootstrap-videoshorts.ps1" -ForegroundColor Cyan
Write-Host "Docs: README.md" -ForegroundColor DarkGray
