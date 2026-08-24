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

void append_zero_blend(std::string& out) {
    out += "{\"alpha_dst_factor\":0,\"alpha_func\":0,\"alpha_src_factor\":0,\"color_dst_factor\":0,\"color_func\":0,\"color_src_factor\":0,\"disable_rop3\":0,\"enable\":0,\"separate_alpha_blend\":0}";
}

void append_color_buffer(std::string& out, int data_format, const std::array<int,4>& swizzle) {
    out += "{\"data_format\":" + std::to_string(data_format) + ",\"export_format\":0,\"num_conversion\":0,\"num_format\":0,\"swizzle\":[";
    for (std::size_t i=0;i<swizzle.size();++i) { if (i) out.push_back(','); out += std::to_string(swizzle[i]); }
    out += "]}";
}

std::string canonical_payload() {
    std::string out;
    out.reserve(5000);
    out += "{\"kind\":\"pipeline\",\"value\":{\"canonical_key\":{";
    out += "\"blend_controls\":[";
    for (int i=0;i<8;++i) { if (i) out.push_back(','); append_zero_blend(out); }
    out += "],\"cb_shader_mask\":15,\"clip_space\":0,\"color_buffers\":[";
    append_color_buffer(out, 1, {4,5,6,7});
    for (int i=1;i<8;++i) { out.push_back(','); append_color_buffer(out, 0, {0,0,0,0}); }
    out += "],\"color_samples\":[1,0,0,0,0,0,0,0],\"depth_clamp_enable\":0,\"depth_clip_enable\":1,\"depth_samples\":1,\"logic_op\":0,\"mrt_mask\":1,\"num_color_attachments\":1,\"num_samples\":1,\"patch_control_points\":0,\"polygon_mode\":0,\"prim_type\":3,\"provoking_vtx_last\":0,\"stage_hashes\":[1229782938247303441,0,0,0,2459565876494606882,0],\"stencil_format\":0,\"vertex_buffer_formats\":[";
    for (int i=0;i<32;++i) { if (i) out.push_back(','); out.push_back('0'); }
    out += "],\"write_masks\":[15,0,0,0,0,0,0,0],\"z_format\":0},";
    out += "\"key_surface_sha256\":\"" + std::string(kSurfaceDigest) + "\",\"key_surface_version\":\"" + std::string(kSurfaceVersion) + "\",\"source\":{\"commit\":\"" + std::string(kCommit) + "\",\"repository\":\"" + std::string(kRepository) + "\"}}}";
    return out;
}

} // namespace

int main() {
    const std::string payload = canonical_payload();
    Sha256 hash;
    hash.update(payload);
    const std::string identity = "pipeline:sha256:" + hash.finish_hex();
    std::cout << payload << '\n' << identity << '\n';
    return identity == kExpectedIdentity ? 0 : 2;
}
