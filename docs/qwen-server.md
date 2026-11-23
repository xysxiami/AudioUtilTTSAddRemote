# Qwen3-TTS 服务端（本地，个人用）

插件侧已完成并验证：`remote.toml` + `voices\<name>.wav` + HTTP `/tts` 契约。这里是把 mock 换成真模型的步骤。

## 1. 下载官方权重（ModelScope，国内快）

```powershell
pip install modelscope
modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base --local_dir E:\qwen-tts\model-base
```

0.6B 版省约 500 MB 显存，`Qwen/Qwen3-TTS-12Hz-0.6B-Base`。

## 2. 拉 Qwen3-TTS-GGUF 并装环境

```powershell
git clone https://github.com/HaujetZhao/Qwen3-TTS-GGUF.git E:\qwen-tts\gguf
cd E:\qwen-tts\gguf
uv sync --extra export
uv sync --extra gpu     # 或 --extra dml
```

llama.cpp 用 **b10621**：下 `llama-b10621-bin-win-vulkan-x64.zip`（省 CUDA 13 运行时），把 DLL 放进 `qwen3_tts_gguf\bin\`。

## 3. 导出

改 `export_config.py` 里的模型路径，然后依次：

```
python 11-Export-Codec-Encoder.py
python 12-Export-Speaker-Encoder.py
python 13-Export-Decoder.py
python 14-Export-Embeddings.py
python 15-Copy-Tokenizer.py
python 16-Quantize-ONNX-Models.py
python 21-Extract-Talker-Weights.py
python 22-Prepare-Talker-Tokenizer.py
python 23-Convert-Talker-GGUF.py
python 24-Quantize-Talker-GGUF.py
python 31-Extract-Predictor-Weights.py
python 32-Prepare-Predictor-Tokenizer.py
python 33-Convert-Predictor-GGUF.py
python 34-Quantize-Predictor-GGUF.py
```

先用 `python 43-Inference-Base.py` 生成一句中文确认能出声，再起服务。

## 4. 参考音

每个 voice type 一段 5–10 秒干净人声（无人声重叠、无战斗音效），命名成 `<voicetype 小写>.wav`：

```
E:\qwen-tts\voices\malenord.wav
E:\qwen-tts\voices\maleguard.wav
E:\qwen-tts\voices\femaleeventoned.wav
```

来源可以是原版语音包（需要 fuz → wav 转换，ffmpeg 可解 XWMA），也可以自己录。参考音决定音色，选错会“串味”。

## 5. 起服务

```powershell
cd E:\code\other\AudioUtilTTSAddRemote
uv run python tools\remote-server\server_qwen_tts.py --model-dir E:\qwen-tts\gguf\EXPORT_DIR --voices E:\qwen-tts\voices
```

`http://127.0.0.1:9880/health` 应返回音色列表。显存约 1.8 GB（1.7B），RTF 约 0.35。

## 6. 插件侧切换

`models\qwen-remote\remote.toml` 保持 `url = "http://127.0.0.1:9880/tts"`；在 `AudioUtilTTS.toml` 里把 `[voicetype]` 的注释取消：

```toml
[voicetype]
MaleNord = "remote_test"
MaleGuard = "remote_test"
```

进游戏 `autts reload`，找对应 NPC 说话即可。日志里 `Config: ... N voice types mapped` 是生效标志。

## 已知限制

- 整句生成，不是流式：3 秒台词约 1 秒，菜单台词来得及，场景即兴台词仍可能迟到。
- `speed` 参数服务端目前忽略（Qwen3-TTS 的语速靠语料本身），需要变速再在服务端做重采样。
- 参考音质量和干净程度直接决定克隆效果。
