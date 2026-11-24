#pragma once

// 一次性把全部对话导成文本，供离线批量合成缓存。
// 只有 Data\SKSE\Plugins\AudioUtilTTS\dump_dialogue.flag 存在时才会执行，
// 导出到同目录的 dump_dialogue.tsv，然后删掉 flag，避免每次启动都跑。
namespace DumpDialogue
{
	void RunIfRequested();
}
