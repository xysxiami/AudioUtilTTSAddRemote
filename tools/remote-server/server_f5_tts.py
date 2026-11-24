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
import json
import os
import threading
import time
import wave

import numpy as np
import soundfile as sf
import torch
import torchaudio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from f5_tts.api import F5TTS
from f5_tts.model.utils import convert_char_to_pinyin

HOP = 256
SR = 24000

app = FastAPI()
model = None
voices = {}
conds = {}
lock = threading.Lock()
lock_holder = {"warm": 0, "total": 0}


def prepare_cond(wav_path):
    """参考音的前处理只做一次：归一化、重采样、mel 频谱（条件序列）。"""
    data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    audio = torch.from_numpy(data.T.copy())
    if audio.shape[0] > 1:
        audio = audio.mean(dim=0, keepdim=True)
    rms = torch.sqrt(torch.mean(torch.square(audio)))
    if rms < 0.1:
        audio = audio * 0.1 / rms
    if sr != SR:
        audio = torchaudio.functional.resample(audio, sr, SR)
    audio = audio.to(model.device)
    with torch.no_grad():
        mel = model.ema_model.mel_spec(audio)
    return {
        "frames": audio.shape[-1] // HOP,
        "cond": mel.permute(0, 2, 1).contiguous(),
        "rms": float(rms),
    }


def voice_cond(name):
    entry = conds.get(name)
    if entry is None:
        entry = prepare_cond(voices[name]["wav"])
        conds[name] = entry
    return entry


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
    # 游戏里的 voice_map 把 maleguard 映射成 qwen_maleguard，这里两种名字都认
    name = line.voice if line.voice in voices else line.voice.removeprefix("qwen_")
    ref = voices.get(name)
    if ref is None:
        raise HTTPException(status_code=400, detail=f"unknown voice '{line.voice}'")
    t0 = time.time()
    nfe = int(os.environ.get("F5_NFE", "6"))
    with lock:
        try:
            entry = voice_cond(name)
            ref_text = ref["text"]
            if len(ref_text[-1].encode("utf-8")) == 1:
                ref_text += " "
            gen_text = line.text
            speed = line.speed or 1.0
            gen_bytes = len(gen_text.encode("utf-8"))
            ref_bytes = len(ref_text.encode("utf-8"))
            # 短句放慢，和官方推理脚本一致
            local_speed = 0.3 if gen_bytes < 10 else speed
            duration = entry["frames"] + int(entry["frames"] / ref_bytes * gen_bytes / local_speed)
            final_text = convert_char_to_pinyin([ref_text + gen_text])
            with torch.autocast("cuda", dtype=torch.float16):
                generated, _ = model.ema_model.sample(
                    cond=entry["cond"],
                    text=final_text,
                    duration=duration,
                    steps=nfe,
                    cfg_strength=2.0,
                    sway_sampling_coef=-1.0,
                )
                generated = generated[:, entry["frames"]:, :].permute(0, 2, 1)
                wave_out = model.vocoder.decode(generated)
            if entry["rms"] < 0.1:
                wave_out = wave_out * entry["rms"] / 0.1
            wav = wave_out.squeeze().float().cpu().numpy()
            sr = SR
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

    refs_text = {}
    refs_json = os.path.join(args.voices, "_refs.json")
    if os.path.exists(refs_json):
        with open(refs_json, encoding="utf-8") as f:
            refs_text = json.load(f)

    for name in sorted(os.listdir(args.voices)):
        if not name.lower().endswith(".wav"):
            continue
        stem = os.path.splitext(name)[0].lower()
        wav = os.path.join(args.voices, name)
        text = refs_text.get(stem, "").strip()
        if not text:
            txt = os.path.splitext(wav)[0] + ".txt"
            if os.path.exists(txt):
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
