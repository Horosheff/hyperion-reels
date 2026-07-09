# Starts the local VideoShorts HTML bridge.
# Default UI mode is Agent: save READY_FOR_AGENT for Cursor Director.
# Direct run_pipeline.py is available only as local diagnostic fallback.
# From plugin root: .\open-videoshorts-ui.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $here "scripts\ui_server.py"
$url = "http://127.0.0.1:8765/"

if (-not (Test-Path $server)) {
  throw "VideoShorts UI server not found: $server"
}

try {
  Invoke-WebRequest -Uri ($url + "api/status") -UseBasicParsing -TimeoutSec 1 | Out-Null
  Invoke-WebRequest -Uri ($url + "api/new-session") -UseBasicParsing -TimeoutSec 2 | Out-Null
  Start-Process $url
  exit 0
} catch {
  # No running bridge on the default port — start a new one.
}

$memory = Join-Path $here "videoshorts-memory"
$output = Join-Path $memory "output"
$runRequest = Join-Path $memory "run-request.json"
$runStatus = Join-Path $output "run-status.json"
$brief = Join-Path $memory "00-brief.md"
$handoffDir = Join-Path $here ".cursor"
$handoff = Join-Path $handoffDir "videoshorts-handoff.md"
New-Item -ItemType Directory -Path $output -Force | Out-Null
New-Item -ItemType Directory -Path $handoffDir -Force | Out-Null
if (Test-Path $runRequest) { Remove-Item $runRequest -Force }
$createdAt = (Get-Date).ToString("s")
@"
{
  "status": "WAITING_FOR_UPLOAD",
  "run_mode": "agent",
  "created_at": "$createdAt",
  "reason": "new_ui_session",
  "message": "Откройте UI, выберите новый файл и нажмите OK — передать Cursor Director."
}
"@ | Set-Content -Path $runStatus -Encoding UTF8
@"
# VideoShorts brief

created_at: $createdAt
status: WAITING_FOR_UPLOAD
video_path: (not selected)
"@ | Set-Content -Path $brief -Encoding UTF8
@"
# VideoShorts — новая сессия

status: WAITING_FOR_UPLOAD
director_action: ждать новый READY_FOR_AGENT из UI, не использовать старые run-request/latest-results
"@ | Set-Content -Path $handoff -Encoding UTF8

Start-Process -FilePath "python" -ArgumentList @("`"$server`"", "--open") -WorkingDirectory $here
