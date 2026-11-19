// Isolation layer: keeps the bot's GD copy away from the user's real save and the internet.
//   1. File guard: any CreateFile/Move/Delete/CreateDirectory/Replace touching
//      %LOCALAPPDATA%\GeometryDash (the real, Steam-Cloud-synced save) is denied.
//   2. Save redirect: CCFileUtilsWin32::getWritablePath -> <game>\gdbot\save\.
//   3. HTTP block: CCHttpClient::send and curl_easy_perform never reach the network.
//   4. GameLevelManager::updateUserScore is a no-op.
// Layer 0 is outside the process: Windows Firewall rules on the frozen exe.
#include <windows.h>
#include <MinHook.h>
#include <atomic>
#include <cwctype>
#include <new>
#include <string>
#include "bridge.hpp"
#include "log.hpp"

namespace gdbot {
namespace {

std::atomic<int> g_denied{0};
std::atomic<int> g_http_blocked{0};
std::atomic<int> g_curl_blocked{0};
std::atomic<int> g_curl_multi_seen{0};

bool under_real_save(const wchar_t* p) {
    if (!p || !*p) return false;
    wchar_t full[MAX_PATH * 4];
    DWORD n = GetFullPathNameW(p, DWORD(std::size(full)), full, nullptr);
    if (n == 0 || n >= std::size(full)) return false;
    const std::wstring& root = g_paths.real_save_dir;
    if (n < root.size()) return false;
    if (_wcsnicmp(full, root.c_str(), root.size()) != 0) return false;
    wchar_t next = full[root.size()];
    return next == L'\0' || next == L'\\' || next == L'/';
}

bool under_real_save_a(const char* p) {
    if (!p) return false;
    wchar_t w[MAX_PATH * 4];
    if (!MultiByteToWideChar(CP_ACP, 0, p, -1, w, int(std::size(w)))) return false;
    return under_real_save(w);
}

void deny(const char* api, const wchar_t* path) {
    int c = ++g_denied;
    if (c <= 64 || (c % 1000) == 0) GLOG("ISOLATION deny #%d %s %ls", c, api, path ? path : L"(null)");
    SetLastError(ERROR_ACCESS_DENIED);
}

// ---- file guard ----
using CreateFileW_t = HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using CreateFileA_t = HANDLE(WINAPI*)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
using CreateFile2_t = HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, DWORD, LPCREATEFILE2_EXTENDED_PARAMETERS);
using MoveFileExW_t = BOOL(WINAPI*)(LPCWSTR, LPCWSTR, DWORD);
using MoveFileWithProgressW_t = BOOL(WINAPI*)(LPCWSTR, LPCWSTR, LPPROGRESS_ROUTINE, LPVOID, DWORD);
using DeleteFileW_t = BOOL(WINAPI*)(LPCWSTR);
using CreateDirectoryW_t = BOOL(WINAPI*)(LPCWSTR, LPSECURITY_ATTRIBUTES);
using ReplaceFileW_t = BOOL(WINAPI*)(LPCWSTR, LPCWSTR, LPCWSTR, DWORD, LPVOID, LPVOID);
using CopyFileExW_t = BOOL(WINAPI*)(LPCWSTR, LPCWSTR, LPPROGRESS_ROUTINE, LPVOID, LPBOOL, DWORD);

CreateFileW_t o_CreateFileW;
CreateFileA_t o_CreateFileA;
CreateFile2_t o_CreateFile2;
MoveFileExW_t o_MoveFileExW;
MoveFileWithProgressW_t o_MoveFileWithProgressW;
DeleteFileW_t o_DeleteFileW;
CreateDirectoryW_t o_CreateDirectoryW;
ReplaceFileW_t o_ReplaceFileW;
CopyFileExW_t o_CopyFileExW;

HANDLE WINAPI h_CreateFileW(LPCWSTR p, DWORD a, DWORD s, LPSECURITY_ATTRIBUTES sa, DWORD c, DWORD f, HANDLE t) {
    if (under_real_save(p)) { deny("CreateFileW", p); return INVALID_HANDLE_VALUE; }
    return o_CreateFileW(p, a, s, sa, c, f, t);
}
HANDLE WINAPI h_CreateFileA(LPCSTR p, DWORD a, DWORD s, LPSECURITY_ATTRIBUTES sa, DWORD c, DWORD f, HANDLE t) {
    if (under_real_save_a(p)) { deny("CreateFileA", L"(ansi path)"); return INVALID_HANDLE_VALUE; }
    return o_CreateFileA(p, a, s, sa, c, f, t);
}
HANDLE WINAPI h_CreateFile2(LPCWSTR p, DWORD a, DWORD s, DWORD c, LPCREATEFILE2_EXTENDED_PARAMETERS x) {
    if (under_real_save(p)) { deny("CreateFile2", p); return INVALID_HANDLE_VALUE; }
    return o_CreateFile2(p, a, s, c, x);
}
BOOL WINAPI h_MoveFileExW(LPCWSTR a, LPCWSTR b, DWORD f) {
    if (under_real_save(a) || under_real_save(b)) { deny("MoveFileExW", a); return FALSE; }
    return o_MoveFileExW(a, b, f);
}
BOOL WINAPI h_MoveFileWithProgressW(LPCWSTR a, LPCWSTR b, LPPROGRESS_ROUTINE r, LPVOID d, DWORD f) {
    if (under_real_save(a) || under_real_save(b)) { deny("MoveFileWithProgressW", a); return FALSE; }
    return o_MoveFileWithProgressW(a, b, r, d, f);
}
BOOL WINAPI h_DeleteFileW(LPCWSTR p) {
    if (under_real_save(p)) { deny("DeleteFileW", p); return FALSE; }
    return o_DeleteFileW(p);
}
BOOL WINAPI h_CreateDirectoryW(LPCWSTR p, LPSECURITY_ATTRIBUTES sa) {
    if (under_real_save(p)) { deny("CreateDirectoryW", p); return FALSE; }
    return o_CreateDirectoryW(p, sa);
}
BOOL WINAPI h_ReplaceFileW(LPCWSTR a, LPCWSTR b, LPCWSTR c, DWORD f, LPVOID e1, LPVOID e2) {
    if (under_real_save(a) || under_real_save(b) || under_real_save(c)) { deny("ReplaceFileW", a); return FALSE; }
    return o_ReplaceFileW(a, b, c, f, e1, e2);
}
BOOL WINAPI h_CopyFileExW(LPCWSTR a, LPCWSTR b, LPPROGRESS_ROUTINE r, LPVOID d, LPBOOL cancel, DWORD f) {
    if (under_real_save(a) || under_real_save(b)) { deny("CopyFileExW", a); return FALSE; }
    return o_CopyFileExW(a, b, r, d, cancel, f);
}

// ---- save redirect (MSVC x64: this in rcx, hidden std::string* return slot in rdx) ----
using GetWritablePath_t = std::string*(__fastcall*)(void*, std::string*);
GetWritablePath_t o_getWritablePath;
GetWritablePath_t o_getWritablePath2;
std::string g_save_dir_a;
std::atomic<int> g_gwp_calls{0};
std::atomic<int> g_gwp2_calls{0};

std::string* __fastcall h_getWritablePath(void* self, std::string* out) {
    if (++g_gwp_calls <= 3) GLOG("getWritablePath -> %s (redirected)", g_save_dir_a.c_str());
    return new (out) std::string(g_save_dir_a);
}
std::string* __fastcall h_getWritablePath2(void* self, std::string* out) {
    std::string* r = o_getWritablePath2(self, out);  // observe only
    if (++g_gwp2_calls <= 3) GLOG("getWritablePath2 -> %s (observed, not redirected)", r->c_str());
    return r;
}

// ---- network ----
using HttpSend_t = void(__fastcall*)(void*, void*);
HttpSend_t o_HttpSend;
void __fastcall h_HttpSend(void* self, void* req) {
    int c = ++g_http_blocked;
    if (c <= 32 || (c % 100) == 0) GLOG("ISOLATION blocked CCHttpClient::send #%d", c);
    // Dropped: the request is never retained or queued, so no callback fires.
}

using CurlEasyPerform_t = int(__cdecl*)(void*);
CurlEasyPerform_t o_curl_easy_perform;
int __cdecl h_curl_easy_perform(void* h) {
    int c = ++g_curl_blocked;
    if (c <= 32 || (c % 100) == 0) GLOG("ISOLATION blocked curl_easy_perform #%d", c);
    return 7;  // CURLE_COULDNT_CONNECT
}

using CurlMultiPerform_t = int(__cdecl*)(void*, int*);
CurlMultiPerform_t o_curl_multi_perform;
int __cdecl h_curl_multi_perform(void* m, int* running) {
    // Observed only (firewall blocks the traffic). Logged so we learn whether 2.209 uses it.
    int c = ++g_curl_multi_seen;
    if (c == 1 || (c % 1000) == 0) GLOG("observed curl_multi_perform #%d (firewall-blocked)", c);
    return o_curl_multi_perform(m, running);
}

using Void0_t = void(__fastcall*)(void*);
Void0_t o_updateUserScore;
void __fastcall h_updateUserScore(void*) { GLOG("ISOLATION blocked GameLevelManager::updateUserScore"); }

// ---- exit diagnostics: who ends the process (parallel instances died with no crash report) ----
void log_exit_stack(const char* what, unsigned code) {
    void* frames[24] = {};
    USHORT n = RtlCaptureStackBackTrace(1, 24, frames, nullptr);
    GLOG("%s(code=%u) called; stack:", what, code);
    for (USHORT i = 0; i < n; ++i) {
        HMODULE m = nullptr;
        wchar_t name[MAX_PATH] = L"?";
        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               (LPCWSTR)frames[i], &m) && m) {
            GetModuleFileNameW(m, name, MAX_PATH);
            const wchar_t* base = wcsrchr(name, L'\\');
            GLOG("  #%u %ls+0x%llx", i, base ? base + 1 : name, (unsigned long long)((char*)frames[i] - (char*)m));
        } else {
            GLOG("  #%u %p", i, frames[i]);
        }
    }
}
LONG CALLBACK log_access_violation(EXCEPTION_POINTERS* e) {
    static std::atomic<int> s_n{0};
    DWORD c = e->ExceptionRecord->ExceptionCode;
    if ((c == EXCEPTION_ACCESS_VIOLATION || c == 0xC0000409 || c == EXCEPTION_ILLEGAL_INSTRUCTION) && s_n++ < 3) {
        HMODULE m = nullptr;
        wchar_t name[MAX_PATH] = L"?";
        void* at = e->ExceptionRecord->ExceptionAddress;
        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)at, &m) && m)
            GetModuleFileNameW(m, name, MAX_PATH);
        const wchar_t* base = wcsrchr(name, L'\\');
        GLOG("exception 0x%08lx at %ls+0x%llx (first-chance; addr %p, info %llx)", c, base ? base + 1 : name,
             (unsigned long long)((char*)at - (char*)m), at,
             (unsigned long long)(e->ExceptionRecord->NumberParameters > 1 ? e->ExceptionRecord->ExceptionInformation[1] : 0));
        log_exit_stack("  at exception", c);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
