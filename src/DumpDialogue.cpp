#include "DumpDialogue.h"

#include <fstream>
#include <utility>

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

	// 条件参数不一定是表单指针（别名等情况是索引），用合法表单指针集合过滤，
	// 避免把 0x1 之类当成 TESForm* 解引用导致崩溃。
	using FormSet = std::unordered_set<const RE::TESForm*>;

	void AddVoiceOf(const RE::TESForm* a_form, std::string& a_out, std::unordered_set<std::string>& a_seen,
		const FormSet& a_forms)
	{
		if (!a_form || !a_forms.contains(a_form)) {
			return;
		}
		const RE::BGSVoiceType* voice = nullptr;
		if (const auto* vtyp = a_form->As<RE::BGSVoiceType>()) {
			voice = vtyp;
		} else if (const auto* actorBase = a_form->As<RE::TESActorBase>()) {
			voice = actorBase->GetObjectVoiceType();
		} else if (const auto* ref = a_form->As<RE::TESObjectREFR>()) {
			if (const auto* base = ref->GetBaseObject()) {
				if (a_forms.contains(base)) {
					if (const auto* actorBase = base->As<RE::TESActorBase>()) {
						voice = actorBase->GetObjectVoiceType();
					}
				}
			}
		}
		if (!voice || !a_forms.contains(voice)) {
			return;
		}
		const char* edid = voice->GetFormEditorID();
		if (!edid || !*edid) {
			return;
		}
		if (!a_seen.insert(edid).second) {
			return;
		}
		if (!a_out.empty()) {
			a_out += ',';
		}
		a_out += edid;
	}

	std::string VoiceTypes(const RE::TESTopicInfo* a_info, const FormSet& a_forms)
	{
		std::string out;
		std::unordered_set<std::string> seen;
		int steps = 0;
		for (auto* item = a_info->objConditions.head; item; item = item->next) {
			if (++steps > 64) {
				break;
			}
			const auto fn = item->data.functionData.function.get();
			if (fn != RE::FUNCTION_DATA::FunctionID::kGetIsVoiceType &&
				fn != RE::FUNCTION_DATA::FunctionID::kGetIsID) {
				continue;
			}
			const auto* form = static_cast<RE::TESForm*>(item->data.functionData.params[0]);
			AddVoiceOf(form, out, seen, a_forms);
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

		FormSet forms;
		for (auto t = 0; t < std::to_underlying(RE::FormType::Max); ++t) {
			for (auto* form : handler->GetFormArray(static_cast<RE::FormType>(t))) {
				if (form) {
					forms.insert(form);
				}
			}
		}
		logger::info("Dump: {} forms indexed", forms.size());

		// INFO 记录不在 TESDataHandler 的全局表单数组里，得从它所属的对话主题往下走
		for (auto* topic : handler->GetFormArray<RE::TESTopic>()) {
			if (!topic) {
				continue;
			}
			if (!topic->topicInfos || topic->numTopicInfos == 0) {
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
				const auto voices = VoiceTypes(info, forms);
				++infos;
				int responses = 0;
				for (auto* response = list->head; response; response = response->next) {
					if (++responses > 32) {
						break;
					}
					if (!response->responseText.c_str()) {
						continue;
					}
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
