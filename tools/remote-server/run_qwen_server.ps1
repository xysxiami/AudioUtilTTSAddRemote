# 起 Qwen3-TTS 服务（插件 remote.toml 指向 127.0.0.1:9880/tts）
param(
    [string]$Root = 'E:\qwen-tts',
    [string]$Voices = 'G:\qwen-tts\voices',
    [string]$Server = 'E:\code\other\AudioUtilTTSAddRemote\tools\remote-server\server_qwen_tts.py'
)

$gguf = Join-Path $Root 'gguf'
$model = Join-Path $Root 'exported\model-base'
if (-not (Test-Path $model)) { throw "missing exported model: $model (run setup_qwen.ps1)" }

Push-Location $gguf
try {
    uv run python $Server --model-dir $model --voices $Voices
} finally {
    Pop-Location
}
