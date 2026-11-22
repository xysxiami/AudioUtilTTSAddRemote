"""HTTP wrapper around Qwen3-TTS GGUF for the AudioUtilTTS remote engine.

Contract (see docs/remote-engine.md):

    GET  /health          -> {"ok": true, "sample_rate": 24000, "voices": ["malenord", ...]}
    POST /tts             -> audio/wav (PCM16 mono)
         {"text": "...", "voice": "malenord", "speed": 1.0, "format": "wav"}

Voices are the wav files in --voices: the file name without ".wav" is the name
the plugin sends; the recording is the reference the model clones from.

Run (after exporting the model, see Qwen3-TTS-GGUF readme):

    uv run python server_qwen_tts.py --model-dir E:\\qwen-tts\\model-base --voices E:\\qwen-tts\\voices
"""

import argparse
import io
import os
import tempfile
import threading
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from qwen3_tts_gguf import TTSEngine, TTSConfig

app = FastAPI()
engine = None
voices = {}
lock = threading.Lock()
sample_rate = 24000


class Line(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0
    format: str = "wav"


def wav_bytes(path):
    with open(path, "rb") as f:
        return f.read()


@app.get("/health")
def health():
    return {"ok": True, "sample_rate": sample_rate, "voices": sorted(voices)}


@app.post("/tts")
def tts(line: Line):
    if not line.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    ref = voices.get(line.voice)
    if ref is None:
        raise HTTPException(status_code=400, detail=f"unknown voice '{line.voice}'")
    config = TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45, streaming=False)
    with lock:
        stream = engine.create_stream()
        try:
            stream.set_voice(ref)
            result = stream.clone(line.text, config=config)
        except Exception as exc:  # the plugin shows this text in its log
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            result.save(tmp)
            data = wav_bytes(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return Response(content=data, media_type="audio/wav")


def main():
    global engine, voices, sample_rate
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True, help="exported model folder")
    parser.add_argument("--voices", required=True, help="folder of <name>.wav reference recordings")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()

    voices = {
        os.path.splitext(name)[0].lower(): os.path.join(args.voices, name)
        for name in os.listdir(args.voices)
        if name.lower().endswith(".wav")
    }
    if not voices:
        raise SystemExit(f"no .wav in {args.voices}")

    engine = TTSEngine(model_dir=args.model_dir)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
