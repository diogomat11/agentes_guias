param(
  [int]$Count = 3,
  [switch]$Reload,
  [switch]$NoWorker,
  [int]$WarmupSeconds = 3
)

function Get-PythonPath {
  if (Test-Path ".\.venv\Scripts\python.exe") { return ".\.venv\Scripts\python.exe" }
  $py = (Get-Command python -ErrorAction SilentlyContinue)
  if ($py) { return $py.Source }
  throw "Python não encontrado. Configure o .venv ou instale Python."
}

function Get-ApiUrls {
  param([string]$EnvPath)
  if (!(Test-Path $EnvPath)) { throw "Arquivo .env não encontrado em $EnvPath" }
  $line = Select-String -Path $EnvPath -Pattern '^API_SERVER_URLS=' | Select-Object -First 1
  if (!$line) { throw "API_SERVER_URLS não encontrado no .env" }
  $raw = $line.Line.Split('=')[1].Trim().Trim('"')
  return $raw -split ','
}

function Start-ApiServer {
  param([string]$Url, [string]$PythonPath, [switch]$Reload)
  $uri = [Uri]$Url
  $args = "-m uvicorn api_carteirinhas:app --host $($uri.Host) --port $($uri.Port) --log-level info"
  if ($Reload) { $args += " --reload" }
  $proc = Start-Process -FilePath $PythonPath -ArgumentList $args -PassThru -WindowStyle Hidden
  return $proc
}

function Test-Port {
  param([string]$Hostname,[int]$Port)
  try {
    return (Test-NetConnection -ComputerName $Hostname -Port $Port -InformationLevel Quiet)
  } catch { return $false }
}

function Ping-Api {
  param([string]$Url)
  try {
     $res = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
     return $res.StatusCode -eq 200
  } catch { return $false }
}

function Start-Worker {
  param([string]$PythonPath)
  $proc = Start-Process -FilePath $PythonPath -ArgumentList "worker_carteirinhas.py" -PassThru -WindowStyle Hidden
  return $proc
}

Write-Host ">> Iniciando serviços (API x$Count + Worker: $([bool](-not $NoWorker)))..."

$python = Get-PythonPath
$urls = Get-ApiUrls -EnvPath (Join-Path $PSScriptRoot ".env")
$selected = $urls | Select-Object -First $Count

$procs = @()

# Start APIs
foreach ($u in $selected) {
  $uri = [Uri]$u
  if (Test-Port -Hostname $uri.Host -Port $uri.Port) {
    Write-Host " - Porta $($uri.Port) já em uso; pulando $u"
    continue
  }
  $p = Start-ApiServer -Url $u -PythonPath $python -Reload:$Reload
  Write-Host " - Iniciado $u (PID $($p.Id))"
  $procs += @{ type="api"; url=$u; pid=$p.Id }
}

# Start Worker
if (-not $NoWorker) {
  $wp = Start-Worker -PythonPath $python
  Write-Host " - Worker iniciado (PID $($wp.Id))"
  $procs += @{ type="worker"; pid=$wp.Id }
}

Start-Sleep -Seconds $WarmupSeconds

# Indicator summary
$active = 0
foreach ($u in $selected) {
  if (Ping-Api "$u/") { $active++ }
}

Write-Host ">> Servidores ativos: $active de $($selected.Count)"
Write-Host ">> Detalhes de processos:"
$procs | ForEach-Object {
  if ($_.type -eq "api") { Write-Host ("   API {0} => PID {1}" -f $_.url, $_.pid) }
  else { Write-Host ("   Worker => PID {0}" -f $_.pid) }
}

# Persistir PIDs em arquivo para stop_services.ps1
try {
  $pidPath = Join-Path $PSScriptRoot "services_pids.json"
  $json = $procs | ConvertTo-Json -Depth 3
  Set-Content -Path $pidPath -Value $json -Encoding UTF8
  Write-Host ("PIDs gravados em {0}" -f $pidPath)
} catch {
  Write-Host ("Falha ao gravar PIDs: {0}" -f $_.Exception.Message)
}

Write-Host "Pronto. Use .\\SCRIPTS\\stop_services.ps1 ou Stop-Process pelos PIDs."