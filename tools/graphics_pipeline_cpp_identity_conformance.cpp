#include <array>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>

namespace {

constexpr std::string_view kRepository = "https://github.com/shadps4-emu/shadPS4";
constexpr std::string_view kCommit = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64";
constexpr std::string_view kSurfaceVersion = "bb-graphics-pipeline-key-surface/v12";
constexpr std::string_view kSurfaceDigest = "sha256:21f03690ddfc424a1d4624eced6fb4d48cdc030df14d5e098e0d979d78191f6e";
constexpr std::string_view kExpectedIdentity = "pipeline:sha256:c46cf5568ebdb232b52bc092f2fc445bf1fa9aee1b7663717b087fae5cce1c38";

struct Sha256 {
    std::array<std::uint32_t, 8> state{
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    std::array<std::uint8_t, 64> block{};
    std::uint64_t total_bytes = 0;
    std::size_t block_size = 0;

    static constexpr std::array<std::uint32_t, 64> k{
        0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
        0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
        0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
        0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
        0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
        0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
        0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
        0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};

    static std::uint32_t rotr(std::uint32_t x, unsigned n) { return (x >> n) | (x << (32 - n)); }

    void compress() {
        std::array<std::uint32_t, 64> w{};
        for (std::size_t i = 0; i < 16; ++i) {
            const std::size_t j = i * 4;
            w[i] = (std::uint32_t(block[j]) << 24) | (std::uint32_t(block[j + 1]) << 16) |
                   (std::uint32_t(block[j + 2]) << 8) | std::uint32_t(block[j + 3]);
        }
        for (std::size_t i = 16; i < 64; ++i) {
            const auto s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const auto s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        auto a=state[0], b=state[1], c=state[2], d=state[3], e=state[4], f=state[5], g=state[6], h=state[7];
        for (std::size_t i = 0; i < 64; ++i) {
            const auto s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            const auto ch = (e & f) ^ ((~e) & g);
            const auto temp1 = h + s1 + ch + k[i] + w[i];
            const auto s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            const auto maj = (a & b) ^ (a & c) ^ (b & c);
            const auto temp2 = s0 + maj;
            h=g; g=f; f=e; e=d+temp1; d=c; c=b; b=a; a=temp1+temp2;
        }
        state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
        state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
    }

    void update(std::string_view input) {
        total_bytes += input.size();
        for (unsigned char c : input) {
            block[block_size++] = c;
            if (block_size == block.size()) { compress(); block_size = 0; }
        }
    }

    std::string finish_hex() {
        const std::uint64_t bit_length = total_bytes * 8;
        block[block_size++] = 0x80;
        if (block_size > 56) {
            while (block_size < 64) block[block_size++] = 0;
            compress(); block_size = 0;
        }
        while (block_size < 56) block[block_size++] = 0;
        for (int shift = 56; shift >= 0; shift -= 8) block[block_size++] = std::uint8_t(bit_length >> shift);
        compress();
        std::ostringstream out;
        out << std::hex << std::setfill('0');
        for (auto word : state) out << std::setw(8) << word;
        return out.str();
    }
};

struct BlendControl {
    std::uint32_t alpha_dst_factor = 0;
    std::uint32_t alpha_func = 0;
    std::uint32_t alpha_src_factor = 0;
    std::uint32_t color_dst_factor = 0;
    std::uint32_t color_func = 0;
    std::uint32_t color_src_factor = 0;
    std::uint32_t disable_rop3 = 0;
    std::uint32_t enable = 0;
    std::uint32_t separate_alpha_blend = 0;
};

struct ColorBuffer {
    std::uint32_t data_format = 0;
    std::uint32_t export_format = 0;
    std::uint32_t num_conversion = 0;
    std::uint32_t num_format = 0;
    std::array<std::uint32_t, 4> swizzle{};
};

struct CanonicalPipelineKey {
    std::array<BlendControl, 8> blend_controls{};
    std::uint32_t cb_shader_mask = 0;
    std::uint32_t clip_space = 0;
    std::array<ColorBuffer, 8> color_buffers{};
    std::array<std::uint32_t, 8> color_samples{};
    std::uint32_t depth_clamp_enable = 0;
    std::uint32_t depth_clip_enable = 0;
    std::uint32_t depth_samples = 0;
    std::uint32_t logic_op = 0;
    std::uint32_t mrt_mask = 0;
    std::uint32_t num_color_attachments = 0;
    std::uint32_t num_samples = 0;
    std::uint32_t patch_control_points = 0;
    std::uint32_t polygon_mode = 0;
    std::uint32_t prim_type = 0;
    std::uint32_t provoking_vtx_last = 0;
    std::array<std::uint64_t, 6> stage_hashes{};
    std::uint32_t stencil_format = 0;
    std::array<std::int32_t, 32> vertex_buffer_formats{};
    std::array<std::uint32_t, 8> write_masks{};
    std::uint32_t z_format = 0;
};

CanonicalPipelineKey fixture_key() {
    CanonicalPipelineKey key{};
    key.cb_shader_mask = 15;
    key.color_buffers[0] = ColorBuffer{1, 0, 0, 0, {4, 5, 6, 7}};
    key.color_samples[0] = 1;
    key.depth_clip_enable = 1;
    key.depth_samples = 1;
    key.mrt_mask = 1;
    key.num_color_attachments = 1;
    key.num_samples = 1;
    key.prim_type = 3;
    key.stage_hashes[0] = 0x1111111111111111ULL;
    key.stage_hashes[4] = 0x2222222222222222ULL;
    key.write_masks[0] = 15;
    return key;
}

template <typename T, std::size_t N>
void append_number_array(std::string& out, const std::array<T, N>& values) {
    out.push_back('[');
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) out.push_back(',');
        out += std::to_string(values[i]);
    }
    out.push_back(']');
}

void append_blend_control(std::string& out, const BlendControl& value) {
    out += "{\"alpha_dst_factor\":" + std::to_string(value.alpha_dst_factor);
    out += ",\"alpha_func\":" + std::to_string(value.alpha_func);
    out += ",\"alpha_src_factor\":" + std::to_string(value.alpha_src_factor);
    out += ",\"color_dst_factor\":" + std::to_string(value.color_dst_factor);
    out += ",\"color_func\":" + std::to_string(value.color_func);
    out += ",\"color_src_factor\":" + std::to_string(value.color_src_factor);
    out += ",\"disable_rop3\":" + std::to_string(value.disable_rop3);
    out += ",\"enable\":" + std::to_string(value.enable);
    out += ",\"separate_alpha_blend\":" + std::to_string(value.separate_alpha_blend) + "}";
}

void append_color_buffer(std::string& out, const ColorBuffer& value) {
    out += "{\"data_format\":" + std::to_string(value.data_format);
    out += ",\"export_format\":" + std::to_string(value.export_format);
    out += ",\"num_conversion\":" + std::to_string(value.num_conversion);
    out += ",\"num_format\":" + std::to_string(value.num_format);
    out += ",\"swizzle\":";
    append_number_array(out, value.swizzle);
    out.push_back('}');
}

std::string canonical_payload(const CanonicalPipelineKey& key) {
    std::string out;
    out.reserve(5000);
    out += "{\"kind\":\"pipeline\",\"value\":{\"canonical_key\":{";

    out += "\"blend_controls\":[";
    for (std::size_t i = 0; i < key.blend_controls.size(); ++i) {
        if (i != 0) out.push_back(',');
        append_blend_control(out, key.blend_controls[i]);
    }

    out += "],\"cb_shader_mask\":" + std::to_string(key.cb_shader_mask);
    out += ",\"clip_space\":" + std::to_string(key.clip_space);
    out += ",\"color_buffers\":[";
    for (std::size_t i = 0; i < key.color_buffers.size(); ++i) {
        if (i != 0) out.push_back(',');
        append_color_buffer(out, key.color_buffers[i]);
    }

    out += "],\"color_samples\":";
    append_number_array(out, key.color_samples);
    out += ",\"depth_clamp_enable\":" + std::to_string(key.depth_clamp_enable);
    out += ",\"depth_clip_enable\":" + std::to_string(key.depth_clip_enable);
    out += ",\"depth_samples\":" + std::to_string(key.depth_samples);
    out += ",\"logic_op\":" + std::to_string(key.logic_op);
    out += ",\"mrt_mask\":" + std::to_string(key.mrt_mask);
    out += ",\"num_color_attachments\":" + std::to_string(key.num_color_attachments);
    out += ",\"num_samples\":" + std::to_string(key.num_samples);
    out += ",\"patch_control_points\":" + std::to_string(key.patch_control_points);
    out += ",\"polygon_mode\":" + std::to_string(key.polygon_mode);
    out += ",\"prim_type\":" + std::to_string(key.prim_type);
    out += ",\"provoking_vtx_last\":" + std::to_string(key.provoking_vtx_last);
    out += ",\"stage_hashes\":";
    append_number_array(out, key.stage_hashes);
    out += ",\"stencil_format\":" + std::to_string(key.stencil_format);
    out += ",\"vertex_buffer_formats\":";
    append_number_array(out, key.vertex_buffer_formats);
    out += ",\"write_masks\":";
    append_number_array(out, key.write_masks);
    out += ",\"z_format\":" + std::to_string(key.z_format) + "},";

    out += "\"key_surface_sha256\":\"" + std::string(kSurfaceDigest) + "\",";
    out += "\"key_surface_version\":\"" + std::string(kSurfaceVersion) + "\",";
    out += "\"source\":{\"commit\":\"" + std::string(kCommit) + "\",";
    out += "\"repository\":\"" + std::string(kRepository) + "\"}}}";
    return out;
}

bool signed_vertex_format_conformance() {
    CanonicalPipelineKey key{};
    key.vertex_buffer_formats[0] = -1;
    const std::string payload = canonical_payload(key);
    return payload.find("\"vertex_buffer_formats\":[-1,0") != std::string::npos &&
           payload.find("4294967295") == std::string::npos;
}

} // namespace

int main() {
    const CanonicalPipelineKey key = fixture_key();
    const std::string payload = canonical_payload(key);
    Sha256 hash;
    hash.update(payload);
    const std::string identity = "pipeline:sha256:" + hash.finish_hex();
    std::cout << payload << '\n' << identity << '\n';
    return identity == kExpectedIdentity && signed_vertex_format_conformance() ? 0 : 2;
}
