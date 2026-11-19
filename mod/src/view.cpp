// M8 human view: shared view state (view.json), launch-session defaults, and the on-screen overlay.
// Plan: .coordination/plans/2026-11-19-m8-human-view-and-cbf.md (agreed by both agents).
//
// view.json (gdbot/view.json, shared by every slot like mode.txt): {"overlay": bool, "watch_slot": int|null}.
// Every slot polls it; whichever slot owns the global hotkeys (Ctrl+Alt+V / Ctrl+Alt+O) writes it.
// The overlay is a cocos2d node tree (CCLayerColor panel + CCLabelBMFont lines, GD's own chatFont) added to
// the running scene, so it is drawn with the scene: every frame at 1x, at the present cadence in draw-skip.
#include <windows.h>
#include <psapi.h>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>
#include "bridge.hpp"
#include "log.hpp"

using json = nlohmann::json;

namespace gdbot {
namespace {

// ---- view.json -----------------------------------------------------------------------------------
std::wstring view_file() { return g_paths.bot_dir + L"\\view.json"; }
FILETIME g_view_time{};

void write_view(bool overlay, int watch_slot) {
    json v = {{"overlay", overlay}, {"watch_slot", watch_slot >= 0 ? json(watch_slot) : json()}};
    std::wstring tmp = view_file() + L".tmp." + std::to_wstring(GetCurrentProcessId());
    FILE* f = _wfopen(tmp.c_str(), L"w");
    if (!f) return;
    std::string s = v.dump();
    fputs(s.c_str(), f);
    fclose(f);
    MoveFileExW(tmp.c_str(), view_file().c_str(), MOVEFILE_REPLACE_EXISTING);  // atomic replace
}

bool read_view(bool* overlay, int* watch_slot) {
    FILE* f = _wfopen(view_file().c_str(), L"r");
    if (!f) return false;
    char buf[512] = {0};
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    try {
        json v = json::parse(std::string(buf, n));
        *overlay = v.value("overlay", true);
        *watch_slot = v.contains("watch_slot") && v["watch_slot"].is_number_integer() ? v["watch_slot"].get<int>() : -1;
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

// ---- slots: which bot GD is in the foreground / lowest running (for Ctrl+Alt+V) --------------------
bool pid_alive(DWORD pid) {
    HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!h) return false;
    DWORD code = 0;
    bool alive = GetExitCodeProcess(h, &code) && code == STILL_ACTIVE;
    CloseHandle(h);
    return alive;
}

struct SlotPid { int slot; DWORD pid; };
std::vector<SlotPid> running_slots() {
    std::vector<SlotPid> out;
    for (int s = 0; s < 64; ++s) {
        std::wstring p = s == 0 ? g_paths.bot_dir + L"\\bridge.json"
                                : g_paths.bot_dir + L"\\inst" + std::to_wstring(s) + L"\\bridge.json";
        FILE* f = _wfopen(p.c_str(), L"r");
        if (!f) continue;
        char buf[512] = {0};
        size_t n = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        try {
            json d = json::parse(std::string(buf, n));
            DWORD pid = d.value("pid", 0u);
            if (pid && pid_alive(pid)) out.push_back({s, pid});
        } catch (const std::exception&) {
        }
    }
    return out;
}

int watch_target() {
    auto slots = running_slots();
    if (slots.empty()) return g_paths.slot;
    DWORD fg = 0;
    if (HWND w = GetForegroundWindow()) GetWindowThreadProcessId(w, &fg);
    for (const auto& s : slots)
        if (s.pid == fg) return s.slot;
    return slots.front().slot;  // lowest running slot
}

// ---- cocos2d exports for the overlay ---------------------------------------------------------------
struct CCPoint { float x, y; };
struct CCSize { float w, h; };
struct Color3 { unsigned char r, g, b; };
struct Color4 { unsigned char r, g, b, a; };
using LabelCreate_t = void*(__cdecl*)(const char*, const char*);
using LabelSetString_t = void(__fastcall*)(void*, const char*, bool);  // (str, needUpdateLabel): primary-base virtual
using LabelSetColor_t = void(__fastcall*)(void*, const Color3*);  // CCRGBAProtocol overrider: this = that subobject
using LabelGetColor_t = const Color3*(__fastcall*)(void*);
using LabelSetScale_t = void(__fastcall*)(void*, float);
using LabelSetAnchor_t = void(__fastcall*)(void*, const CCPoint*);
using LayerColorCreate_t = void*(__cdecl*)(const Color4*, float, float);
using LayerSetSize_t = void(__fastcall*)(void*, const CCSize*);
using NodeAddChildZ_t = void(__fastcall*)(void*, void*, int);
using NodeSetPos_t = void(__fastcall*)(void*, float, float);
using NodeGetParent_t = void*(__fastcall*)(void*);
using NodeRemove_t = void(__fastcall*)(void*, bool);
using NodeSetVisible_t = void(__fastcall*)(void*, bool);
using NodeGetSize_t = const CCSize*(__fastcall*)(void*);
using Retain_t = void(__fastcall*)(void*);
using Director_t = void*(__cdecl*)();
using RunningScene_t = void*(__fastcall*)(void*);

struct Cocos {
    LabelCreate_t label_create;
    LabelSetString_t label_set_string;
    LabelSetColor_t label_set_color;
    LabelGetColor_t label_get_color;
    LabelSetScale_t label_set_scale;
    LabelSetAnchor_t label_set_anchor;
    LayerColorCreate_t layer_create;
    LayerSetSize_t layer_set_size;
    NodeAddChildZ_t add_child;
    NodeSetPos_t set_pos;
    NodeGetParent_t get_parent;
    NodeRemove_t remove;
    NodeSetVisible_t set_visible;
    NodeGetSize_t get_size;
    Retain_t retain;
    Director_t director;
    RunningScene_t running_scene;
    bool ok = false;
};
Cocos g_cc;

void load_cocos() {
    static bool s_tried = false;
    if (s_tried) return;
    s_tried = true;
    HMODULE m = GetModuleHandleW(L"libcocos2d.dll");
    if (!m) return;
    auto get = [m](const char* n) { return reinterpret_cast<void*>(GetProcAddress(m, n)); };
    g_cc.label_create = (LabelCreate_t)get("?create@CCLabelBMFont@cocos2d@@SAPEAV12@PEBD0@Z");
    // Not setString(const char*): that one overrides CCLabelProtocol (a secondary base), so MSVC expects
    // `this` at the CCLabelProtocol subobject (its body does `add rcx, -0x168`) and crashed when given the
    // label pointer. setString(const char*, bool) is a CCLabelBMFont virtual on the primary vtable.
    g_cc.label_set_string = (LabelSetString_t)get("?setString@CCLabelBMFont@cocos2d@@UEAAXPEBD_N@Z");
    g_cc.label_set_color = (LabelSetColor_t)get("?setColor@CCLabelBMFont@cocos2d@@UEAAXAEBU_ccColor3B@2@@Z");
    g_cc.label_get_color = (LabelGetColor_t)get("?getColor@CCLabelBMFont@cocos2d@@UEAAAEBU_ccColor3B@2@XZ");
    g_cc.label_set_scale = (LabelSetScale_t)get("?setScale@CCLabelBMFont@cocos2d@@UEAAXM@Z");
    g_cc.label_set_anchor = (LabelSetAnchor_t)get("?setAnchorPoint@CCLabelBMFont@cocos2d@@UEAAXAEBVCCPoint@2@@Z");
    g_cc.layer_create = (LayerColorCreate_t)get("?create@CCLayerColor@cocos2d@@SAPEAV12@AEBU_ccColor4B@2@MM@Z");
    g_cc.layer_set_size = (LayerSetSize_t)get("?setContentSize@CCLayerColor@cocos2d@@UEAAXAEBVCCSize@2@@Z");
    g_cc.add_child = (NodeAddChildZ_t)get("?addChild@CCNode@cocos2d@@UEAAXPEAV12@H@Z");
    g_cc.set_pos = (NodeSetPos_t)get("?setPosition@CCNode@cocos2d@@UEAAXMM@Z");
    g_cc.get_parent = (NodeGetParent_t)get("?getParent@CCNode@cocos2d@@UEAAPEAV12@XZ");
    g_cc.remove = (NodeRemove_t)get("?removeFromParentAndCleanup@CCNode@cocos2d@@UEAAX_N@Z");
    g_cc.set_visible = (NodeSetVisible_t)get("?setVisible@CCNode@cocos2d@@UEAAX_N@Z");
    g_cc.get_size = (NodeGetSize_t)get("?getContentSize@CCNode@cocos2d@@UEBAAEBVCCSize@2@XZ");
    g_cc.retain = (Retain_t)get("?retain@CCObject@cocos2d@@QEAAXXZ");
    g_cc.director = (Director_t)get("?sharedDirector@CCDirector@cocos2d@@SAPEAV12@XZ");
    g_cc.running_scene = (RunningScene_t)get("?getRunningScene@CCDirector@cocos2d@@QEAAPEAVCCScene@2@XZ");
    g_cc.ok = g_cc.label_create && g_cc.label_set_string && g_cc.label_set_scale &&
              g_cc.label_set_anchor && g_cc.layer_create && g_cc.layer_set_size && g_cc.add_child && g_cc.set_pos &&
              g_cc.get_parent && g_cc.remove && g_cc.set_visible && g_cc.get_size && g_cc.retain && g_cc.director &&
              g_cc.running_scene;
    GLOG("overlay: cocos exports %s", g_cc.ok ? "found" : "MISSING (overlay disabled)");
}

// ---- overlay ---------------------------------------------------------------------------------------
// Layout (points; GD's design space is about 569 x 320): a dark translucent panel in the top-left corner.
// Rows have a dim key column and a bright value column, so values line up (chatFont is proportional).
// The title row and the hotkey hint span both columns. The mode row is coloured by mode.
constexpr int kRows = 9;
constexpr float kScale = 0.6f, kLineH = 10.6f, kPad = 6.0f, kKeyW = 50.0f, kWidth = 238.0f, kMargin = 6.0f;
constexpr Color4 kPanel = {10, 12, 18, 182};
constexpr Color3 kTitle = {255, 196, 140}, kText = {236, 240, 246}, kKey = {150, 158, 172}, kDim = {120, 128, 140};
constexpr Color3 kDedicated = {120, 230, 140}, kBackground = {255, 196, 90}, kWatch = {110, 210, 255},
                 kNormal = {200, 200, 200};

// setColor/getColor override CCRGBAProtocol, a secondary base: they take `this` at that subobject. Layout
// (CCSpriteBatchNode, CCLabelProtocol, CCRGBAProtocol): CCLabelProtocol at +0x168 (from setString's thunk),
// CCRGBAProtocol expected 8 bytes later. Verified at runtime on the first label (getColor must return a
// pointer inside the label that reads white); otherwise colours stay off and the text is plain white.
constexpr ptrdiff_t kRgbaOff = 0x170;
bool g_colors_ok = false;
void* g_panel = nullptr;
struct Label { void* node = nullptr; std::string text; Color3 color{0, 0, 0}; };
Label g_key[kRows], g_val[kRows];
int g_used_rows = 0;
bool g_row_span[kRows] = {};
std::string g_job;                       // from set_overlay
std::vector<std::string> g_client_lines;  // from set_overlay (at most 3; "Key\tvalue" or plain text)

void* make_label() {
    void* l = g_cc.label_create(" ", "chatFont.fnt");
    if (!l) return nullptr;
    static bool s_checked = false;
    if (!s_checked && g_cc.label_set_color && g_cc.label_get_color) {
        s_checked = true;
        char* base = static_cast<char*>(l);
        const Color3* c = g_cc.label_get_color(base + kRgbaOff);
        const char* cp = reinterpret_cast<const char*>(c);
        Color3 v{};
        g_colors_ok = cp > base && cp < base + 0x800 && safe_copy(&v, c, sizeof v) && v.r == 255 && v.g == 255 && v.b == 255;
        GLOG("overlay: label colour interface at +0x%llx %s", (unsigned long long)kRgbaOff,
             g_colors_ok ? "verified" : "NOT verified (plain white text)");
    }
    const CCPoint top_left = {0.0f, 1.0f};
    g_cc.label_set_scale(l, kScale);
    g_cc.label_set_anchor(l, &top_left);
    g_cc.add_child(g_panel, l, 1);
    return l;
}

void build_overlay() {
    if (g_panel || !g_cc.ok) return;
    g_panel = g_cc.layer_create(&kPanel, kWidth, kPad * 2 + kLineH * kRows);
    if (!g_panel) return;
    g_cc.retain(g_panel);  // survives scene changes; re-parented each time the running scene changes
    for (int i = 0; i < kRows; ++i) {
        g_key[i].node = make_label();
        g_val[i].node = make_label();
    }
    GLOG("overlay: built (%d rows)", kRows);
}

std::string thousands(long long v) {
    std::string s = std::to_string(v < 0 ? -v : v), out;
    for (size_t i = 0; i < s.size(); ++i) {
        if (i && (s.size() - i) % 3 == 0) out += ',';
        out += s[i];
    }
    return v < 0 ? "-" + out : out;
}

std::string fmt(const char* f, double a, double b = 0, double c = 0) {
    char buf[160];
    snprintf(buf, sizeof(buf), f, a, b, c);
    return buf;
}

std::string ascii(const std::string& s, size_t max_len) {
    std::string out;
    for (unsigned char ch : s) {
        if (out.size() >= max_len) break;
        out += ((ch >= 32 && ch < 127) || ch == '\t') ? char(ch) : '?';
    }
    return out;
}

double private_mb() {
    PROCESS_MEMORY_COUNTERS_EX pmc{};
    pmc.cb = sizeof(pmc);
    return K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), pmc.cb)
               ? double(pmc.PrivateUsage) / (1024.0 * 1024.0) : 0.0;
}

double avail_mb() {
    MEMORYSTATUSEX m{};
    m.dwLength = sizeof(m);
    return GlobalMemoryStatusEx(&m) ? double(m.ullAvailPhys) / (1024.0 * 1024.0) : 0.0;
}

void set_label(Label& l, const std::string& text, Color3 color) {
    if (!l.node) return;
    if (text != l.text) {
        g_cc.label_set_string(l.node, text.empty() ? " " : text.c_str(), true);
        l.text = text;
    }
    if (g_colors_ok && (color.r != l.color.r || color.g != l.color.g || color.b != l.color.b)) {
        g_cc.label_set_color(static_cast<char*>(l.node) + kRgbaOff, &color);
        l.color = color;
    }
}

void update_overlay(const char* mode_label, float progress, double tps) {
    struct Row { std::string key, value; Color3 color; bool span; };
    std::vector<Row> rows;
    std::string title = "BABYZOINK   slot " + std::to_string(g_paths.slot);
    if (!g_job.empty()) title += "   " + g_job;
    rows.push_back({"", title, kTitle, true});
    rows.push_back({"Level", ascii(g_vstats.level, 40), kText, false});
    Color3 mc = kNormal;
    std::string mode = mode_label;
    if (g_watch) { mode = "WATCH 1x"; mc = kWatch; }
    else if (mode == "dedicated") { mode = "DEDICATED"; mc = kDedicated; }
    else if (mode == "background") { mode = "BACKGROUND"; mc = kBackground; }
    else mode = "NORMAL";
    std::string speed = tps > 0.5 ? fmt("%.1fx real time   %.0f ticks/s", tps / 240.0, tps) : "idle";
    rows.push_back({"Mode", mode + "    " + speed, mc, false});
    rows.push_back({"Attempts", thousands(g_vstats.runs) + " full runs    " + thousands(g_vstats.practice) + " practice",
                    kText, false});
    if (g_layer) rows.push_back({"Progress", fmt("%.1f%%      best %.1f%%", progress * 100.0, g_vstats.best * 100.0), kText, false});
    for (const auto& l : g_client_lines) {
        size_t tab = l.find('\t');
        if (tab == std::string::npos) rows.push_back({"", l, kText, true});
        else rows.push_back({l.substr(0, tab), l.substr(tab + 1), kText, false});
    }
    rows.push_back({"Memory", fmt("GD %.2f GB      free %.2f GB", private_mb() / 1024.0, avail_mb() / 1024.0), kText, false});
    int owned = g_hotkeys_owned.load();
    std::string keys = "Ctrl+Alt+   V watch 1x    O overlay    B background";
    if (owned != 7) keys += owned ? "   (partly on another slot)" : "   (on another slot)";
    rows.push_back({"", keys, kDim, true});
    if (int(rows.size()) > kRows) rows.erase(rows.begin() + (kRows - 1), rows.end() - 1);  // keep the hint row
    int n = int(rows.size());
    for (int i = 0; i < kRows; ++i) {
        if (i < n) {
            set_label(g_key[i], rows[i].span ? "" : rows[i].key, kKey);
            set_label(g_val[i], rows[i].value, rows[i].color);
        } else {
            set_label(g_key[i], "", kKey);
            set_label(g_val[i], "", kText);
        }
    }
    bool relayout = n != g_used_rows;
    for (int i = 0; i < n; ++i) relayout |= g_row_span[i] != rows[i].span;
    if (relayout) {
        g_used_rows = n;
        const CCSize size = {kWidth, kPad * 2 + kLineH * n};
        g_cc.layer_set_size(g_panel, &size);
        for (int i = 0; i < kRows; ++i) {
            bool span = i < n && rows[i].span;
            g_row_span[i] = span;
            float y = size.h - kPad - kLineH * i;
            if (g_key[i].node) g_cc.set_pos(g_key[i].node, kPad, y);
            if (g_val[i].node) g_cc.set_pos(g_val[i].node, span ? kPad : kPad + kKeyW, y);
        }
    }
}

void place_overlay() {
    void* scene = g_cc.running_scene(g_cc.director());
    if (!scene) return;
    if (g_cc.get_parent(g_panel) != scene) {
        if (g_cc.get_parent(g_panel)) g_cc.remove(g_panel, false);
        g_cc.add_child(scene, g_panel, 100000);
    }
    const CCSize* win = g_cc.get_size(scene);
    float h = kPad * 2 + kLineH * (g_used_rows ? g_used_rows : kRows);
    if (win) g_cc.set_pos(g_panel, kMargin, win->h - kMargin - h);
}

}  // namespace

