// gdbot-launch: starts the frozen GD copy suspended, loads gdbot_bridge.dll into it,
// runs gdbot_init, and resumes the game only if init returned 0 (build matched and
// isolation installed). Otherwise the game process is terminated before any game code runs.
//
// Usage: gdbot-launch.exe [--game <dir containing GeometryDash.exe>] [--dll <bridge dll>] [--instance N]
// --instance N (1..63) starts a parallel copy whose discovery, log and save live in gdbot\inst<N>\.
// Defaults: --game <repo>\game\2.2091 (found relative to this exe), --dll next to this exe.
#include <windows.h>
#include <tlhelp32.h>
#include <cstdio>
#include <string>

namespace {

std::wstring dir_of(const std::wstring& p) { return p.substr(0, p.find_last_of(L"\\/")); }

std::wstring full_path(const std::wstring& p) {
    wchar_t buf[MAX_PATH * 4];
    DWORD n = GetFullPathNameW(p.c_str(), DWORD(std::size(buf)), buf, nullptr);
    return (n && n < std::size(buf)) ? std::wstring(buf) : p;
}

bool file_exists(const std::wstring& p) {
    DWORD a = GetFileAttributesW(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

bool process_running(const wchar_t* name) {
    HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (s == INVALID_HANDLE_VALUE) return false;
    PROCESSENTRY32W e{sizeof(e)};
    bool found = false;
    for (BOOL ok = Process32FirstW(s, &e); ok; ok = Process32NextW(s, &e))
        if (_wcsicmp(e.szExeFile, name) == 0) { found = true; break; }
    CloseHandle(s);
    return found;
}

uintptr_t remote_module_base(DWORD pid, const wchar_t* name) {
    for (int attempt = 0; attempt < 20; ++attempt) {
        HANDLE s = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
        if (s == INVALID_HANDLE_VALUE) { Sleep(50); continue; }
        MODULEENTRY32W m{sizeof(m)};
        uintptr_t base = 0;
        for (BOOL ok = Module32FirstW(s, &m); ok; ok = Module32NextW(s, &m))
            if (_wcsicmp(m.szModule, name) == 0) { base = reinterpret_cast<uintptr_t>(m.modBaseAddr); break; }
        CloseHandle(s);
        if (base) return base;
        Sleep(50);
    }
    return 0;
}

bool run_remote(HANDLE proc, LPTHREAD_START_ROUTINE fn, void* arg, DWORD timeout_ms, DWORD* code) {
    HANDLE t = CreateRemoteThread(proc, nullptr, 0, fn, arg, 0, nullptr);
    if (!t) return false;
    DWORD w = WaitForSingleObject(t, timeout_ms);
    bool ok = (w == WAIT_OBJECT_0) && GetExitCodeThread(t, code);
    CloseHandle(t);
    return ok;
}

const wchar_t* init_reason(DWORD c) {
    switch (c) {
        case 0: return L"ok";
        case 1: return L"could not open gdbot\\bridge.log";
        case 2: return L"BUILD MISMATCH: this GeometryDash.exe has no verified offsets file";
        case 3: return L"ISOLATION INCOMPLETE: save redirect / file guard / HTTP block could not be installed";
        case 4: return L"MinHook init/enable failed";
        case 5: return L"could not resolve paths";
        case 6: return L"GAME HOOKS INCOMPLETE: a required game hook or the control pipe could not be installed";
        default: return L"unknown";
    }
}

int fail(PROCESS_INFORMATION& pi, const wchar_t* msg) {
    fwprintf(stderr, L"gdbot-launch: %ls\n", msg);
    if (pi.hProcess) {
        TerminateProcess(pi.hProcess, 1);
        fwprintf(stderr, L"gdbot-launch: game process terminated before it ran.\n");
    }
    return 1;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    wchar_t self[MAX_PATH * 4];
    GetModuleFileNameW(nullptr, self, DWORD(std::size(self)));
    std::wstring self_dir = dir_of(self);
    std::wstring dll = self_dir + L"\\gdbot_bridge.dll";
    std::wstring game;
    int instance = 0;  // parallel copies: slot N gets its own pipe, discovery, log and save under gdbot\inst<N>
    for (int i = 1; i + 1 < argc; ++i) {
        if (!wcscmp(argv[i], L"--game")) game = argv[++i];
        else if (!wcscmp(argv[i], L"--dll")) dll = argv[++i];
        else if (!wcscmp(argv[i], L"--instance")) instance = _wtoi(argv[++i]);
    }
    if (game.empty()) {
        // build dir is <repo>\mod\build\<config>; walk up until <repo>\game\2.2091 exists
        std::wstring d = self_dir;
        for (int i = 0; i < 6 && game.empty(); ++i) {
            if (file_exists(d + L"\\game\\2.2091\\GeometryDash.exe")) game = d + L"\\game\\2.2091";
            d = dir_of(d);
        }
    }
    game = full_path(game);
    dll = full_path(dll);
    std::wstring exe = game + L"\\GeometryDash.exe";
    PROCESS_INFORMATION pi{};
    if (!file_exists(exe)) return fail(pi, (L"GeometryDash.exe not found in " + game).c_str());
    if (!file_exists(dll)) return fail(pi, (L"bridge DLL not found: " + dll).c_str());
    if (!process_running(L"steam.exe")) fwprintf(stderr, L"gdbot-launch: warning: Steam does not appear to be running.\n");
    if (instance < 0 || instance > 63) return fail(pi, L"--instance must be 0..63");
    if (process_running(L"GeometryDash.exe") && instance == 0)
        fwprintf(stderr, L"gdbot-launch: warning: another GeometryDash.exe is already running "
                         L"(use --instance N for a parallel copy).\n");
    // The child inherits this; the bridge reads it to pick its per-instance directory.
    SetEnvironmentVariableW(L"GDBOT_INSTANCE", instance ? std::to_wstring(instance).c_str() : nullptr);
    std::wstring inst_dir = game + L"\\gdbot" + (instance ? L"\\inst" + std::to_wstring(instance) : L"");
    if (instance) {
        // A brand-new profile crashes on its first level load, so a new slot starts from a copy of
        // slot 0's bot save (never the user's real save). Existing slot saves are left alone.
        CreateDirectoryW(inst_dir.c_str(), nullptr);
        CreateDirectoryW((inst_dir + L"\\save").c_str(), nullptr);
        for (const wchar_t* f : {L"CCGameManager.dat", L"CCLocalLevels.dat"}) {
            std::wstring src = game + L"\\gdbot\\save\\" + f, dst = inst_dir + L"\\save\\" + f;
            if (file_exists(src) && !file_exists(dst) && !CopyFileW(src.c_str(), dst.c_str(), TRUE))
                return fail(pi, (L"could not seed instance save: " + dst).c_str());
        }
    }

    // Each slot loads its own copy of the bridge, so the build output (mod/build/Release) is never
    // locked by a running game and the bridge can be rebuilt while other slots keep training.
    CreateDirectoryW(inst_dir.c_str(), nullptr);
    std::wstring slot_dll = inst_dir + L"\\gdbot_bridge.dll";
    if (!CopyFileW(dll.c_str(), slot_dll.c_str(), FALSE))
        return fail(pi, (L"could not copy the bridge DLL to " + slot_dll + L" (is this slot's game still running?)").c_str());
    dll = slot_dll;

    // Find gdbot_init's RVA by mapping the DLL locally without running it.
    HMODULE local = LoadLibraryExW(dll.c_str(), nullptr, DONT_RESOLVE_DLL_REFERENCES);
    if (!local) return fail(pi, L"could not map bridge DLL locally");
    auto init_local = reinterpret_cast<uintptr_t>(GetProcAddress(local, "gdbot_init"));
    if (!init_local) return fail(pi, L"bridge DLL has no gdbot_init export");
    uintptr_t init_rva = init_local - reinterpret_cast<uintptr_t>(local);
    FreeLibrary(local);

    STARTUPINFOW si{sizeof(si)};
    si.dwFlags = STARTF_USESHOWWINDOW;  // shown but unfocused; never start minimized (it stalls the bridge)
    si.wShowWindow = SW_SHOWNOACTIVATE;
    std::wstring cmd = L"\"" + exe + L"\"";
    if (!CreateProcessW(exe.c_str(), cmd.data(), nullptr, nullptr, FALSE, CREATE_SUSPENDED, nullptr,
                        game.c_str(), &si, &pi))
        return fail(pi, L"CreateProcess failed");
    wprintf(L"gdbot-launch: started GD suspended, pid %lu\n", pi.dwProcessId);

    size_t bytes = (dll.size() + 1) * sizeof(wchar_t);
    void* remote_path = VirtualAllocEx(pi.hProcess, nullptr, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote_path || !WriteProcessMemory(pi.hProcess, remote_path, dll.c_str(), bytes, nullptr))
        return fail(pi, L"could not write DLL path into the game process");
    auto load_library = reinterpret_cast<LPTHREAD_START_ROUTINE>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW"));
    DWORD code = 0;
    if (!run_remote(pi.hProcess, load_library, remote_path, 30000, &code) || code == 0)
        return fail(pi, L"remote LoadLibraryW failed");
    VirtualFreeEx(pi.hProcess, remote_path, 0, MEM_RELEASE);

    uintptr_t base = remote_module_base(pi.dwProcessId, L"gdbot_bridge.dll");
    if (!base) return fail(pi, L"bridge DLL not found in the game process after loading");
    if (!run_remote(pi.hProcess, reinterpret_cast<LPTHREAD_START_ROUTINE>(base + init_rva), nullptr, 60000, &code))
        return fail(pi, L"gdbot_init did not complete");
    if (code != 0) return fail(pi, init_reason(code));

    ResumeThread(pi.hThread);
    wprintf(L"gdbot-launch: bridge ready, game resumed (instance %d). Discovery: %ls\\bridge.json  Log: %ls\\bridge.log\n",
            instance, inst_dir.c_str(), inst_dir.c_str());
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
