#include <windows.h>
#include <bcrypt.h>
#include <string>
#include <vector>
#include "bridge.hpp"

#pragma comment(lib, "bcrypt.lib")

namespace gdbot {

std::string sha256_file_hex(const std::wstring& path) {
    HANDLE f = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
    if (f == INVALID_HANDLE_VALUE) return {};
    BCRYPT_ALG_HANDLE alg = nullptr;
    BCRYPT_HASH_HANDLE h = nullptr;
    std::string out;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) == 0 &&
        BCryptCreateHash(alg, &h, nullptr, 0, nullptr, 0, 0) == 0) {
        std::vector<unsigned char> buf(1 << 20);
        DWORD n = 0;
        bool ok = true;
        while (ReadFile(f, buf.data(), DWORD(buf.size()), &n, nullptr) && n > 0) {
            if (BCryptHashData(h, buf.data(), n, 0) != 0) { ok = false; break; }
        }
        unsigned char digest[32];
        if (ok && BCryptFinishHash(h, digest, sizeof(digest), 0) == 0) {
            static const char* hex = "0123456789abcdef";
            for (unsigned char c : digest) { out += hex[c >> 4]; out += hex[c & 15]; }
        }
    }
    if (h) BCryptDestroyHash(h);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    CloseHandle(f);
    return out;
}

}  // namespace gdbot