// ---- public ------------------------------------------------------------------------------------------
void view_session_init() {
    wchar_t s[16] = {0};
    GetEnvironmentVariableW(L"GDBOT_SESSION", s, DWORD(std::size(s)));
    if (std::wstring(s) == L"keep") {
        GLOG("session: keep (supervisor recycle): mode.txt and view.json unchanged");
        bool overlay = true;
        int watch = -1;
        if (read_view(&overlay, &watch)) { g_overlay_on = overlay; g_watch = watch == g_paths.slot; }
        return;
    }
    // fresh (default): a start the user asked for. User rule: fastest speed, not background, overlay shown.
    FILE* f = _wfopen((g_paths.bot_dir + L"\\mode.txt").c_str(), L"w");
    if (f) { fputs("dedicated", f); fclose(f); }
    write_view(true, -1);
    g_overlay_on = true;
    g_watch = false;
    GLOG("session: fresh: mode.txt=dedicated, view.json overlay on, no watch");
}

void view_set_client(const std::string& job, const std::vector<std::string>& lines) {
    g_job = ascii(job, 28);
    g_client_lines.clear();
    for (size_t i = 0; i < lines.size() && i < 3; ++i) g_client_lines.push_back(ascii(lines[i], 72));
}

void view_release() {
    g_job.clear();
    g_client_lines.clear();
}

