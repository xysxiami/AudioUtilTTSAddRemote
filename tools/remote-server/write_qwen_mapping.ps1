param(
    [string]$Extracted = 'G:\v2',
    [string]$Voices = 'G:\qwen-tts\voices',
    [string]$Mod = 'G:\iniRePather-Skyrim\mods\AudioUtilTTS 195673 0.7.2 2026'
)
$ErrorActionPreference = 'Stop'

$types = @{}
Get-ChildItem -LiteralPath (Join-Path $Extracted 'sound\voice') -Directory | ForEach-Object {
    Get-ChildItem -LiteralPath $_.FullName -Directory | ForEach-Object { $types[$_.Name.ToLowerInvariant()] = $_.Name }
}
$have = @{}
Get-ChildItem -LiteralPath $Voices -Filter *.wav | ForEach-Object { $have[$_.BaseName.ToLowerInvariant()] = $true }
$mapped = $types.Keys | Where-Object { $have.ContainsKey($_) } | Sort-Object

$presetDir = Join-Path $Mod 'SKSE\Plugins\AudioUtilTTS\presets'
New-Item -ItemType Directory -Force -Path $presetDir | Out-Null
$pl = @('# 由 write_qwen_mapping.ps1 生成：每个 voice type 指向 qwen-remote 的同名参考音', '')
foreach ($k in $mapped) {
    $pl += "[preset.qwen_$k]"
    $pl += 'model = "qwen-remote"'
    $pl += "voice = `"$k`""
    $pl += ''
}
[System.IO.File]::WriteAllLines((Join-Path $presetDir 'qwen.toml'), [string[]]$pl, (New-Object System.Text.UTF8Encoding($false)))

$cfg = Join-Path $Mod 'SKSE\Plugins\AudioUtilTTS\AudioUtilTTS.toml'
$lines = @(Get-Content -LiteralPath $cfg -Encoding UTF8)
$start = -1
for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq '[voicetype]') { $start = $i; break } }
if ($start -lt 0) { throw '[voicetype] line not found' }
$end = $lines.Count
for ($i = $start + 1; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^\[') { $end = $i; break } }

$block = @('[voicetype]', '# 由 write_qwen_mapping.ps1 生成：远程引擎（Qwen3-TTS）接管这些 voice type') +
    ($mapped | ForEach-Object { "$($types[$_]) = `"qwen_$_`"" }) + @('')
$new = @()
if ($start -gt 0) { $new += $lines[0..($start - 1)] }
$new += $block
if ($end -lt $lines.Count) { $new += $lines[$end..($lines.Count - 1)] }
[System.IO.File]::WriteAllLines($cfg, [string[]]$new, (New-Object System.Text.UTF8Encoding($false)))
"mapped $($mapped.Count) voice types (section lines $($start + 1)-$end)"
