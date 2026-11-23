"""HTTP wrapper around F5-TTS for the AudioUtilTTS remote engine.

Same contract as server_qwen_tts.py:

    GET  /health -> {"ok": true, "voices": [...], "warm": N, "total": M}
    POST /tts    -> audio/wav (PCM16 mono, 24 kHz)
         {"text": "...", "voice": "maleguard", "speed": 1.0, "format": "wav"}

A voice is <voices>/<name>.wav plus <name>.txt (its transcript). NFE=16 keeps a
4 second line under a second on a laptop GPU, which is what the dialogue menu's
2.5 s preparation window can absorb.
"""

import argparse
import io
import os
import threading
import time
import wave

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import soundfile as sf
import torch
import uvicorn

from f5_tts.api import F5TTS

app = FastAPI()
model = None
voices = {}
lock = threading.Lock()
lock_holder = {"warm": 0, "total": 0}


class Line(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0
    format: str = "wav"


@app.get("/health")
def health():
    return {"ok": model is not None, "voices": sorted(voices),
            "warm": lock_holder["warm"], "total": lock_holder["total"]}


@app.post("/tts")
def tts(line: Line):
    if not line.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    ref = voices.get(line.voice)
    if ref is None:
        raise HTTPException(status_code=400, detail=f"unknown voice '{line.voice}'")
    t0 = time.time()
    with lock:
        try:
            wav, sr, _ = model.infer(
                ref_file=ref["wav"],
                ref_text=ref["text"],
                gen_text=line.text,
                nfe_step=16,
                cfg_strength=2.0,
                sway_sampling_coef=-1.0,
                speed=line.speed or 1.0,
                show_info=lambda *a, **k: None,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if wav is None or len(wav) == 0:
        raise HTTPException(status_code=500, detail="no audio")
    pcm = (np.clip(np.asarray(wav, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)
    print(f"tts voice={line.voice} chars={len(line.text)} gen_ms={int((time.time() - t0) * 1000)}", flush=True)
    return Response(content=buf.getvalue(), media_type="audio/wav")


def main():
    global model, voices
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", required=True)
    parser.add_argument("--model", default="F5TTS_v1_Base")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()

    for name in sorted(os.listdir(args.voices)):
        if not name.lower().endswith(".wav"):
            continue
        stem = os.path.splitext(name)[0].lower()
        wav = os.path.join(args.voices, name)
        txt = os.path.splitext(wav)[0] + ".txt"
        if not os.path.exists(txt):
            continue
        with open(txt, encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            voices[stem] = {"wav": wav, "text": text}
    if not voices:
        raise SystemExit(f"no <name>.wav + <name>.txt in {args.voices}")

    model = F5TTS(model=args.model, device=args.device)
    model.infer(ref_file=voices[next(iter(voices))]["wav"],
                ref_text=voices[next(iter(voices))]["text"], gen_text="预热。", nfe_step=16,
                show_info=lambda *a, **k: None)
    lock_holder["warm"] = lock_holder["total"] = len(voices)
    print(f"f5 ready: {len(voices)} voices, {torch.cuda.max_memory_allocated()/1024**3:.2f} GB peak", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