void view_frame(const char* mode_label, float progress) {
    // hotkeys (this slot owns them): write the shared state; every slot (this one included) reads it below
    if (g_hk_overlay.exchange(false)) {
        bool overlay = true;
        int watch = -1;
        read_view(&overlay, &watch);
        write_view(!overlay, watch);
        GLOG("hotkey Ctrl+Alt+O: overlay %s", !overlay ? "on" : "off");
    }
    if (g_hk_watch.exchange(false)) {
        bool overlay = true;
        int watch = -1;
        read_view(&overlay, &watch);
        int next = watch >= 0 ? -1 : watch_target();
        write_view(overlay, next);
        GLOG("hotkey Ctrl+Alt+V: watch %s", next >= 0 ? ("slot " + std::to_string(next)).c_str() : "off");
    }
    // poll view.json (cheap: file time first)
    static ULONGLONG s_last_poll = 0;
    ULONGLONG now = GetTickCount64();
    if (now - s_last_poll >= 250) {
        s_last_poll = now;
        WIN32_FILE_ATTRIBUTE_DATA a{};
        if (GetFileAttributesExW(view_file().c_str(), GetFileExInfoStandard, &a) &&
            CompareFileTime(&a.ftLastWriteTime, &g_view_time) != 0) {
            g_view_time = a.ftLastWriteTime;
            bool overlay = true;
            int watch = -1;
            if (read_view(&overlay, &watch)) {
                bool w = watch == g_paths.slot;
                if (w != g_watch) GLOG("view: watch at 1x %s", w ? "ON" : "off");
                if (overlay != g_overlay_on) GLOG("view: overlay %s", overlay ? "shown" : "hidden");
                g_watch = w;
                g_overlay_on = overlay;
            }
        }
    }
    // overlay: at most 4 updates a second; drawn with the scene
    load_cocos();
    if (!g_cc.ok) return;
    if (!g_panel) build_overlay();
    if (!g_panel) return;
    static ULONGLONG s_last_draw = 0;
    static long long s_last_ticks = 0;
    static double s_tps = 0.0;
    static bool s_visible = true;
    if (s_visible != g_overlay_on) { g_cc.set_visible(g_panel, g_overlay_on); s_visible = g_overlay_on; }
    if (!g_overlay_on || now - s_last_draw < 250) return;
    double dt = s_last_draw ? double(now - s_last_draw) / 1000.0 : 0.0;
    if (dt > 0) s_tps = double(g_vstats.ticks_run - s_last_ticks) / dt;
    s_last_ticks = g_vstats.ticks_run;
    s_last_draw = now;
    update_overlay(mode_label, progress, s_tps);
    place_overlay();
}

}  // namespace gdbot
