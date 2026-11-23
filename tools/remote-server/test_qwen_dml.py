import multiprocessing
import pathlib
import time


def main():
    from qwen3_tts_gguf.inference.engine import TTSEngine
    from qwen3_tts_gguf.inference.config import TTSConfig

    t0 = time.time()
    engine = TTSEngine(model_dir=r"E:\qwen-tts\exported\model-base", onnx_provider="DML")
    print("engine loaded in %.1fs" % (time.time() - t0))

    stream = engine.create_stream()
    if stream is None:
        print("no stream")
        return
    ref = r"G:\qwen-tts\voices\malenord.wav"
    txt = pathlib.Path(r"G:\qwen-tts\voices\malenord.txt").read_text(encoding="utf-8").strip()
    t0 = time.time()
    stream.set_voice(ref, text=txt)
    print("set_voice in %.1fs" % (time.time() - t0))
    anchor = stream.voice

    for i, text in enumerate(["你好，旅行者。", "今天天气不错，我们去镇上看看吧。", "站住！你踩到我的菜地了。"]):
        if i == 1:
            t0 = time.time()
            stream.set_voice(anchor)
            print("set_voice(cached) in %.2fs" % (time.time() - t0))
        t0 = time.time()
        r = stream.clone(text, language="chinese", config=TTSConfig(streaming=False))
        dur = len(r.audio) / 24000 if r is not None and r.audio is not None else 0
        print("line %d: %.1fs for %.1fs audio (RTF %.2f)" % (i, time.time() - t0, dur, (time.time() - t0) / max(dur, 0.01)))
        if i == 0 and r is not None:
            r.save_wav(r"E:\qwen-tts\test_zh.wav")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