using ExitProcess_t = void(WINAPI*)(UINT);
ExitProcess_t o_ExitProcess;
void WINAPI h_ExitProcess(UINT code) { log_exit_stack("ExitProcess", code); o_ExitProcess(code); }
using TerminateProcess_t = BOOL(WINAPI*)(HANDLE, UINT);
TerminateProcess_t o_TerminateProcess;
BOOL WINAPI h_TerminateProcess(HANDLE h, UINT code) {
    if (h == GetCurrentProcess() || GetProcessId(h) == GetCurrentProcessId()) log_exit_stack("TerminateProcess(self)", code);
    return o_TerminateProcess(h, code);
}

// ---- helpers ----
bool api_hook(const wchar_t* mod, const char* fn, void* detour, void** orig) {
    MH_STATUS s = MH_CreateHookApi(mod, fn, detour, orig);
    if (s != MH_OK) GLOG("hook FAIL %ls!%s: %s", mod, fn, MH_StatusToString(s));
    return s == MH_OK;
}

bool export_hook(const wchar_t* dll, const char* sym, void* detour, void** orig) {
    HMODULE m = GetModuleHandleW(dll);
    if (!m) m = LoadLibraryW(dll);
    void* target = m ? reinterpret_cast<void*>(GetProcAddress(m, sym)) : nullptr;
    if (!target) { GLOG("hook FAIL %ls!%s: export not found", dll, sym); return false; }
    MH_STATUS s = MH_CreateHook(target, detour, orig);
    if (s != MH_OK) { GLOG("hook FAIL %ls!%s: %s", dll, sym, MH_StatusToString(s)); return false; }
    return true;
}

}  // namespace

