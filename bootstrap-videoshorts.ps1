# Первичная настройка VideoShorts для новых пользователей.
# Из корня плагина: .\bootstrap-videoshorts.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ensure = Join-Path $here "scripts\ensure_dependencies.py"

Write-Host "VideoShorts bootstrap: проверка и установка зависимостей..." -ForegroundColor Cyan

if (-not (Test-Path $ensure)) {
  throw "Не найден scripts/ensure_dependencies.py"
}

python --version | Out-Host
python $ensure --install
if ($LASTEXITCODE -ne 0) {
  Write-Host "Не все зависимости установлены автоматически." -ForegroundColor Yellow
  Write-Host "Если Python < 3.10 — установите Python 3.10+ с https://www.python.org/downloads/" -ForegroundColor Yellow
  Write-Host "Если FFmpeg не в PATH — перезапустите терминал после winget install Gyan.FFmpeg" -ForegroundColor Yellow
  exit $LASTEXITCODE
}

Write-Host "Зависимости готовы. Можно запускать .\open-videoshorts-ui.ps1" -ForegroundColor Green
