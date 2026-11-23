"""HTTP wrapper around Qwen3-TTS GGUF for the AudioUtilTTS remote engine.

Contract (see docs/remote-engine.md):

    GET  /health          -> {"ok": true, "voices": [...], "warm": N, "total": M}
    POST /tts             -> audio/wav (PCM16 mono)
         {"text": "...", "voice": "malenord", "speed": 1.0, "format": "wav"}

Voices are the wav files in --voices (file name without ".wav"); a same-named
.txt, written by transcribe_refs.py, is the reference transcript the clone uses.

Voice anchors (reference encoding) are prewarmed at startup, one stream holds
the prewarm while the other serves requests. Two streams let a burst of lines
from a dialogue menu be generated in parallel instead of queueing behind each
other until the plugin's HTTP timeout.
"""

import argparse
import io
import os
import queue
import threading
import time
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from qwen3_tts_gguf.inference.engine import TTSEngine
from qwen3_tts_gguf.inference.config import TTSConfig

STREAMS = 2

app = FastAPI()
engine = None
streams = []
stream_q = queue.Queue()
voices = {}
anchors = {}
warm = {"done": 0, "total": 0}


class Line(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0
    format: str = "wav"


@app.get("/health")
def health():
    return {"ok": bool(streams), "voices": sorted(voices), "warm": warm["done"], "total": warm["total"]}


# Common voice types first, so a normal town is ready within seconds.
COMMON = [
    "maleguard", "malenord", "malecommoner", "femalenord", "femalecommoner",
    "maleeventoned", "femaleeventoned", "malebandit", "malesoldier", "malebrute",
    "femaleargonian", "maleargonian", "femalekhajiit", "malekhajiit", "maleorc",
    "femaleorc", "maledarkelf", "femaledarkelf", "malechild", "femalechild",
]


def prewarm(stream):
    order = [n for n in COMMON if n in voices] + [n for n in sorted(voices) if n not in COMMON]
    warm["total"] = len(order)
    for name in order:
        if name in anchors:
            warm["done"] += 1
            continue
        try:
            stream.set_voice(voices[name]["wav"], text=voices[name]["text"])
            anchors[name] = stream.voice
            warm["done"] += 1
        except Exception as exc:  # one bad clip must not stop the rest
            print(f"prewarm failed for {name}: {exc}", flush=True)


@app.post("/tts")
def tts(line: Line):
    if not line.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    ref = voices.get(line.voice)
    if ref is None:
        raise HTTPException(status_code=400, detail=f"unknown voice '{line.voice}'")

    config = TTSConfig(temperature=0.8, sub_temperature=0.8, seed=42, sub_seed=45, streaming=False)
    t0 = time.time()
    stream = streams[stream_q.get()]
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
    finally:
        stream_q.put(stream.index)

    if result is None or result.audio is None or len(result.audio) == 0:
        raise HTTPException(status_code=500, detail="no audio from the engine")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        import numpy as np

        w.writeframes((np.clip(result.audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    print(f"tts voice={line.voice} chars={len(line.text)} gen_ms={int((time.time() - t0) * 1000)}", flush=True)
    return Response(content=buf.getvalue(), media_type="audio/wav")


def main():
    global engine, streams, voices
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
    for i in range(STREAMS):
        s = engine.create_stream()
        if s is None:
            raise SystemExit("engine reported no stream (decoder timeout?)")
        s.index = i
        streams.append(s)
        stream_q.put(i)

    # prewarm holds stream 0; requests use the remaining stream(s) meanwhile
    warm_stream = streams[0]
    stream_q.get()
    threading.Thread(target=lambda: (prewarm(warm_stream), stream_q.put(0)), daemon=True).start()
    print(f"prewarming {len(voices)} voice anchors on stream 0, serving on {STREAMS - 1} stream(s)", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
