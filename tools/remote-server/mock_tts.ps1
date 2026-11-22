# Fake remote engine for AudioUtilTTS: answers /health and /tts so the plugin
# side can be tested before Qwen3-TTS is exported. Writes a 2 s 440 Hz wav.
#   powershell -ExecutionPolicy Bypass -File mock_tts.ps1 [-Port 9880] [-Seconds 2]
param([int]$Port = 9880, [int]$Seconds = 2)

$ErrorActionPreference = 'Stop'

function New-ToneWav([int]$rate = 24000, [double]$seconds = 2, [double]$freq = 440) {
    $frames = [int]($rate * $seconds)
    $data = New-Object byte[] ($frames * 2)
    for ($i = 0; $i -lt $frames; $i++) {
        $v = [int16]([math]::Sin(2 * [math]::PI * $freq * $i / $rate) * 8000)
        $data[2 * $i] = [byte]($v -band 0xFF)
        $data[2 * $i + 1] = [byte](($v -shr 8) -band 0xFF)
    }
    $ms = New-Object System.IO.MemoryStream
    $w = New-Object System.IO.BinaryWriter($ms)
    $w.Write([char[]]'RIFF'); $w.Write([int](36 + $data.Length))
    $w.Write([char[]]'WAVE'); $w.Write([char[]]'fmt ')
    $w.Write([int]16); $w.Write([int16]1); $w.Write([int16]1)
    $w.Write([int]$rate); $w.Write([int]($rate * 2)); $w.Write([int16]2); $w.Write([int16]16)
    $w.Write([char[]]'data'); $w.Write([int]$data.Length); $w.Write($data)
    $w.Flush()
    return $ms.ToArray()
}

$tone = New-ToneWav -seconds $Seconds
$listener = New-Object System.Net.HttpListener
$prefix = "http://127.0.0.1:$Port/"
$listener.Prefixes.Add($prefix)
$listener.Start()
Write-Host "mock TTS listening on $prefix  (Ctrl+C to stop)"

while ($listener.IsListening) {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    $path = $req.Url.AbsolutePath
    if ($path -eq '/health') {
        $json = '{"ok":true,"sample_rate":24000,"voices":["malenord","femaleeventoned"]}'
        $buf = [Text.Encoding]::UTF8.GetBytes($json)
        $res.ContentType = 'application/json; charset=utf-8'
        $res.ContentLength64 = $buf.Length
        $res.OutputStream.Write($buf, 0, $buf.Length)
        Write-Host "GET /health"
    } elseif ($path -eq '/tts') {
        $body = (New-Object System.IO.StreamReader($req.InputStream, [Text.Encoding]::UTF8)).ReadToEnd()
        Write-Host ("POST /tts " + $body.Substring(0, [Math]::Min(160, $body.Length)))
        $res.ContentType = 'audio/wav'
        $res.ContentLength64 = $tone.Length
        $res.OutputStream.Write($tone, 0, $tone.Length)
    } else {
        $res.StatusCode = 404
        $buf = [Text.Encoding]::UTF8.GetBytes('not found')
        $res.ContentLength64 = $buf.Length
        $res.OutputStream.Write($buf, 0, $buf.Length)
    }
    $res.OutputStream.Close()
}
