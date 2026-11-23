# 一次性准备 Qwen3-TTS GGUF 环境并导出模型
#   powershell -ExecutionPolicy Bypass -File setup_qwen.ps1
param([string]$Root = 'E:\qwen-tts')

$ErrorActionPreference = 'Stop'
$gguf = Join-Path $Root 'gguf'
$models = Join-Path $Root 'models'
$exported = Join-Path $Root 'exported'

# 1. 解 GGUF 源码
if (-not (Test-Path (Join-Path $gguf 'export_config.py'))) {
    $zip = Join-Path $Root 'src\Qwen3-TTS-GGUF.zip'
    if (-not (Test-Path $zip)) { throw "missing $zip (run the download step first)" }
    $tmp = Join-Path $Root 'src\_unzip'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    $top = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
    Move-Item -LiteralPath $top.FullName -Destination $gguf
    Remove-Item -LiteralPath $tmp -Recurse -Force
    Write-Output "gguf source ready: $gguf"
}

# 2. llama.cpp DLL 放进 qwen3_tts_gguf\bin
$llamaZip = Join-Path $Root 'tools\llama-b10621-bin-win-vulkan-x64.zip'
if ((Test-Path $llamaZip) -and -not (Test-Path (Join-Path $gguf 'qwen3_tts_gguf\bin\ggml-vulkan.dll'))) {
    $tmp = Join-Path $Root 'tools\_llama'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $llamaZip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $gguf 'qwen3_tts_gguf\bin') | Out-Null
    Get-ChildItem -LiteralPath $tmp -Recurse -Filter '*.dll' | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $gguf 'qwen3_tts_gguf\bin') -Force
    }
    Remove-Item -LiteralPath $tmp -Recurse -Force
    Write-Output 'llama.cpp DLLs copied'
}

# 3. 让权重目录符合 export_config 的预期
New-Item -ItemType Directory -Force -Path $models, $exported | Out-Null
$link = Join-Path $models 'Qwen3-TTS-12Hz-1.7B-Base'
if (-not (Test-Path $link)) {
    cmd /c mklink /J "$link" (Join-Path $Root 'model-base') | Out-Null
}

$cfg = Join-Path $gguf 'export_config.py'
$text = Get-Content -LiteralPath $cfg -Raw
$text = $text.Replace("model_home = Path('~/.cache/modelscope/hub/models/Qwen').expanduser()", "model_home = Path(r'$models')")
$text = $text.Replace('dest_home = Path(__file__).parent', "dest_home = Path(r'$exported')")
[System.IO.File]::WriteAllText($cfg, $text, (New-Object System.Text.UTF8Encoding($false)))

# 4. 依赖
Push-Location $gguf
try {
    uv sync --extra export --extra gpu
    uv pip install faster-whisper
    # 5. 导出
    $steps = @(
        '11-Export-Codec-Encoder.py', '12-Export-Speaker-Encoder.py', '13-Export-Decoder.py',
        '14-Export-Embeddings.py', '15-Copy-Tokenizer.py', '16-Quantize-ONNX-Models.py',
        '21-Extract-Talker-Weights.py', '22-Prepare-Talker-Tokenizer.py',
        '23-Convert-Talker-GGUF.py', '24-Quantize-Talker-GGUF.py',
        '31-Extract-Predictor-Weights.py', '32-Prepare-Predictor-Tokenizer.py',
        '33-Convert-Predictor-GGUF.py', '34-Quantize-Predictor-GGUF.py'
    )
    foreach ($s in $steps) {
        Write-Output "=== $s ==="
        uv run python $s
        if ($LASTEXITCODE -ne 0) { throw "step failed: $s" }
    }
    Write-Output "exported to $exported\model-base"
} finally {
    Pop-Location
}
