#pragma once
// Minimal thread-safe line logger. Opened once in init, before any hook is enabled,
// so the file handle never goes through our own CreateFile guard.
#include <windows.h>
#include <cstdarg>
#include <cstdio>
#include <string>

namespace gdbot::log {

inline FILE* g_file = nullptr;
inline CRITICAL_SECTION g_cs;
inline LARGE_INTEGER g_qpf{}, g_t0{};

inline bool open(const std::wstring& path) {
    InitializeCriticalSection(&g_cs);
    QueryPerformanceFrequency(&g_qpf);
    QueryPerformanceCounter(&g_t0);
    g_file = _wfopen(path.c_str(), L"a");
    return g_file != nullptr;
}

inline double now_ms() {
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return double(t.QuadPart - g_t0.QuadPart) * 1000.0 / double(g_qpf.QuadPart);
}

inline void write(const char* fmt, ...) {
    if (!g_file) return;
    char buf[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    EnterCriticalSection(&g_cs);
    fprintf(g_file, "[%10.3f ms][t%05lu] %s\n", now_ms(), GetCurrentThreadId(), buf);
    fflush(g_file);
    LeaveCriticalSection(&g_cs);
}

}  // namespace gdbot::log

#define GLOG(...) ::gdbot::log::write(__VA_ARGS__)
