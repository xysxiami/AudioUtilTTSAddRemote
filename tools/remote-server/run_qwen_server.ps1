$env:PYTHONUTF8 = '1'
Set-Location 'E:\qwen-tts\gguf'
$log = "E:\qwen-tts\server-$(Get-Date -Format yyyyMMdd-HHmmss).log"
uv run python 'E:\code\other\AudioUtilTTSAddRemote\tools\remote-server\server_qwen_tts.py' --model-dir 'E:\qwen-tts\exported\model-base' --voices 'G:\qwen-tts\voices' --provider DML *> $log
