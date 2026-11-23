"""HTTP wrapper around Qwen3-TTS GGUF for the AudioUtilTTS remote engine.

Contract (see docs/remote-engine.md):

    GET  /health          -> {"ok": true, "voices": ["malenord", ...]}
    POST /tts             -> audio/wav (PCM16 mono)
         {"text": "...", "voice": "malenord", "speed": 1.0, "format": "wav"}

Voices are the wav files in --voices (file name without ".wav"); a same-named
.txt, written by transcribe_refs.py, is the reference transcript the clone uses.

One stream is kept for the process lifetime, and each voice's anchor is cached
after its first use: switching back to a voice then costs nothing, which is what
keeps a line under a second.
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

from qwen3_tts_gguf.inference.engine import TTSEngine
from qwen3_tts_gguf.inference.config import TTSConfig

app = FastAPI()
engine = None
stream = None
voices = {}
anchors = {}
lock = threading.Lock()


class Line(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0
    format: str = "wav"


@app.get("/health")
def health():
    return {"ok": stream is not None, "voices": sorted(voices)}


@app.post("/tts")
def tts(line: Line):
    if not line.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    ref = voices.get(line.voice)
    if ref is None:
        raise HTTPException(status_code=400, detail=f"unknown voice '{line.voice}'")

    config = TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45, streaming=False)
    with lock:
        try:
            anchor = anchors.get(line.voice)
            if anchor is None:
                stream.set_voice(ref["wav"], text=ref["text"])
                anchor = stream.voice
                anchors[line.voice] = anchor
            else:
                stream.set_voice(anchor)
            result = stream.clone(line.text, language="chinese", config=config)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None or result.audio is None or len(result.audio) == 0:
            raise HTTPException(status_code=500, detail="no audio from the engine")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            import numpy as np

            w.writeframes((np.clip(result.audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())
        data = buf.getvalue()
    return Response(content=data, media_type="audio/wav")


def main():
    global engine, stream, voices
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--provider", default="DML", help="DML, CUDA or CPU (onnxruntime)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()

    for name in sorted(os.listdir(args.voices)):
        if not name.lower().endswith(".wav"):
            continue
        stem = os.path.splitext(name)[0].lower()
        wav = os.path.join(args.voices, name)
        txt = os.path.splitext(wav)[0] + ".txt"
        text = ""
        if os.path.exists(txt):
            with open(txt, encoding="utf-8") as f:
                text = f.read().strip()
        voices[stem] = {"wav": wav, "text": text}
    if not voices:
        raise SystemExit(f"no .wav in {args.voices}")

    engine = TTSEngine(model_dir=args.model_dir, onnx_provider=args.provider)
    stream = engine.create_stream()
    if stream is None:
        raise SystemExit("engine reported no stream (decoder timeout?)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
