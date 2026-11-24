#include "DumpDialogue.h"

#include <fstream>

#include "PCH.h"
#include "Config.h"
#include "Speaker.h"

namespace
{
	namespace fs = std::filesystem;

	fs::path PluginDir()
	{
		return fs::current_path() / "Data" / "SKSE" / "Plugins" / "AudioUtilTTS";
	}

	// 一行里既不能有制表符也不能有换行，其它字节原样保留（游戏文本是 UTF-8）
	std::string OneLine(const char* a_text)
	{
		std::string out;
		if (!a_text) {
			return out;
		}
		for (const char* p = a_text; *p; ++p) {
			out += (*p == '\t' || *p == '\r' || *p == '\n') ? ' ' : *p;
		}
		return out;
	}

	// INFO 条件里 GetIsVoiceType 的 VTYP，可能不止一个
	std::string VoiceTypes(const RE::TESTopicInfo* a_info)
	{
		std::string out;
		for (auto* item = a_info->objConditions.head; item; item = item->next) {
			if (item->data.functionData.function.get() != RE::FUNCTION_DATA::FunctionID::kGetIsVoiceType) {
				continue;
			}
			auto* form = static_cast<RE::TESForm*>(item->data.functionData.params[0]);
			if (!form) {
				continue;
			}
			const char* edid = form->GetFormEditorID();
			if (!edid || !*edid) {
				continue;
			}
			if (!out.empty()) {
				out += ',';
			}
			out += edid;
		}
		return out;
	}
}

namespace DumpDialogue
{
	void RunIfRequested()
	{
		const auto dir = PluginDir();
		std::error_code ec;
		const auto flag = dir / "dump_dialogue.flag";
		if (!fs::exists(flag, ec)) {
			return;
		}

		const auto outPath = dir / "dump_dialogue.tsv";
		std::ofstream out(outPath, std::ios::binary | std::ios::trunc);
		if (!out) {
			logger::error("Dump: cannot open {}", outPath.string());
			return;
		}

		auto* handler = RE::TESDataHandler::GetSingleton();
		if (!handler) {
			logger::error("Dump: no data handler");
			return;
		}

		std::size_t lines = 0;
		std::size_t infos = 0;
		std::size_t topics = 0;
		// INFO 记录不在 TESDataHandler 的全局表单数组里，得从它所属的对话主题往下走
		for (auto* topic : handler->GetFormArray<RE::TESTopic>()) {
			if (!topic) {
				continue;
			}
			++topics;
			for (std::uint32_t i = 0; i < topic->numTopicInfos; ++i) {
				auto* info = topic->topicInfos[i];
				if (!info) {
					continue;
				}
				auto* list = info->GetResponseList();
				if (!list) {
					continue;
				}
				const auto voices = VoiceTypes(info);
				++infos;
				for (auto* response = list->head; response; response = response->next) {
					const auto text = OneLine(response->responseText.c_str());
					if (text.empty()) {
						continue;
					}
					const auto spoken = Speaker::CleanForDump(text);
					if (spoken.empty()) {
						continue;
					}
					out << std::format("{:08X}\t{}\t{}\t{}\n",
						info->GetFormID(),
						static_cast<unsigned>(response->responseNumber),
						voices,
						spoken);
					++lines;
				}
			}
		}
		out.close();

		logger::info("Dump: {} topics, {} infos, {} responses -> {}", topics, infos, lines, outPath.string());
		fs::remove(flag, ec);
	}
}
