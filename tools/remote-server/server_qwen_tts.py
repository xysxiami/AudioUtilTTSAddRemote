import argparse
import os
import tempfile
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from qwen3_tts_gguf import TTSEngine, TTSConfig

app = FastAPI()
engine = None
voices = {}
lock = threading.Lock()


class Line(BaseModel):
    text: str
    voice: str = ""
    speed: float = 1.0
    format: str = "wav"


@app.get("/health")
def health():
    return {"ok": True, "voices": sorted(voices)}


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
            # text 是参考音的字幕；缺 .txt 时传空串，音色仍按音频特征走
            stream.set_voice(ref["wav"], text=ref["text"])
            result = stream.clone(line.text, language="chinese", config=config)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=500, detail="no audio from the engine")
        fd, tmp = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            result.save(tmp)
            with open(tmp, "rb") as f:
                data = f.read()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return Response(content=data, media_type="audio/wav")


def main():
    global engine, voices
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True, help="exported model folder")
    parser.add_argument("--voices", required=True, help="folder of <name>.wav (+ optional <name>.txt)")
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

    engine = TTSEngine(model_dir=args.model_dir)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