bool install_isolation() {
    int c = WideCharToMultiByte(CP_ACP, 0, g_paths.save_dir.c_str(), -1, nullptr, 0, nullptr, nullptr);
    g_save_dir_a.resize(c > 0 ? c - 1 : 0);
    WideCharToMultiByte(CP_ACP, 0, g_paths.save_dir.c_str(), -1, g_save_dir_a.data(), c, nullptr, nullptr);

    bool fg = true;
    fg &= api_hook(L"kernelbase", "CreateFileW", (void*)h_CreateFileW, (void**)&o_CreateFileW);
    fg &= api_hook(L"kernelbase", "CreateFileA", (void*)h_CreateFileA, (void**)&o_CreateFileA);
    fg &= api_hook(L"kernelbase", "CreateFile2", (void*)h_CreateFile2, (void**)&o_CreateFile2);
    fg &= api_hook(L"kernelbase", "MoveFileExW", (void*)h_MoveFileExW, (void**)&o_MoveFileExW);
    fg &= api_hook(L"kernelbase", "MoveFileWithProgressW", (void*)h_MoveFileWithProgressW, (void**)&o_MoveFileWithProgressW);
    fg &= api_hook(L"kernelbase", "DeleteFileW", (void*)h_DeleteFileW, (void**)&o_DeleteFileW);
    fg &= api_hook(L"kernelbase", "CreateDirectoryW", (void*)h_CreateDirectoryW, (void**)&o_CreateDirectoryW);
    fg &= api_hook(L"kernelbase", "ReplaceFileW", (void*)h_ReplaceFileW, (void**)&o_ReplaceFileW);
    fg &= api_hook(L"kernelbase", "CopyFileExW", (void*)h_CopyFileExW, (void**)&o_CopyFileExW);
    g_iso.file_guard = fg;

    g_iso.saves_redirected = export_hook(L"libcocos2d.dll",
        "?getWritablePath@CCFileUtilsWin32@cocos2d@@UEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@XZ",
        (void*)h_getWritablePath, (void**)&o_getWritablePath);
    export_hook(L"libcocos2d.dll",
        "?getWritablePath2@CCFileUtilsWin32@cocos2d@@UEAA?AV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@XZ",
        (void*)h_getWritablePath2, (void**)&o_getWritablePath2);

    bool hb = export_hook(L"libExtensions.dll", "?send@CCHttpClient@extension@cocos2d@@QEAAXPEAVCCHttpRequest@23@@Z",
                          (void*)h_HttpSend, (void**)&o_HttpSend);
    hb &= export_hook(L"libcurl.dll", "curl_easy_perform", (void*)h_curl_easy_perform, (void**)&o_curl_easy_perform);
    export_hook(L"libcurl.dll", "curl_multi_perform", (void*)h_curl_multi_perform, (void**)&o_curl_multi_perform);
    api_hook(L"kernel32", "ExitProcess", (void*)h_ExitProcess, (void**)&o_ExitProcess);
    AddVectoredExceptionHandler(1, log_access_violation);
    api_hook(L"kernelbase", "TerminateProcess", (void*)h_TerminateProcess, (void**)&o_TerminateProcess);
    g_iso.http_blocked = hb;

    if (void* p = rva_ptr(offsets::GameLevelManager__updateUserScore)) {
        g_iso.score_upload_blocked = MH_CreateHook(p, (void*)h_updateUserScore, (void**)&o_updateUserScore) == MH_OK;
    }

    GLOG("isolation: file_guard=%d saves_redirected=%d http_blocked=%d score_upload_blocked=%d",
         g_iso.file_guard, g_iso.saves_redirected, g_iso.http_blocked, g_iso.score_upload_blocked);
    return g_iso.file_guard && g_iso.saves_redirected && g_iso.http_blocked;
}

}  // namespace gdbot
