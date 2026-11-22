#include "RemoteTts.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>

#include <httplib.h>
#include <nlohmann/json.hpp>
#include <toml++/toml.hpp>

namespace RemoteTts
{
	namespace fs = std::filesystem;

	namespace
	{
		fs::path RemoteToml(const std::string& a_dir)
		{
			return fs::path(std::u8string(a_dir.begin(), a_dir.end())) / "remote.toml";
		}

		bool ReadAll(const fs::path& a_path, std::string& a_out, std::string& a_error)
		{
			std::ifstream in(a_path, std::ios::binary);
			if (!in) {
				a_error = "cannot open " + a_path.string();
				return false;
			}
			std::ostringstream ss;
			ss << in.rdbuf();
			a_out = ss.str();
			return true;
		}

		// "http://127.0.0.1:9880" -> server "http://127.0.0.1:9880", path "/tts"
		bool SplitUrl(std::string a_url, std::string& a_server, std::string& a_path)
		{
			while (!a_url.empty() && a_url.back() == '/') {
				a_url.pop_back();
			}
			auto scheme = a_url.find("://");
			if (scheme == std::string::npos || a_url.substr(0, scheme) != "http") {
				return false;
			}
			auto rest = a_url.substr(scheme + 3);
			if (rest.empty()) {
				return false;
			}
			auto slash = rest.find('/');
			if (slash == std::string::npos) {
				a_server = "http://" + rest;
				a_path = "/tts";
			} else {
				a_server = "http://" + rest.substr(0, slash);
				a_path = rest.substr(slash);
			}
			return true;
		}

		struct WavFormat
		{
			int format = 0;  // 1 = PCM, 3 = IEEE float, 0xFFFE = extensible
			int channels = 0;
			int rate = 0;
			int bits = 0;
		};

		std::uint16_t U16(const std::string& a_bytes, std::size_t a_at)
		{
			return static_cast<std::uint16_t>(static_cast<unsigned char>(a_bytes[a_at]) |
											  (static_cast<unsigned char>(a_bytes[a_at + 1]) << 8));
		}

		std::uint32_t U32(const std::string& a_bytes, std::size_t a_at)
		{
			return static_cast<std::uint32_t>(static_cast<unsigned char>(a_bytes[a_at]) |
											  (static_cast<unsigned char>(a_bytes[a_at + 1]) << 8) |
											  (static_cast<unsigned char>(a_bytes[a_at + 2]) << 16) |
											  (static_cast<unsigned char>(a_bytes[a_at + 3]) << 24));
		}

		// A wav the service wrote: PCM 8/16/24/32 or 32-bit float, any channels,
		// mixed to mono. Only what a plain fmt/data pair needs; anything else is
		// reported rather than guessed at.
		bool ParseWav(const std::string& a_bytes, std::vector<float>& a_out, int& a_rate, std::string& a_error)
		{
			if (a_bytes.size() < 44 || std::memcmp(a_bytes.data(), "RIFF", 4) != 0 ||
				std::memcmp(a_bytes.data() + 8, "WAVE", 4) != 0) {
				a_error = "the service did not answer a wav";
				return false;
			}
			WavFormat fmt;
			std::size_t dataAt = 0;
			std::size_t dataSize = 0;
			std::size_t at = 12;
			while (at + 8 <= a_bytes.size()) {
				const auto id = a_bytes.substr(at, 4);
				const auto size = static_cast<std::size_t>(U32(a_bytes, at + 4));
				const auto body = at + 8;
				if (id == "fmt " && size >= 16 && body + 16 <= a_bytes.size()) {
					fmt.format = U16(a_bytes, body);
					fmt.channels = U16(a_bytes, body + 2);
					fmt.rate = static_cast<int>(U32(a_bytes, body + 4));
					fmt.bits = U16(a_bytes, body + 14);
					if (fmt.format == 0xFFFE && size >= 26 && body + 26 <= a_bytes.size()) {
						fmt.format = U16(a_bytes, body + 24);
					}
				} else if (id == "data") {
					dataAt = body;
					dataSize = std::min(size, a_bytes.size() - body);
					break;
				}
				at = body + size + (size & 1);
			}
			if (fmt.rate <= 0 || fmt.channels <= 0 || dataAt == 0) {
				a_error = "the wav has no usable fmt/data";
				return false;
			}
			const bool pcm = fmt.format == 1 && (fmt.bits == 8 || fmt.bits == 16 || fmt.bits == 24 || fmt.bits == 32);
			const bool real = fmt.format == 3 && fmt.bits == 32;
			if (!pcm && !real) {
				a_error = "unsupported wav encoding (format " + std::to_string(fmt.format) + ", " +
						  std::to_string(fmt.bits) + " bits)";
				return false;
			}
			const std::size_t bytesPer = static_cast<std::size_t>(fmt.bits / 8);
			const std::size_t frame = bytesPer * static_cast<std::size_t>(fmt.channels);
			if (frame == 0) {
				a_error = "bad wav frame size";
				return false;
			}
			const std::size_t frames = dataSize / frame;
			a_out.resize(frames);
			for (std::size_t i = 0; i < frames; ++i) {
				float sum = 0.0f;
				for (int c = 0; c < fmt.channels; ++c) {
					const auto* p = a_bytes.data() + dataAt + i * frame + static_cast<std::size_t>(c) * bytesPer;
					if (real) {
						float v;
						std::memcpy(&v, p, 4);
						sum += v;
					} else if (fmt.bits == 8) {
						sum += (static_cast<float>(static_cast<unsigned char>(*p)) - 128.0f) / 128.0f;
					} else if (fmt.bits == 16) {
						std::int16_t v;
						std::memcpy(&v, p, 2);
						sum += static_cast<float>(v) / 32768.0f;
					} else if (fmt.bits == 24) {
						const auto* b = reinterpret_cast<const unsigned char*>(p);
						auto v = static_cast<std::int32_t>(b[0] | (b[1] << 8) | (b[2] << 16));
						if (v & 0x800000) {
							v -= 0x1000000;
						}
						sum += static_cast<float>(v) / 8388608.0f;
					} else {
						std::int32_t v;
						std::memcpy(&v, p, 4);
						sum += static_cast<float>(static_cast<double>(v) / 2147483648.0);
					}
				}
				a_out[i] = std::clamp(sum / static_cast<float>(fmt.channels), -1.0f, 1.0f);
			}
			a_rate = fmt.rate;
			if (a_out.empty()) {
				a_error = "the wav holds no audio";
				return false;
			}
			return true;
		}
	}

