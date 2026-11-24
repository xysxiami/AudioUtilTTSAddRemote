"""把参考音裁到前 ~4 秒，并按词边界生成对应的参考文本。

F5 的采样开销随参考音长度增长，8 秒的参考音会让每句多花将近一倍时间。
Whisper 给出词时间戳后，裁到最后一个结束于 4.0 秒内的词，文本只保留到那个词，
这样参考音和参考文本仍然对齐。
"""

import argparse
import json
import os

import soundfile as sf
from faster_whisper import WhisperModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default=r"G:\qwen-tts\voices")
    parser.add_argument("--out", default=r"G:\f5\refs")
    parser.add_argument("--limit", type=float, default=4.0)
    parser.add_argument("--model", default="small.en")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    rows = {}
    done = 0
    for name in sorted(os.listdir(args.voices)):
        if not name.lower().endswith(".wav"):
            continue
        stem = os.path.splitext(name)[0].lower()
        path = os.path.join(args.voices, name)
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as exc:
            print("skip", name, exc)
            continue
        if len(data) / sr <= args.limit + 0.3:
            out_wav = os.path.join(args.out, stem + ".wav")
            sf.write(out_wav, data, sr)
            txt = os.path.splitext(path)[0] + ".txt"
            text = open(txt, encoding="utf-8").read().strip() if os.path.exists(txt) else ""
            rows[stem] = text
            continue
        try:
            segments, _ = model.transcribe(path, language="en", word_timestamps=True, vad_filter=False)
            words = [w for seg in segments for w in seg.words]
        except Exception as exc:
            print("asr failed", name, exc)
            words = []
        keep = [w for w in words if w.end is not None and w.end <= args.limit]
        if keep:
            end = keep[-1].end
            text = " ".join(w.word.strip() for w in keep).strip()
        else:
            end = args.limit
            text = ""
        if not text:
            # 没有词时间戳时退化为按比例裁，文本取原字幕前 40%
            orig = os.path.splitext(path)[0] + ".txt"
            text = ""
            if os.path.exists(orig):
                t = open(orig, encoding="utf-8").read().strip()
                text = t[: max(1, int(len(t) * 0.4))]
        clip = data[: int(end * sr)]
        out_wav = os.path.join(args.out, stem + ".wav")
        sf.write(out_wav, clip, sr)
        rows[stem] = text
        done += 1
        if done % 20 == 0:
            print("done", done, flush=True)

    with open(os.path.join(args.out, "_refs.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=0)
    print("total", len(rows))


if __name__ == "__main__":
    main()
