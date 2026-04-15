# AI Crypto Trading Bot - Windows-friendly local runner
# Starts/stops:
# - Trading Postgres via docker compose (project root)
# - FastAPI via uvicorn (host process)
# - Telegram bot (host process)
# - Airflow stack via docker compose (airflow/)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 start
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 stop
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 restart
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 status
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 logs api
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_all.ps1 logs bot
#
# Optional env vars:
#   API_HOST         default: 0.0.0.0
#   API_PORT         default: 8000
#   FASTAPI_RELOAD   default: true
#   PYTHON_BIN       optional: full path to python.exe
#
# Notes:
# - If .env exists in project root, this script will try to import KEY=VALUE lines into the current session env.
# - Logs are written to ./run_logs, PID files to ./.run

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Usage {
  @"
Usage: run_all.ps1 <command> [args]

Commands:
  start         Start Postgres (docker), FastAPI (host), Cloudflare Tunnel (host), Telegram bot (host), Airflow (docker)
  stop          Stop Telegram bot, Cloudflare Tunnel, FastAPI, Airflow, Postgres
  restart       Stop then start
  status        Show status
  logs api      Tail FastAPI logs
  logs bot      Tail Telegram bot logs
  logs tunnel   Tail Cloudflare Tunnel logs

Environment (optional):
  API_HOST              Default: 0.0.0.0
  API_PORT              Default: 8000
  FASTAPI_RELOAD        Default: true
  PYTHON_BIN            Force a Python executable (otherwise tries .venv\Scripts\python.exe then python)

  # Cloudflare Tunnel
  CLOUDFLARED_TUNNEL_NAME   Default: ai-crypto-miniapp
  CLOUDFLARED_CONFIG        Default: /etc/cloudflared/config.yml
  CLOUDFLARED_METRICS       Default: 127.0.0.1:20241
  MINIAPP_URL               Optional: used only for display (e.g. https://miniapp.<domain>/miniapp)

"@ | Write-Host
}

function Get-ProjectRoot {
  # scripts/run_all.ps1 -> project root
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Ensure-Directories([string]$ProjectRoot) {
  $runDir = Join-Path $ProjectRoot ".run"
  $logDir = Join-Path $ProjectRoot "run_logs"
  if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
}

function Import-DotEnv([string]$ProjectRoot) {
  $envPath = Join-Path $ProjectRoot ".env"
  if (-not (Test-Path $envPath)) { return }

  # Very simple parser: KEY=VALUE lines, ignores comments and blank lines.
  # Handles quotes minimally (removes surrounding single/double quotes).
  Get-Content $envPath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line) { return }
    if ($line.StartsWith("#")) { return }

    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }

    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()

    if (-not $key) { return }

    if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
      $val = $val.Substring(1, $val.Length - 2)
    }

    # Do not overwrite existing env var unless explicitly present in .env
    # (we do overwrite because .env is the expected source of truth for local dev)
    [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
  }
}

function Resolve-Python([string]$ProjectRoot) {
  if ($env:PYTHON_BIN -and (Test-Path $env:PYTHON_BIN)) {
    return $env:PYTHON_BIN
  }

  $venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
  if (Test-Path $venvPy) { return $venvPy }

  # Fallback to python in PATH
  return "python"
}

function Read-PidFile([string]$PidPath) {
  if (-not (Test-Path $PidPath)) { return $null }
  $raw = (Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
  if (-not $raw) { return $null }
  $raw = $raw.Trim()
  if (-not $raw) { return $null }

  $pid = $null
  if ([int]::TryParse($raw, [ref]$pid)) { return $pid }
  return $null
}

function Write-PidFile([string]$PidPath, [int]$Pid) {
  Set-Content -Path $PidPath -Value $Pid -Encoding ascii
}

function Remove-PidFile([string]$PidPath) {
  if (Test-Path $PidPath) {
    Remove-Item -Force $PidPath -ErrorAction SilentlyContinue | Out-Null
  }
}

function Is-ProcessRunning([int]$Pid) {
  try {
    $p = Get-Process -Id $Pid -ErrorAction Stop
    return $true
  } catch {
    return $false
  }
}

function Stop-ProcessByPidFile([string]$Name, [string]$PidPath) {
  $pid = Read-PidFile $PidPath
  if (-not $pid) {
    Write-Host "[$Name] no pid file; skipping stop"
    return
  }

  if (Is-ProcessRunning $pid) {
    Write-Host "[$Name] stopping (pid=$pid)..."
    try {
      Stop-Process -Id $pid -ErrorAction Stop
    } catch {
      # Might already be exiting
    }

    # Wait a bit then force kill if still alive
    $deadline = (Get-Date).AddSeconds(6)
    while ((Get-Date) -lt $deadline) {
      if (-not (Is-ProcessRunning $pid)) { break }
      Start-Sleep -Milliseconds 200
    }

    if (Is-ProcessRunning $pid) {
      Write-Host "[$Name] force killing (pid=$pid)..."
      try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch {}
    }
  } else {
    Write-Host "[$Name] pid file exists but process not running (pid=$pid)"
  }

  Remove-PidFile $PidPath
}

function Ensure-DockerComposeAvailable {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    throw "docker is not available. Install Docker Desktop (with docker compose v2)."
  }

  # Check "docker compose" works
  $p = Start-Process -FilePath "docker" -ArgumentList @("compose", "version") -NoNewWindow -PassThru -Wait -ErrorAction SilentlyContinue
  if ($p.ExitCode -ne 0) {
    throw "docker compose is not available. Ensure Docker Desktop is installed and 'docker compose' works."
  }
}

