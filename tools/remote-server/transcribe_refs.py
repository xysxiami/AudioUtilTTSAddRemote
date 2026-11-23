"""给参考音补字幕：Qwen3-TTS 克隆时 ref_text 越准，音色越稳。

    uv pip install faster-whisper
    python transcribe_refs.py --voices G:\\qwen-tts\\voices [--model small.en]

对每个 <name>.wav 生成同名 .txt（读音即字幕，不要翻译）。
"""

import argparse
import os

from faster_whisper import WhisperModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", required=True)
    parser.add_argument("--model", default="small.en", help="tiny.en / base.en / small.en / medium.en")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = parser.parse_args()

    model = WhisperModel(args.model, device=args.device, compute_type="float16" if args.device == "cuda" else "int8")
    done = 0
    for name in sorted(os.listdir(args.voices)):
        if not name.lower().endswith(".wav"):
            continue
        wav = os.path.join(args.voices, name)
        txt = os.path.splitext(wav)[0] + ".txt"
        if os.path.exists(txt) and os.path.getsize(txt) > 0:
            continue
        segments, info = model.transcribe(wav, language="en", beam_size=5, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            with open(txt, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            done += 1
            print(f"{name}: {text[:80]}")
    print(f"written: {done}")


if __name__ == "__main__":
    main()