	bool IsRemoteModel(const std::string& a_dir)
	{
		std::error_code ec;
		return fs::is_regular_file(RemoteToml(a_dir), ec);
	}

	bool ReadConfig(const std::string& a_dir, Config& a_out, std::string& a_error)
	{
		const auto path = RemoteToml(a_dir);
		std::string text;
		if (!ReadAll(path, text, a_error)) {
			return false;
		}
		try {
			const auto table = toml::parse(text, path.string());
			a_out.url = table["url"].value_or(std::string{});
			a_out.timeoutMs = table["timeout_ms"].value_or(20000);
			a_out.sampleRate = table["sample_rate"].value_or(24000);
		} catch (const std::exception& e) {
			a_error = std::string("remote.toml: ") + e.what();
			return false;
		}
		if (a_out.url.empty()) {
			a_error = "remote.toml: no url";
			return false;
		}
		if (a_out.timeoutMs < 1000 || a_out.timeoutMs > 120000) {
			a_out.timeoutMs = std::clamp(a_out.timeoutMs, 1000, 120000);
		}
		std::string server, linePath;
		if (!SplitUrl(a_out.url, server, linePath)) {
			a_error = "remote.toml: url must start with http://";
			return false;
		}
		return true;
	}

	bool Synthesize(const Config& a_config, const std::string& a_text, const std::string& a_voice, float a_speed,
		std::vector<float>& a_samples, int& a_sampleRate, std::string& a_error)
	{
		std::string server, path;
		if (!SplitUrl(a_config.url, server, path)) {
			a_error = "bad remote url";
			return false;
		}
		httplib::Client client(server);
		const auto seconds = std::max(1, a_config.timeoutMs / 1000);
		client.set_connection_timeout(5, 0);
		client.set_read_timeout(seconds, 0);
		client.set_write_timeout(seconds, 0);

		nlohmann::json request;
		request["text"] = a_text;
		request["voice"] = a_voice;
		request["speed"] = a_speed;
		request["format"] = "wav";

		const auto answer = client.Post(path.c_str(), request.dump(), "application/json");
		if (!answer) {
			a_error = "no answer from " + server + " (" + httplib::to_string(answer.error()) + ")";
			return false;
		}
		if (answer->status != 200) {
			a_error = "service answered " + std::to_string(answer->status);
			if (!answer->body.empty() && answer->body.size() < 400) {
				a_error += ": " + answer->body;
			}
			return false;
		}
		if (!ParseWav(answer->body, a_samples, a_sampleRate, a_error)) {
			return false;
		}
		return true;
	}
}