function Get-EnvInt([string]$Name, [int]$DefaultValue) {
  $raw = [System.Environment]::GetEnvironmentVariable($Name, "Process")
  if (-not $raw) { return $DefaultValue }

  $val = 0
  if ([int]::TryParse($raw.Trim(), [ref]$val)) { return $val }
  return $DefaultValue
}

function Wait-TcpPort([string]$Host, [int]$Port, [int]$TimeoutSeconds, [string]$Name) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $lastError = $null

  Write-Host ("[health] waiting for {0} tcp {1}:{2} (timeout {3}s)..." -f $Name, $Host, $Port, $TimeoutSeconds)

  while ((Get-Date) -lt $deadline) {
    try {
      $client = New-Object System.Net.Sockets.TcpClient
      $iar = $client.BeginConnect($Host, $Port, $null, $null)
      if ($iar.AsyncWaitHandle.WaitOne(800)) {
        $client.EndConnect($iar)
        $client.Close()
        Write-Host ("[health] {0} tcp is ready" -f $Name)
        return
      }
      $client.Close()
    } catch {
      $lastError = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 500
  }

  throw ("Timeout waiting for {0} tcp {1}:{2}. Last error: {3}" -f $Name, $Host, $Port, $lastError)
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSeconds, [string]$Name) {
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  $last = $null

  Write-Host ("[health] waiting for {0} http {1} (timeout {2}s)..." -f $Name, $Url, $TimeoutSeconds)

  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec 5 -UseBasicParsing
      if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300) {
        Write-Host ("[health] {0} http is ready (status {1})" -f $Name, $resp.StatusCode)
        return
      }
      $last = "HTTP " + $resp.StatusCode
    } catch {
      $last = $_.Exception.Message
    }
    Start-Sleep -Milliseconds 700
  }

  throw ("Timeout waiting for {0} http {1}. Last: {2}" -f $Name, $Url, $last)
}

function Wait-AirflowHealth([int]$TimeoutSeconds) {
  # Airflow exposes a simple health endpoint.
  $url = "http://localhost:8080/health"
  Wait-HttpOk $url $TimeoutSeconds "Airflow"
}

function Wait-ProjectServicesReady([string]$WorkingDir) {
  $timeout = Get-EnvInt "HEALTHCHECK_TIMEOUT_SECONDS" 180

  $leaf = Split-Path -Leaf $WorkingDir
  if ($leaf -eq "airflow") {
    Wait-AirflowHealth $timeout
    return
  }

  # Root compose is trading postgres (exposes 5432 by default)
  $pgPort = Get-EnvInt "POSTGRES_PORT" 5432
  Wait-TcpPort "127.0.0.1" $pgPort $timeout "Trading Postgres"
}

function DockerCompose-Up([string]$WorkingDir) {
  Push-Location $WorkingDir
  try {
    Write-Host "[docker] docker compose up -d ($WorkingDir)"
    & docker compose up -d
  } finally {
    Pop-Location
  }

  # Readiness waits (so 'start' is deterministic and demo-friendly)
  Wait-ProjectServicesReady $WorkingDir
}

function DockerCompose-Down([string]$WorkingDir) {
  Push-Location $WorkingDir
  try {
    Write-Host "[docker] docker compose down ($WorkingDir)"
    & docker compose down
  } finally {
    Pop-Location
  }
}

