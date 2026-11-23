# 从解包的原版语音里，为每个 voice type 挑一段干净的参考音
#   powershell -File extract_voice_refs.ps1 [-Extracted G:\v2] [-OutDir G:\qwen-tts\voices]
param(
    [string]$Extracted = 'G:\v2',
    [string]$OutDir = 'G:\qwen-tts\voices',
    [string]$Ffmpeg,
    [string]$Ffprobe
)

$ErrorActionPreference = 'Stop'
if (-not $Ffmpeg) {
    $Ffmpeg = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue |
        Select-Object -First 1 -Expand FullName
}
if (-not $Ffmpeg) { throw 'ffmpeg not found; install with: winget install Gyan.FFmpeg' }
if (-not $Ffprobe) { $Ffprobe = Join-Path (Split-Path $Ffmpeg -Parent) 'ffprobe.exe' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$voiceRoots = Get-ChildItem -LiteralPath (Join-Path $Extracted 'sound\voice') -Directory | Sort-Object Name
$types = foreach ($root in $voiceRoots) { Get-ChildItem -LiteralPath $root.FullName -Directory }
$types = $types | Sort-Object Name -Unique
$report = @()

foreach ($type in $types) {
    $name = $type.Name.ToLowerInvariant()
    $dest = Join-Path $OutDir "$name.wav"
    if (Test-Path -LiteralPath $dest) { continue }

    # 只取真正的台词文件（任务__FormID_序号），避开吼叫/受伤等
    $cands = Get-ChildItem -LiteralPath $type.FullName -File -Filter '*.fuz' |
        Where-Object { $_.Name -match '__[0-9a-fA-F]{8}_\d+\.fuz$' -and $_.Length -ge 14KB -and $_.Length -le 400KB } |
        Sort-Object Length -Descending | Select-Object -First 24

    $done = $false
    foreach ($f in $cands) {
        $bytes = [IO.File]::ReadAllBytes($f.FullName)
        if ($bytes.Length -lt 20 -or [Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne 'FUZE') { continue }
        $lip = [BitConverter]::ToUInt32($bytes, 8)
        $off = 12 + $lip
        if ($off -ge $bytes.Length) { continue }
        $tmp = Join-Path $env:TEMP ("ref_" + [guid]::NewGuid().ToString('N'))
        [IO.File]::WriteAllBytes("$tmp.xwm", $bytes[$off..($bytes.Length - 1)])
        & $Ffmpeg -hide_banner -loglevel error -y -i "$tmp.xwm" -ar 24000 -ac 1 -c:a pcm_s16le "$tmp.wav" 2>$null
        if (-not (Test-Path "$tmp.wav")) { Remove-Item "$tmp.xwm" -Force -ErrorAction SilentlyContinue; continue }
        $dur = [double](& $Ffprobe -v error -show_entries format=duration -of csv=p=0 "$tmp.wav")
        if ($dur -ge 5 -and $dur -le 15) {
            Move-Item -LiteralPath "$tmp.wav" -Destination $dest -Force
            $report += [pscustomobject]@{ VoiceType = $type.Name; Seconds = [math]::Round($dur, 1); Source = $f.Name }
            $done = $true
        }
        Remove-Item "$tmp.xwm" -Force -ErrorAction SilentlyContinue
        Remove-Item "$tmp.wav" -Force -ErrorAction SilentlyContinue
        if ($done) { break }
    }
    if (-not $done) { $report += [pscustomobject]@{ VoiceType = $type.Name; Seconds = 0; Source = '(no clean clip found)' } }
}

$report | Format-Table -AutoSize | Out-String -Width 120
"wav written: $((Get-ChildItem -LiteralPath $OutDir -Filter *.wav).Count)"
