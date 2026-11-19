// gdbot bridge DLL entry. The launcher (injector/) starts GD suspended, loads this DLL,
// calls gdbot_init in a remote thread, and resumes the game only if it returns 0.
// DllMain does nothing: all setup happens in gdbot_init, outside the loader lock.
#include <windows.h>
#include <MinHook.h>
#include <shlobj.h>
#include <string>
#include "bridge.hpp"
#include "log.hpp"

#pragma comment(lib, "shell32.lib")

namespace {

enum InitResult : DWORD {
    kOk = 0,
    kLogFailed = 1,
    kBuildMismatch = 2,
    kIsolationFailed = 3,
    kHookEnableFailed = 4,
    kPathsFailed = 5,
    kHooksFailed = 6,
};

bool init_paths() {
    wchar_t exe[MAX_PATH * 4];
    DWORD n = GetModuleFileNameW(nullptr, exe, DWORD(std::size(exe)));
    if (!n || n >= std::size(exe)) return false;
    std::wstring e(exe);
    auto& p = gdbot::g_paths;
    p.game_dir = e.substr(0, e.find_last_of(L"\\/"));
    p.bot_dir = p.game_dir + L"\\gdbot";
    wchar_t slot[16] = {0};
    if (GetEnvironmentVariableW(L"GDBOT_INSTANCE", slot, DWORD(std::size(slot))) && slot[0]) {
        p.slot = _wtoi(slot);
        if (p.slot < 0 || p.slot > 63) return false;
    }
    p.inst_dir = p.slot ? p.bot_dir + L"\\inst" + std::to_wstring(p.slot) : p.bot_dir;
    p.save_dir = p.inst_dir + L"\\save\\";
    PWSTR la = nullptr;
    if (SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &la) != S_OK) return false;
    p.real_save_dir = std::wstring(la) + L"\\GeometryDash";
    CoTaskMemFree(la);
    // #41: the redirected save dir must exist, be a real directory (not a link elsewhere), and not sit under
    // the real save. Fail closed: gdbot_init refuses to start the game otherwise.
    for (const std::wstring& d : {p.bot_dir, p.inst_dir, p.inst_dir + L"\\save"}) {
        if (!CreateDirectoryW(d.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
        DWORD attr = GetFileAttributesW(d.c_str());
        if (attr == INVALID_FILE_ATTRIBUTES || !(attr & FILE_ATTRIBUTE_DIRECTORY) || (attr & FILE_ATTRIBUTE_REPARSE_POINT))
            return false;
    }
    std::wstring root = p.real_save_dir + L"\\";
    if (_wcsnicmp(p.save_dir.c_str(), root.c_str(), root.size()) == 0) return false;
    return true;
}

}  // namespace

extern "C" __declspec(dllexport) DWORD WINAPI gdbot_init(LPVOID) {
    using namespace gdbot;
    if (!init_paths()) return kPathsFailed;
    if (!log::open(g_paths.inst_dir + L"\\bridge.log")) return kLogFailed;
    GLOG("==== gdbot bridge init (pid %lu, instance %d) ====", GetCurrentProcessId(), g_paths.slot);
    GLOG("game_dir=%ls", g_paths.game_dir.c_str());
    GLOG("save_dir=%ls real_save_dir=%ls (guarded)", g_paths.save_dir.c_str(), g_paths.real_save_dir.c_str());

    wchar_t exe[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, exe, DWORD(std::size(exe)));
    std::string sha = sha256_file_hex(exe);
    for (const auto& b : offsets::kBuilds)
        if (sha == b.exe_sha256) g_build = &b;
    if (!g_build) {
        GLOG("BUILD MISMATCH: exe sha256=%s has no offsets file. Bridge stays inactive.", sha.c_str());
        return kBuildMismatch;
    }
    g_exe_base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    GLOG("build %s (%s) exe_base=%p", g_build->game_version, g_build->source_file, (void*)g_exe_base);

    if (MH_Initialize() != MH_OK) return kHookEnableFailed;
    if (!install_isolation()) {
        GLOG("ISOLATION INCOMPLETE: refusing to start the game.");
        return kIsolationFailed;
    }
    if (!install_hooks()) {
        GLOG("GAME HOOKS INCOMPLETE: refusing to start the game.");
        return kHooksFailed;
    }
    if (!install_cbf()) GLOG("CBF UNAVAILABLE: steps with fractions will be refused (hello reports cbf=false)");
    if (!start_control()) return kHooksFailed;
    MH_STATUS s = MH_EnableHook(MH_ALL_HOOKS);
    GLOG("MH_EnableHook(all): %s", MH_StatusToString(s));
    if (s != MH_OK) return kHookEnableFailed;
    GLOG("init ok; game may resume");
    return kOk;
}

BOOL APIENTRY DllMain(HMODULE, DWORD, LPVOID) { return TRUE; }