function Start-FastAPI([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\uvicorn.pid"
  $logPath = Join-Path $ProjectRoot "run_logs\fastapi.log"

  $existing = Read-PidFile $pidPath
  if ($existing -and (Is-ProcessRunning $existing)) {
    Write-Host "[api] already running (pid=$existing)"
    return
  }

  $py = Resolve-Python $ProjectRoot
  $apiHost = if ($env:API_HOST) { $env:API_HOST } else { "0.0.0.0" }
  $apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
  $reload = if ($env:FASTAPI_RELOAD) { $env:FASTAPI_RELOAD } else { "true" }

  $args = @("-m", "uvicorn", "app.api.main:app", "--host", $apiHost, "--port", $apiPort)
  if ($reload.ToLowerInvariant() -eq "true") {
    $args += "--reload"
  }

  Write-Host "[api] starting FastAPI (uvicorn) on ${apiHost}:${apiPort}"
  Write-Host "[api] log: $logPath"

  $p = Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $ProjectRoot -RedirectStandardOutput $logPath -RedirectStandardError $logPath -PassThru -WindowStyle Hidden
  Write-PidFile $pidPath $p.Id
  Write-Host "[api] started (pid=$($p.Id))"

  # Health-check FastAPI readiness (demo-friendly): wait for HTTP + DB connectivity
  $timeout = Get-EnvInt "HEALTHCHECK_TIMEOUT_SECONDS" 180
  Wait-HttpOk ("http://localhost:{0}/" -f $apiPort) $timeout "FastAPI"
  Wait-HttpOk ("http://localhost:{0}/health/db" -f $apiPort) $timeout "FastAPI DB"

}

function Start-TelegramBot([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\telegram_bot.pid"
  $logPath = Join-Path $ProjectRoot "run_logs\telegram_bot.log"

  $existing = Read-PidFile $pidPath
  if ($existing -and (Is-ProcessRunning $existing)) {
    Write-Host "[bot] already running (pid=$existing)"
    return
  }

  $py = Resolve-Python $ProjectRoot

  Write-Host "[bot] starting Telegram bot"
  Write-Host "[bot] log: $logPath"

  $args = @("-m", "app.telegram.bot")
  $p = Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $ProjectRoot -RedirectStandardOutput $logPath -RedirectStandardError $logPath -PassThru -WindowStyle Hidden
  Write-PidFile $pidPath $p.Id
  Write-Host "[bot] started (pid=$($p.Id))"
}

function Start-CloudflaredTunnel([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\cloudflared.pid"
  $logPath = Join-Path $ProjectRoot "run_logs\cloudflared.log"

  $existing = Read-PidFile $pidPath
  if ($existing -and (Is-ProcessRunning $existing)) {
    Write-Host "[tunnel] already running (pid=$existing)"
    return
  }

  $name = if ($env:CLOUDFLARED_TUNNEL_NAME) { $env:CLOUDFLARED_TUNNEL_NAME } else { "ai-crypto-miniapp" }
  $config = if ($env:CLOUDFLARED_CONFIG) { $env:CLOUDFLARED_CONFIG } else { "/etc/cloudflared/config.yml" }

  # Deterministic metrics address to verify the process is up.
  $metrics = if ($env:CLOUDFLARED_METRICS) { $env:CLOUDFLARED_METRICS } else { "127.0.0.1:20241" }

  Write-Host "[tunnel] starting cloudflared tunnel '$name'"
  Write-Host "[tunnel] config: $config"
  Write-Host "[tunnel] metrics: $metrics"
  Write-Host "[tunnel] log: $logPath"

  # Important:
  # - In some packaged builds/versions, 'cloudflared tunnel run' does NOT support flags like --protocol.
  # - Keep the invocation minimal and rely on /etc/cloudflared/config.yml for tunnel + ingress.
  $args = @("tunnel", "--config", $config, "--metrics", $metrics, "run", $name)
  $p = Start-Process -FilePath "cloudflared" -ArgumentList $args -WorkingDirectory $ProjectRoot -RedirectStandardOutput $logPath -RedirectStandardError $logPath -PassThru -WindowStyle Hidden
  Write-PidFile $pidPath $p.Id
  Write-Host "[tunnel] started (pid=$($p.Id))"

  # Readiness: metrics endpoint should respond.
  $timeout = Get-EnvInt "HEALTHCHECK_TIMEOUT_SECONDS" 180
  Wait-HttpOk ("http://{0}/metrics" -f $metrics) $timeout "cloudflared metrics"
}

function Stop-CloudflaredTunnel([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\cloudflared.pid"
  Stop-ProcessByPidFile "tunnel" $pidPath
}

function Stop-FastAPI([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\uvicorn.pid"
  Stop-ProcessByPidFile "api" $pidPath
}

function Stop-TelegramBot([string]$ProjectRoot) {
  $pidPath = Join-Path $ProjectRoot ".run\telegram_bot.pid"
  Stop-ProcessByPidFile "bot" $pidPath
}

function Show-Status([string]$ProjectRoot) {
  Write-Host "== Status =="

  $apiPid = Read-PidFile (Join-Path $ProjectRoot ".run\uvicorn.pid")
  $botPid = Read-PidFile (Join-Path $ProjectRoot ".run\telegram_bot.pid")
  $apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }

  if ($apiPid -and (Is-ProcessRunning $apiPid)) {
    Write-Host "[api] running (pid=$apiPid) http://localhost:$apiPort"
  } else {
    Write-Host "[api] stopped"
  }

  if ($botPid -and (Is-ProcessRunning $botPid)) {
    Write-Host "[bot] running (pid=$botPid)"
  } else {
    Write-Host "[bot] stopped"
  }

  Write-Host "[db] docker compose (root):"
  Push-Location $ProjectRoot
  try { & docker compose ps } catch { Write-Host "  (docker compose ps failed)" }
  Pop-Location

  Write-Host "[airflow] docker compose (airflow/):"
  Push-Location (Join-Path $ProjectRoot "airflow")
  try { & docker compose ps } catch { Write-Host "  (docker compose ps failed)" }
  Pop-Location

  Write-Host ""
  Write-Host "Logs:"
  Write-Host ("  api: " + (Join-Path $ProjectRoot "run_logs\fastapi.log"))
  Write-Host ("  bot: " + (Join-Path $ProjectRoot "run_logs\telegram_bot.log"))
}

function Tail-Logs([string]$ProjectRoot, [string]$Target) {
  $file = $null
  switch ($Target) {
    "api" { $file = Join-Path $ProjectRoot "run_logs\fastapi.log" }
    "bot" { $file = Join-Path $ProjectRoot "run_logs\telegram_bot.log" }
    default {
      throw "Unknown logs target '$Target'. Use: logs api|bot"
    }
  }

  Write-Host "Tailing: $file"
  if (-not (Test-Path $file)) {
    Write-Host "Log file not found yet. Start services first or wait for output..."
  }

  Get-Content -Path $file -Tail 200 -Wait
}

# -------- Main --------
$command = if ($args.Count -ge 1) { $args[0] } else { "" }

$projectRoot = Get-ProjectRoot
Ensure-Directories $projectRoot
Import-DotEnv $projectRoot

# Recommended for DAGs (containers) and local tooling consistency; doesn't affect already-running containers.
if (-not $env:TRADING_API_BASE_URL) {
  $apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
  $env:TRADING_API_BASE_URL = "http://host.docker.internal:$apiPort"
}

switch ($command) {
  "start" {
    Ensure-DockerComposeAvailable
    DockerCompose-Up $projectRoot
    DockerCompose-Up (Join-Path $projectRoot "airflow")

    # FastAPI first (tunnel proxies to it)
    Start-FastAPI $projectRoot

    # Cloudflare Tunnel for Mini App (DISABLED: start it manually if needed)
    # try {
    #   Start-CloudflaredTunnel $projectRoot
    # } catch {
    #   Write-Host "[tunnel] failed to start or pass health-check. Mini App may not work until tunnel connects."
    #   Write-Host ("[tunnel] error: " + $_.Exception.Message)
    # }

    Start-TelegramBot $projectRoot

    $apiPort = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
    Write-Host ""
    Write-Host "== Started =="
    Write-Host "FastAPI:    http://localhost:$apiPort"
    Write-Host "Swagger:    http://localhost:$apiPort/docs"
    Write-Host "Airflow UI: http://localhost:8080"
    if ($env:MINIAPP_URL) {
      Write-Host ("Mini App:  " + $env:MINIAPP_URL)
    } else {
      Write-Host "Mini App:  (set MINIAPP_URL to show it here)"
    }
    Write-Host ""
    Write-Host "To stop: .\scripts\run_all.ps1 stop"
  }
  "stop" {
    Stop-TelegramBot $projectRoot
    # Stop-CloudflaredTunnel $projectRoot  # DISABLED: stop it manually if needed
    Stop-FastAPI $projectRoot
    DockerCompose-Down (Join-Path $projectRoot "airflow")
    DockerCompose-Down $projectRoot
    Write-Host "== Stopped =="
  }
  "restart" {
    & $PSCommandPath stop
    & $PSCommandPath start
  }
  "status" {
    Show-Status $projectRoot
  }
  "logs" {
    if ($args.Count -lt 2) { throw "Missing logs target. Use: logs api|bot" }
    Tail-Logs $projectRoot $args[1]
  }
  "" { Show-Usage }
  "-h" { Show-Usage }
  "--help" { Show-Usage }
  "help" { Show-Usage }
  default {
    Write-Host "Unknown command: $command"
    Write-Host ""
    Show-Usage
    exit 1
  }
}
