param(
  [switch]$All,
  [int[]]$Ports,
  [switch]$NoWorker,
  [switch]$DryRun,
  [switch]$NoKillBrowsers
)

$BrowserNames = @('chromedriver.exe','msedgedriver.exe','chrome.exe','msedge.exe','chrome-headless-shell.exe')

function Read-ApiUrlsFromEnv {
  param([string]$EnvPath)
  if (!(Test-Path $EnvPath)) { return @() }
  $line = Select-String -Path $EnvPath -Pattern '^API_SERVER_URLS=' | Select-Object -First 1
  if (!$line) { return @() }
  $raw = $line.Line.Split('=')[1].Trim().Trim('"')
  return $raw -split ','
}

function Find-ApiProcesses {
  param([int[]]$PortsFilter)
  $procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match '-m\s+uvicorn' -and $_.CommandLine -match 'api_carteirinhas:app'
  }
  if ($PortsFilter -and $PortsFilter.Count -gt 0) {
    $procs = $procs | Where-Object {
      $cmd = $_.CommandLine
      foreach ($p in $PortsFilter) {
        if ($cmd -match "--port\s+$p(\s|$)") { return $true }
      }
      return $false
    }
  }
  return $procs
}

function Find-WorkerProcesses {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'worker_carteirinhas\.py' }
}

function Get-ProcessesByPidList {
  param([int[]]$PidList)
  if (!$PidList -or $PidList.Count -eq 0) { return @() }
  $all = Get-CimInstance Win32_Process
  return $all | Where-Object { $PidList -contains $_.ProcessId }
}

function Read-PidFileItems {
  param([string]$PidFile)
  if (!(Test-Path $PidFile)) { return @() }
  try { Get-Content -Path $PidFile -Raw | ConvertFrom-Json } catch { return @() }
}

function Find-BrowserChildren {
  param([int]$RootPid)
  $all = Get-CimInstance Win32_Process
  $direct = $all | Where-Object { $_.ParentProcessId -eq $RootPid -and ($BrowserNames -contains $_.Name) }
  $drivers = $direct | Where-Object { $_.Name -in @('chromedriver.exe','msedgedriver.exe') }
  $grand = @()
  foreach ($d in $drivers) {
    $grand += $all | Where-Object { $_.ParentProcessId -eq $d.ProcessId -and $_.Name -in @('chrome.exe','msedge.exe','chrome-headless-shell.exe') }
  }
  $combined = @()
  $combined += $direct
  $combined += $grand
  return $combined | Sort-Object -Property ProcessId -Unique
}

function Stop-Targets {
  param([array]$Targets, [string]$Label, [switch]$DryRun)
  foreach ($t in $Targets) {
    if ($DryRun) {
      Write-Host ("[dry-run] Stop {0} -- PID {1} CMD={2}" -f $Label, $t.ProcessId, $t.CommandLine)
    } else {
      try { Stop-Process -Id $t.ProcessId -Force -ErrorAction Stop; Write-Host ("[ok] {0} encerrado => PID {1}" -f $Label, $t.ProcessId) }
      catch { Write-Host ("[skip] Falha ao encerrar {0} PID {1}: {2}" -f $Label, $t.ProcessId, $_.Exception.Message) }
    }
  }
}

Write-Host (">> Encerrando serviços (All={0}, Ports={1}, NoWorker={2}, DryRun={3}, NoKillBrowsers={4})..." -f [bool]$All, (($Ports) -join ','), [bool]$NoWorker, [bool]$DryRun, [bool]$NoKillBrowsers)

# 1) Carregar PIDs do arquivo (para selecionar exatamente o que foi iniciado pelo start_services)
$pidFile = Join-Path $PSScriptRoot 'services_pids.json'
$items = Read-PidFileItems -PidFile $pidFile
$pidApis = @($items | Where-Object { $_.type -eq 'api' } | ForEach-Object { [int]$_.pid })
$pidWorkers = @($items | Where-Object { $_.type -eq 'worker' } | ForEach-Object { [int]$_.pid })

# 2) Determinar portas alvo, se não veio via parâmetro e não é -All
$portsToStop = @()
if ($Ports -and $Ports.Count -gt 0) {
  $portsToStop = $Ports
} elseif (-not $All) {
  $urls = Read-ApiUrlsFromEnv -EnvPath (Join-Path $PSScriptRoot '.env')
  $portsToStop = $urls | ForEach-Object { try { ([Uri]$_).Port } catch { $null } } | Where-Object { $_ }
}

# 3) Coletar processos de API e Worker (união de scanning + PIDs do arquivo)
$apiProcs = @()
$apiProcs += Find-ApiProcesses -PortsFilter $portsToStop
$apiProcs += Get-ProcessesByPidList -PidList $pidApis
$apiProcs = $apiProcs | Sort-Object -Property ProcessId -Unique

$workerProcs = @()
if (-not $NoWorker) {
  $workerProcs += Find-WorkerProcesses
  $workerProcs += Get-ProcessesByPidList -PidList $pidWorkers
  $workerProcs = $workerProcs | Sort-Object -Property ProcessId -Unique
}

Write-Host ">> Identificados: APIs=$($apiProcs.Count), Workers=$($workerProcs.Count)"

# 4) Encerrar navegadores vinculados aos processos identificados (primeiro)
if (-not $NoKillBrowsers) {
  $browserTargets = @()
  foreach ($p in $apiProcs) { $browserTargets += Find-BrowserChildren -RootPid $p.ProcessId }
  foreach ($p in $workerProcs) { $browserTargets += Find-BrowserChildren -RootPid $p.ProcessId }
  $browserTargets = $browserTargets | Sort-Object -Property ProcessId -Unique
  if ($browserTargets.Count -gt 0) {
    Write-Host ">> Encerrando navegadores vinculados: $($browserTargets.Count)"
    Stop-Targets -Targets $browserTargets -Label 'Browser' -DryRun:$DryRun
  } else {
    Write-Host ">> Nenhum navegador vinculado detectado."
  }
}

# 5) Se for dry-run, apenas mostrar plano para APIs/Workers
if ($DryRun) {
  Stop-Targets -Targets $apiProcs -Label 'API' -DryRun:$true
  Stop-Targets -Targets $workerProcs -Label 'Worker' -DryRun:$true
  Write-Host ">> Dry-run concluído. Nenhum processo foi encerrado."
  return
}

# 6) Encerrar APIs e depois Workers
Stop-Targets -Targets $apiProcs -Label 'API' -DryRun:$false
Stop-Targets -Targets $workerProcs -Label 'Worker' -DryRun:$false

Write-Host (">> Encerramento concluído. APIs={0}, Workers={1}." -f $apiProcs.Count, $workerProcs.Count)