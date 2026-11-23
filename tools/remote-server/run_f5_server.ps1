$env:PYTHONUTF8 = '1'
Set-Location 'C:\f5'
$log = "C:\f5\server-$(Get-Date -Format yyyyMMdd-HHmmss).log"
& 'C:\f5\venv\Scripts\python.exe' 'E:\code\other\AudioUtilTTSAddRemote\tools\remote-server\server_f5_tts.py' --voices 'G:\qwen-tts\voices' --port 9880 *> $log
