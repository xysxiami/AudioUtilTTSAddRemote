# 跟游戏同生共死：启动游戏前拉起 F5 服务，游戏退出后关掉它。
# MO2 里添加为可执行程序：
#   程序：pwsh.exe
#   参数：-NoProfile -File E:\code\other\play_with_f5.ps1
# 服务与游戏同时启动（不阻塞游戏加载），退出游戏后只关本次拉起的服务。
param(
    [string]$GameDir = 'G:\iniRePather-Skyrim\StockGame',
    [string]$ServerScript = 'E:\code\other\run_f5_server.ps1',
    [string]$HealthUrl = 'http://127.0.0.1:9880/health'
)

$ErrorActionPreference = 'Continue'
$log = 'G:\f5\play.log'
function Say($m) {
    $ts = Get-Date -Format 'HH:mm:ss'
    Add-Content -LiteralPath $log -Value "[$ts] $m"
    Write-Host "[$ts] $m"
}

function ServerUp {
    try { $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2; return $r.StatusCode -eq 200 } catch { return $false }
}

$ownServer = $null
if (ServerUp) {
    Say 'server already running, reusing it'
} else {
    Say 'starting F5 server (in parallel with the game)'
    $ownServer = Start-Process -FilePath 'pwsh' -ArgumentList '-NoProfile', '-File', $ServerScript -WindowStyle Hidden -PassThru
}

$loader = Join-Path $GameDir 'skse64_loader.exe'
if (-not (Test-Path $loader)) { Say "missing $loader"; exit 1 }
Say 'launching skse64_loader'
Start-Process -FilePath $loader -WorkingDirectory $GameDir

$game = $null
for ($i = 0; $i -lt 150; $i++) {
    Start-Sleep -Seconds 2
    $game = Get-Process SkyrimSE -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($game) { Say "game running pid=$($game.Id)"; break }
}
if ($game) {
    $game.WaitForExit()
    Say 'game exited'
} else {
    Say 'game did not start; stopping our server'
}

if ($ownServer) {
    Say 'stopping F5 server'
    $children = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*server_f5_tts.py*' }
    foreach ($c in $children) { Stop-Process -Id $c.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $ownServer.Id -Force -ErrorAction SilentlyContinue
    Say 'server stopped'
}
