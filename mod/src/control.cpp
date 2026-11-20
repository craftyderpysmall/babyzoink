// Protocol v0 server (docs/PROTOCOL.md): named pipe \\.\pipe\gdbot-<pid>, u32 LE length + UTF-8 JSON,
// strictly alternating request/reply. The pipe thread only moves bytes; every request is executed
// on the game thread inside control_frame() (called from CCScheduler::update).
#include <windows.h>
#include <sddl.h>
#include <atomic>
#include <climits>
#include <cmath>
#include <cstdio>
#include <algorithm>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>
#include "bridge.hpp"
#include "log.hpp"

using json = nlohmann::json;

namespace gdbot {
namespace {
using namespace offsets;

constexpr int kProto = 0;
constexpr float kTickDt = 1.0f / 240.0f;

// ---- pipe <-> game thread handoff ----
HANDLE g_req_ev = nullptr;   // pipe thread -> game thread: request ready
HANDLE g_rep_ev = nullptr;   // game thread -> pipe thread: reply ready
std::string g_req, g_rep;
std::atomic<bool> g_client_gone{false};
bool g_close_after_reply = false;
std::wstring g_pipe_name;
void send_reply(const json& r);
bool update_ready();

// ---- session state (game thread only) ----
enum class Mode { Normal, Dedicated, Background };
Mode g_mode = Mode::Normal;
const char* mode_str(Mode m);
int g_episode = 0;
bool g_trace = false;
// practice / checkpoints (M4); see op_set_practice
bool g_practice = false;
struct BotCheckpoint { int id; void* obj; long long tick; float x; };
std::vector<BotCheckpoint> g_cps;
int g_next_cp_id = 1;
float g_prev_x = 0.0f;
long long g_prev_tick = -1;
float g_tick_x = 0.0f;   // player x after the most recent tick
float g_tick_vx = 0.0f;  // x(t) - x(t-1) for the most recent tick (game units per tick)
// deferred load_level reply
bool g_load_pending = false;
bool g_load_seen_layer = false;
json g_load_reply;
int g_load_wait_frames = 0;
std::string g_next_title;  // main level name read at load_level, for the overlay

// ---- game functions ----
using GetMgr_t = void*(__fastcall*)();
using GetMainLevel_t = void*(__fastcall*)(void*, int, bool);
using PLScene_t = void*(__fastcall*)(void*, bool, bool);
using Percent_t = float(__fastcall*)(void*);
using SharedDirector_t = void*(__fastcall*)();
using ReplaceScene_t = bool(__fastcall*)(void*, void*);
using GetRotation_t = float(__fastcall*)(void*);
SharedDirector_t f_sharedDirector = nullptr;
ReplaceScene_t f_replaceScene = nullptr;
GetRotation_t f_getRotation = nullptr;

// SEH wrappers live in functions without C++ objects (MSVC C2712).
float call_float(void* fn, void* self) {
    float v = 0.0f;
    __try { v = reinterpret_cast<float(__fastcall*)(void*)>(fn)(self); } __except (EXCEPTION_EXECUTE_HANDLER) { v = 0.0f; }
    return v;
}

void send_reply(const json& r);

// Never throws (#36): a malformed id (string, float, missing, non-object request) replies with id 0.
long long req_id(const json& req) {
    if (!req.is_object()) return 0;
    auto it = req.find("id");
    return it != req.end() && it->is_number_integer() ? it->get<long long>() : 0;
}
json err(const json& req, const char* code, const std::string& msg) {
    return {{"id", req_id(req)}, {"ok", false}, {"error", {{"code", code}, {"msg", msg}}}};
}
json ok(const json& req) { return {{"id", req_id(req)}, {"ok", true}}; }

// debug_peek reads raw game memory; dev use only (#36). Enabled when the launcher's environment has GDBOT_DEBUG=1.
bool debug_enabled() {
    static int s = -1;
    if (s < 0) {
        wchar_t v[8] = {0};
        s = GetEnvironmentVariableW(L"GDBOT_DEBUG", v, 8) && v[0] == L'1';
    }
    return s == 1;
}

const char* mode_name(void* p) {
    using namespace fields;
    if (read_field<uint8_t>(p, kIsShip)) return "ship";
    if (read_field<uint8_t>(p, kIsBird)) return "ufo";
    if (read_field<uint8_t>(p, kIsBall)) return "ball";
    if (read_field<uint8_t>(p, kIsDart)) return "wave";
    if (read_field<uint8_t>(p, kIsRobot)) return "robot";
    if (read_field<uint8_t>(p, kIsSpider)) return "spider";
    if (read_field<uint8_t>(p, kIsSwing)) return "swing";
    return "cube";
}

json player_json(void* p) {
    using namespace fields;
    float x = read_field<float>(p, kPosTickX), y = read_field<float>(p, kPosTickY);
    float vx = g_tick_vx;  // x(t) - x(t-1), maintained per physics tick in op_step
    float rot = (f_getRotation && p) ? call_float((void*)f_getRotation, p) : 0.0f;
    return {
        {"x", x}, {"y", y},
        {"vx", vx},  // game units per tick, from consecutive observations
        {"vy", read_field<double>(p, kYVelocity)},  // m_yVelocity, game-internal units
        {"rot", rot},
        {"mode", mode_name(p)},
        {"speed", read_field<float>(p, kPlayerSpeed)},
        {"gravity_flipped", read_field<uint8_t>(p, kIsUpsideDown) != 0},
        {"mini", read_field<float>(p, kVehicleSize, 1.0f) < 0.99f},
        {"on_ground", read_field<uint8_t>(p, kIsOnGround) != 0},
        {"on_ceiling", false},
        {"holding", g_held},
        {"buffered", read_field<uint8_t>(p, kJumpBuffered) != 0},
        {"dashing", read_field<uint8_t>(p, kIsDashing) != 0},
        {"dead", read_field<uint8_t>(p, kIsDead) != 0},
        {"going_left", read_field<uint8_t>(p, kIsGoingLeft) != 0},
    };
}

float progress() {
    void* f = rva_ptr(PlayLayer__getCurrentPercent);
    if (!f || !g_layer) return 0.0f;
    float v = call_float(f, g_layer);
    return std::isfinite(v) ? std::fmin(std::fmax(v / 100.0f, 0.0f), 1.0f) : 0.0f;
}

// ---- objects (M1b) ----
// Cache of collision-relevant objects, sorted by their level x, rebuilt on reset/load. Each observation
// binary-searches the window and re-reads the live hitbox via GameObject::getObjectRect(), so objects
// moved by triggers inside the window report their current rect. Objects moved in from far outside
// the window are not found (documented limitation, "moving_objects_partial").
constexpr double kAheadX = 1200.0, kBehindX = 150.0;
constexpr size_t kMaxObjects = 128;
struct CachedObj { double x; void* obj; int type; int id; };
std::vector<CachedObj> g_objs;
bool g_objects_ok = false;
using CCArrayCount_t = unsigned(__fastcall*)(const void*);
using CCArrayAt_t = void*(__fastcall*)(void*, unsigned);
CCArrayCount_t f_arrCount = nullptr;
CCArrayAt_t f_arrAt = nullptr;
struct Rect { float x, y, w, h; };

bool call_rect(void* obj, Rect* out) {
    void* fn = rva_ptr(GameObject__getObjectRect);
    if (!fn) return false;
    __try {
        const Rect* r = reinterpret_cast<const Rect*(__fastcall*)(void*)>(fn)(obj);
        *out = *r;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

unsigned call_count(void* arr) {
    __try { return f_arrCount(arr); } __except (EXCEPTION_EXECUTE_HANDLER) { return 0; }
}
void* call_at(void* arr, unsigned i) {
    __try { return f_arrAt(arr, i); } __except (EXCEPTION_EXECUTE_HANDLER) { return nullptr; }
}

// GameObjectType -> protocol category ("" = not collision-relevant, skipped)
const char* category(int type, int id) {
    switch (id) {  // speed portals are identified by object id
        case 200: case 201: case 202: case 203: case 1334: return "portal_speed";
        default: break;
    }
    switch (type) {
        case 0: case 21: case 25: return "solid";
        case 2: case 47: return "hazard";
        case 8: case 9: case 10: case 34: case 44: return "pad";
        case 11: case 12: case 13: case 29: case 32: case 35: case 36: case 37: case 38: case 43: case 46: return "orb";
        case 5: case 6: case 16: case 19: case 26: case 27: case 33: case 41: return "portal_mode";
        case 3: case 4: case 42: return "portal_gravity";
        case 17: case 18: return "portal_size";
        case 23: case 24: return "portal_dual";
        case 28: return "portal_teleport";
        case 14: case 15: return "other";
        default: return "";
    }
}

json params(int type, int id) {
    switch (type) {
        case 8: return {{"kind", "yellow"}};  case 9: return {{"kind", "pink"}};
        case 10: return {{"kind", "gravity"}}; case 34: return {{"kind", "red"}}; case 44: return {{"kind", "spider"}};
        case 11: return {{"kind", "yellow"}}; case 12: return {{"kind", "pink"}}; case 13: return {{"kind", "blue"}};
        case 29: return {{"kind", "green"}};  case 32: return {{"kind", "black"}}; case 35: return {{"kind", "red"}};
        case 36: return {{"kind", "custom"}}; case 37: return {{"kind", "dash_green"}}; case 38: return {{"kind", "dash_pink"}};
        case 43: return {{"kind", "spider"}}; case 46: return {{"kind", "teleport"}};
        case 5: return {{"to", "ship"}}; case 6: return {{"to", "cube"}}; case 16: return {{"to", "ball"}};
        case 19: return {{"to", "ufo"}}; case 26: return {{"to", "wave"}}; case 27: return {{"to", "robot"}};
        case 33: return {{"to", "spider"}}; case 41: return {{"to", "swing"}};
        case 3: return {{"to", "flipped"}}; case 4: return {{"to", "normal"}}; case 42: return {{"to", "toggle"}};
        case 17: return {{"to", "normal"}}; case 18: return {{"to", "mini"}};
        case 23: return {{"to", "dual"}}; case 24: return {{"to", "solo"}};
        case 14: return {{"kind", "mirror_on"}}; case 15: return {{"kind", "mirror_off"}};
        case 21: return {{"breakable", true}}; case 25: return {{"slope", true}};
        default: break;
    }
    switch (id) {
        case 200: return {{"to", 0.5}}; case 201: return {{"to", 1}}; case 202: return {{"to", 2}};
        case 203: return {{"to", 3}}; case 1334: return {{"to", 4}};
        default: return json::object();
    }
}

void rebuild_object_cache() {
    g_objs.clear();
    g_objects_ok = false;
    if (g_anticheat_off >= 0) g_anticheat_obj = read_field<void*>(g_layer, size_t(g_anticheat_off));
    void* arr = read_field<void*>(g_layer, fields::kLayerObjects);
    if (!arr || !f_arrCount || !f_arrAt) return;
    unsigned n = call_count(arr);
    int bad_type = 0;
    for (unsigned i = 0; i < n; ++i) {
        void* o = call_at(arr, i);
        if (!o) continue;
        int type = read_field<int>(o, fields::kObjType, -1);
        if (type < 0 || type > 47) { ++bad_type; continue; }
        int id = read_field<int>(o, fields::kObjID, -1);
        if (!*category(type, id)) continue;
        Rect r;
        if (!call_rect(o, &r)) continue;
        g_objs.push_back({double(r.x) + r.w * 0.5, o, type, id});  // keyed by live hitbox centre
    }
    std::sort(g_objs.begin(), g_objs.end(), [](const CachedObj& a, const CachedObj& b) { return a.x < b.x; });
    // One-time layout probe: rect + first 0x600 bytes of up to 400 objects -> gdbot\objprobe.bin
    static bool s_probed = false;
    if (!s_probed) {
        s_probed = true;
        FILE* f = _wfopen((g_paths.inst_dir + L"\\objprobe.bin").c_str(), L"wb");
        if (f) {
            static unsigned char buf[16 + 0x600];
            unsigned m = n < 400 ? n : 400;
            for (unsigned i = 0; i < m; ++i) {
                void* o = call_at(arr, i);
                Rect r{};
                memset(buf, 0, sizeof(buf));
                if (o && call_rect(o, &r)) memcpy(buf, &r, 16);
                if (o) for (size_t off = 0; off < 0x600; off += 0x100) safe_copy(buf + 16 + off, (char*)o + off, 0x100);
                fwrite(buf, 1, sizeof(buf), f);
            }
            fclose(f);
            GLOG("objects: wrote objprobe.bin (%u objects)", m);
        }
    }
    // Sanity gate: the layout is unverified until this passes on a real level.
    g_objects_ok = n > 0 && bad_type * 20 <= int(n) && !g_objs.empty();
    static unsigned s_last_n = ~0u;
    static size_t s_last_rel = ~size_t(0);
    if (n != s_last_n || g_objs.size() != s_last_rel) {  // log only when the level's object set changes
        s_last_n = n; s_last_rel = g_objs.size();
        GLOG("objects: m_objects count=%u relevant=%zu bad_type=%d -> %s", n, g_objs.size(), bad_type,
             g_objects_ok ? "OK" : "DISABLED (layout check failed)");
    }
}

json objects_json(float px, bool* truncated) {
    json out = json::array();
    *truncated = false;
    if (!g_objects_ok) return out;
    auto lo = std::lower_bound(g_objs.begin(), g_objs.end(), px - kBehindX - 120.0,
                               [](const CachedObj& a, double x) { return a.x < x; });
    for (auto it = lo; it != g_objs.end() && it->x <= px + kAheadX + 120.0; ++it) {
        if (it->obj == g_anticheat_obj) continue;  // hidden anticheat spike, not level geometry
        Rect r;
        if (!call_rect(it->obj, &r)) continue;
        double cx = r.x + r.w * 0.5, cy = r.y + r.h * 0.5;
        if (cx < px - kBehindX || cx > px + kAheadX) continue;
        if (out.size() >= kMaxObjects) { *truncated = true; break; }
        float rot = f_getRotation ? call_float((void*)f_getRotation, it->obj) : 0.0f;
        out.push_back({{"uid", read_field<int>(it->obj, fields::kObjUniqueID)}, {"cat", category(it->type, it->id)},
                       {"type_id", it->id}, {"x", cx}, {"y", cy}, {"w", r.w}, {"h", r.h}, {"rot", rot},
                       {"active", true}, {"params", params(it->type, it->id)}});
    }
    return out;
}

unsigned long long fnv(unsigned long long h, const void* p, size_t n) {
    const unsigned char* b = static_cast<const unsigned char*>(p);
    for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ull; }
    return h;
}

// Effective item counts (id -> value), sorted by id; empty if unmapped. Bounded walk of the MSVC list.
std::vector<std::pair<int, int>> item_counts() {
    std::vector<std::pair<int, int>> out;
    void* em = g_layer ? read_field<void*>(g_layer, fields::kLayerEffectManager) : nullptr;
    if (!em) return out;
    size_t n = read_field<size_t>(em, fields::kEffItemMapSize);
    void* head = read_field<void*>(em, fields::kEffItemMapHead);
    if (!head || n > 100000) return out;
    void* node = read_field<void*>(head, 0);
    for (size_t i = 0; node && node != head && i < n; ++i) {
        out.push_back({read_field<int>(node, 0x10), read_field<int>(node, 0x14)});
        node = read_field<void*>(node, 0);
    }
    std::sort(out.begin(), out.end());
    return out;
}

// Gameplay world state: which cached gameplay objects (solids, hazards, pads, orbs, portals) are group-disabled,
// by stable unique id, plus item counts. Two branches with the same toggled groups and items hash equal.
unsigned long long world_hash() {
    unsigned long long h = 1469598103934665603ull;
    for (const CachedObj& c : g_objs) {
        if (!read_field<uint8_t>(c.obj, fields::kObjGroupDisabled)) continue;
        int uid = read_field<int>(c.obj, fields::kObjUniqueID);
        h = fnv(h, &uid, sizeof uid);
    }
    return h;
}
unsigned long long items_hash(size_t* count) {
    auto items = item_counts();
    if (count) *count = items.size();
    unsigned long long h = 1469598103934665603ull;
    for (const auto& kv : items) { h = fnv(h, &kv.first, 4); h = fnv(h, &kv.second, 4); }
    return h;
}
std::string hex64(unsigned long long v) { char b[20]; snprintf(b, sizeof b, "%016llx", v); return b; }

json state_json() {
    size_t n_items = 0;
    unsigned long long ih = items_hash(&n_items);
    json s = {{"dual", dual_mode()}, {"world_hash", hex64(world_hash())}, {"items_hash", hex64(ih)}, {"items", n_items}};
    return s;
}

// One archive cell observation (M9): both players' coarse physical state, held input, world/items hashes.
json cell_json(long long tick) {
    auto pl = [](void* p) -> json {
        if (!p) return nullptr;
        using namespace fields;
        return json::array({read_field<float>(p, kPosTickX), read_field<float>(p, kPosTickY),
                            read_field<double>(p, kYVelocity), read_field<uint8_t>(p, kIsOnGround),
                            mode_name(p), read_field<uint8_t>(p, kIsUpsideDown), read_field<uint8_t>(p, kIsGoingLeft)});
    };
    bool dual = dual_mode();
    return {{"t", tick}, {"held", g_held}, {"p1", pl(player1())}, {"p2", dual ? pl(player2()) : json()},
            {"world", hex64(world_hash())}, {"items", hex64(items_hash(nullptr))}};
}

json obs_json() {
    void* p = player1();
    bool truncated = false;
    json objs = objects_json(read_field<float>(p, fields::kPosTickX), &truncated);
    json unsupported = json::array({"on_ceiling", "button_queue", "object_active", "moving_objects_partial"});
    if (!g_objects_ok) unsupported.push_back("objects");
    json players = json::array({player_json(p)});
    if (dual_mode()) players.push_back(player_json(player2()));
    json o = {
        {"players", players},
        {"dual", dual_mode()},
        {"objects", objs},
        {"progress", progress()},
        {"window", {{"ahead_x", kAheadX}, {"behind_x", kBehindX}, {"max_objects", kMaxObjects}, {"truncated", truncated}}},
        {"unsupported", unsupported},
    };
    g_prev_x = read_field<float>(p, fields::kPosTickX);
    g_prev_tick = g_tick;
    return o;
}

void press(bool down) {
    if (g_layer && g_held != down) {
        o_handleButton(g_layer, down, 1, true);  // original: our hook (which tracks g_held) is bypassed
        g_held = down;
    }
}

BOOL CALLBACK find_game_window(HWND h, LPARAM out);

// Window owner marking: the client's hello may name its agent ("claude" | "codex"). The window's caption
// and border take that agent's colour (Claude orange / ChatGPT green) and the title names agent + slot,
// so the user can tell the slots apart. Colours stay until another agent says hello. Windows 11 DWM only;
// older systems just get the title.
void mark_window_owner(const std::string& agent) {
    HWND w = nullptr;
    EnumWindows(find_game_window, LPARAM(&w));
    if (!w) { GLOG("window owner %s: no game window yet", agent.c_str()); return; }
    COLORREF caption, text = RGB(255, 255, 255);
    if (agent == "claude") caption = RGB(0xD9, 0x77, 0x57);       // Claude orange #D97757
    else if (agent == "codex") caption = RGB(0x10, 0xA3, 0x7F);   // ChatGPT green #10A37F
    else return;
    using DwmSet_t = HRESULT(WINAPI*)(HWND, DWORD, LPCVOID, DWORD);
    static HMODULE dwm = LoadLibraryW(L"dwmapi.dll");
    auto set = dwm ? (DwmSet_t)GetProcAddress(dwm, "DwmSetWindowAttribute") : nullptr;
    HRESULT hb = E_FAIL, hc = E_FAIL;
    if (set) {
        hb = set(w, 34 /*DWMWA_BORDER_COLOR*/, &caption, sizeof caption);
        hc = set(w, 35 /*DWMWA_CAPTION_COLOR*/, &caption, sizeof caption);
        set(w, 36 /*DWMWA_TEXT_COLOR*/, &text, sizeof text);
    }
    std::wstring title = L"Geometry Dash - " + std::wstring(agent.begin(), agent.end()) + L" - slot " +
                         std::to_wstring(g_paths.slot);
    SetWindowTextW(w, title.c_str());
    GLOG("window owner -> %s (caption 0x%lx, border 0x%lx)", agent.c_str(), (unsigned long)hc, (unsigned long)hb);
}

// ---- operations ----
json op_hello(const json& req) {
    if (req.value("proto", -1) != kProto) return err(req, "BAD_REQUEST", "unsupported protocol version");
    g_controlled = true;
    GLOG("client hello (%s); bot now controls the game", req.value("client", std::string("?")).c_str());
    std::string agent = req.value("agent", std::string());
    static std::string s_owner;
    if (!agent.empty() && agent != s_owner) { s_owner = agent; mark_window_owner(agent); }
    json r = ok(req);
    r["proto"] = kProto;
    r["build"] = {{"exe_sha256", g_build->exe_sha256}, {"game_version", g_build->game_version}};
    r["capabilities"] = {{"step", true}, {"reset", true}, {"startpos", false}, {"checkpoint", true},
                         {"trace", true}, {"modes", {"normal", "dedicated", "background"}}, {"dual", false},
                         {"objects", true}, {"level_string", true}, {"quit_level", true}, {"debug_peek", debug_enabled()}, {"isolation", true},
                         {"set_render", g_draw_skip_supported}, {"agent_colors", true},
                         {"watch_1x", true}, {"overlay", true}, {"session", true}, {"cbf", g_cbf_ok}};
    r["ready"] = update_ready();  // false: load_level is held until the menu is up (no client sleep needed)
    r["mode"] = mode_str(g_mode);
    r["isolation"] = {{"saves_redirected", g_iso.saves_redirected && g_iso.file_guard},
                      {"http_blocked", g_iso.http_blocked}};
    return r;
}

// MSVC std::string (release): 16-byte buffer/pointer union, then size, then capacity.
bool read_msvc_string(void* base, size_t off, std::string* out, size_t max_len) {
    char raw[32];
    if (!safe_copy(raw, static_cast<char*>(base) + off, 32)) return false;
    size_t size, cap;
    memcpy(&size, raw + 16, 8);
    memcpy(&cap, raw + 24, 8);
    if (cap < 15 || size > cap || cap > (1ull << 28)) return false;
    const char* data = raw;
    if (cap > 15) memcpy(&data, raw, 8);
    size_t n = size < max_len ? size : max_len;
    out->assign(n, '\0');
    return n == 0 || safe_copy(out->data(), data, n);
}

// GJGameLevel: m_levelName, m_levelDesc, m_levelString are consecutive std::strings (bindings order).
// Found on a real main level: the string that starts with "H4sI" and is >100 bytes, with the level's
// name two strings (0x40 bytes) earlier. Verified once per process, then reused.
long long g_level_string_off = -1;
long long find_level_string_offset(void* level, const char* expect_name) {
    for (size_t off = 0x100; off < 0x800; off += 8) {
        std::string head, name;
        if (!read_msvc_string(level, off, &head, 8) || head.rfind("H4sI", 0) != 0) continue;
        std::string full;
        char raw[32];
        if (!safe_copy(raw, static_cast<char*>(level) + off, 32)) continue;
        size_t size;
        memcpy(&size, raw + 16, 8);
        if (size < 100) continue;
        if (!read_msvc_string(level, off - 0x40, &name, 64) || name != expect_name) {
            GLOG("level string candidate at +0x%zx rejected: name check got '%s'", off, name.c_str());
            continue;
        }
        GLOG("GJGameLevel::m_levelString at +0x%zx (size %zu), m_levelName at +0x%zx = '%s'", off, size, off - 0x40, name.c_str());
        return (long long)off;
    }
    return -1;
}

void begin_load(const json& req, void* level, json info) {
    void* s = reinterpret_cast<PLScene_t>(rva_ptr(PlayLayer__scene))(level, false, false);
    if (!s) { send_reply(err(req, "INTERNAL", "PlayLayer::scene returned null")); return; }
    f_replaceScene(f_sharedDirector(), s);
    GLOG("load_level %s: scene %p, waiting for the level to settle", info.dump().c_str(), s);
    g_load_pending = true;
    g_load_wait_frames = 0;
    g_load_reply = ok(req);
    std::string title = info.value("kind", "") == "main"
                            ? (g_next_title.empty() ? "Main level " + std::to_string(info.value("id", 0)) : g_next_title)
                            : info.value("name", std::string("level"));
    if (title.rfind("online-", 0) == 0) title = "Online level " + title.substr(7);
    if (const json* nm = req.contains("level") ? &req["level"] : nullptr; nm && nm->contains("title") && (*nm)["title"].is_string())
        title = (*nm)["title"].get<std::string>();  // optional human title from the client
    g_vstats = ViewStats{title, 0, 0, 0.0f, g_vstats.ticks_run};
    g_load_reply["level"] = std::move(info);
}

// Game readiness (Codex review of #46): a load_level right after a fresh start crashed in PlayLayer::init while
// GD was still on its loading screen. Ready = the running scene has changed from the first one seen (loading ->
// menu) and stayed for 30 frames, or 10 s since the bridge started (fallback). Until then load_level is deferred.
using GetScene_t = void*(__fastcall*)(void*);
bool g_ready = false;
json g_early_load;  // a load_level that arrived before the game was ready
bool update_ready() {
    if (g_ready) return true;
    static void* s_first = nullptr;
    static void* s_last = nullptr;
    static int s_same = 0;
    static ULONGLONG s_t0 = GetTickCount64();
    static GetScene_t s_get = nullptr;
    if (!s_get) {
        HMODULE cc = GetModuleHandleW(L"libcocos2d.dll");
        s_get = cc ? (GetScene_t)GetProcAddress(cc, "?getRunningScene@CCDirector@cocos2d@@QEAAPEAVCCScene@2@XZ") : nullptr;
    }
    void* scene = (s_get && f_sharedDirector) ? s_get(f_sharedDirector()) : nullptr;
    if (scene && !s_first) s_first = scene;
    if (scene == s_last) ++s_same; else { s_last = scene; s_same = 0; }
    if ((scene && scene != s_first && s_same >= 30) || GetTickCount64() - s_t0 > 10000) {
        g_ready = true;
        GLOG("game ready for load_level (%s)", scene != s_first ? "menu scene up" : "10 s fallback");
    }
    return g_ready;
}

json op_load_level(const json& req) {
    if (!update_ready()) {
        GLOG("load_level before the game is ready: deferred until the menu is up");
        g_early_load = req;
        return json();
    }
    const json& lv = req.value("level", json::object());
    std::string kind = lv.value("kind", "");
    if (g_layer) return err(req, "BAD_REQUEST", "already in a level; send quit_level first");
    auto sharedState = reinterpret_cast<GetMgr_t>(rva_ptr(GameLevelManager__sharedState));
    auto getMainLevel = reinterpret_cast<GetMainLevel_t>(rva_ptr(GameLevelManager__getMainLevel));
    if (!sharedState || !getMainLevel || !rva_ptr(PlayLayer__scene) || !f_sharedDirector || !f_replaceScene)
        return err(req, "UNSUPPORTED", "level loading functions not mapped");
    void* glm = sharedState();
    if (kind == "main") {
        int id = lv.value("id", 0);
        if (id < 1 || id > 30) return err(req, "BAD_REQUEST", "main level id out of range");
        void* level = glm ? getMainLevel(glm, id, false) : nullptr;
        if (!level) return err(req, "INTERNAL", "getMainLevel returned null");
        // the level's own name for the overlay (GJGameLevel::m_levelName sits 0x40 before m_levelString)
        if (g_level_string_off < 0) {
            void* main1 = getMainLevel(glm, 1, false);
            if (main1) g_level_string_off = find_level_string_offset(main1, "Stereo Madness");
        }
        g_next_title.clear();
        if (g_level_string_off >= 0x40) read_msvc_string(level, size_t(g_level_string_off - 0x40), &g_next_title, 64);
        begin_load(req, level, {{"kind", "main"}, {"id", id}, {"name", nullptr}, {"length_x", nullptr}, {"revision", "main"}});
        return json();  // deferred
    }
    if (kind == "level_string") {
        std::string data = lv.value("data", ""), name = lv.value("name", "drill");
        if (data.rfind("H4sI", 0) != 0) return err(req, "BAD_REQUEST", "data must be GD-encoded (base64 gzip, starts with H4sI)");
        if (g_level_string_off < 0) {
            void* main1 = glm ? getMainLevel(glm, 1, false) : nullptr;
            if (main1) g_level_string_off = find_level_string_offset(main1, "Stereo Madness");
        }
        if (g_level_string_off < 0) return err(req, "UNSUPPORTED", "could not verify GJGameLevel::m_levelString offset");
        // One local editor level (in the bot's redirected save) is created once and reused for every drill.
        static void* s_drill_level = nullptr;
        if (!s_drill_level) {
            auto createNewLevel = reinterpret_cast<void*(__fastcall*)(void*)>(rva_ptr(GameLevelManager__createNewLevel));
            s_drill_level = createNewLevel ? createNewLevel(glm) : nullptr;
            GLOG("level_string: created local editor level %p for drills", s_drill_level);
        }
        void* level = s_drill_level;
        if (!level) return err(req, "INTERNAL", "createNewLevel returned null");
        *reinterpret_cast<std::string*>(static_cast<char*>(level) + g_level_string_off) = data;
        *reinterpret_cast<std::string*>(static_cast<char*>(level) + g_level_string_off - 0x40) = name;
        // revision: FNV-1a 64 of data (stable id; the client keeps its own sha256)
        unsigned long long h = 1469598103934665603ull;
        for (unsigned char ch : data) { h ^= ch; h *= 1099511628211ull; }
        char rev[24];
        snprintf(rev, sizeof(rev), "fnv1a64:%016llx", h);
        begin_load(req, level, {{"kind", "level_string"}, {"name", name}, {"length_x", nullptr}, {"revision", rev}});
        return json();
    }
    return err(req, "UNSUPPORTED", "level kind must be main or level_string");
}

// quit_level: PlayLayer::onQuit (through our hook) cleans up and returns to the menu; reply deferred.
bool g_quit_pending = false;
json g_quit_reply;
int g_quit_wait_frames = 0;
json op_quit_level(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    press(false);
    g_practice = false;  // the layer (and its checkpoints) goes away with the level
    g_cps.clear();
    reinterpret_cast<Void0_t>(rva_ptr(PlayLayer__onQuit))(g_layer);
    g_objs.clear();
    g_objects_ok = false;
    g_quit_pending = true;
    g_quit_wait_frames = 0;
    g_quit_reply = ok(req);
    return json();
}

// ---- practice / checkpoints (M4) ----
// Practice mode on: GD's resetLevel restores the newest stored checkpoint. While the bot controls the game
// only bot checkpoints are stored (hooks.cpp blocks practice auto-checkpoints), so "newest" = newest bot one.

void set_practice(bool on) {
    if (!g_layer || g_practice == on) return;
    reinterpret_cast<void(__fastcall*)(void*, bool)>(rva_ptr(PlayLayer__togglePracticeMode))(g_layer, on);
    g_practice = on;
    if (!on) g_cps.clear();
    GLOG("practice mode -> %d", on);
}

json op_set_practice(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (!rva_ptr(PlayLayer__togglePracticeMode)) return err(req, "UNSUPPORTED", "togglePracticeMode not mapped");
    set_practice(req.value("enabled", false));
    json r = ok(req);
    r["practice"] = g_practice;
    return r;
}

json op_checkpoint_create(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (!g_practice) return err(req, "BAD_REQUEST", "enable practice mode first (set_practice)");
    void* p = player1();
    if (read_field<uint8_t>(p, fields::kIsDead)) return err(req, "BAD_REQUEST", "player is dead");
    g_bot_checkpoint = true;
    void* cp = reinterpret_cast<void*(__fastcall*)(void*)>(rva_ptr(PlayLayer__markCheckpoint))(g_layer);
    g_bot_checkpoint = false;
    if (!cp) return err(req, "INTERNAL", "markCheckpoint returned null");
    BotCheckpoint c{g_next_cp_id++, cp, g_tick, read_field<float>(p, fields::kPosTickX)};
    g_cps.push_back(c);
    GLOG("checkpoint %d at tick %lld x=%.2f (%p)", c.id, c.tick, c.x, cp);
    json r = ok(req);
    r["checkpoint_id"] = c.id;
    r["tick"] = c.tick;
    r["x"] = c.x;
    r["count"] = g_cps.size();
    return r;
}

json op_checkpoint_pop(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (g_cps.empty()) return err(req, "BAD_REQUEST", "no bot checkpoints");
    reinterpret_cast<void(__fastcall*)(void*, bool)>(rva_ptr(PlayLayer__removeCheckpoint))(g_layer, false);
    int id = g_cps.back().id;
    g_cps.pop_back();
    json r = ok(req);
    r["removed"] = id;
    r["count"] = g_cps.size();
    return r;
}

json op_reset(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    const json& st = req.value("start", json::object());
    std::string kind = st.value("kind", "zero");
    json start_info = {{"kind", kind}};
    if (kind == "checkpoint") {
        if (!g_practice || g_cps.empty()) return err(req, "BAD_REQUEST", "no bot checkpoint to restore (practice off or none created)");
        int want = st.value("checkpoint_id", g_cps.back().id);
        if (want != g_cps.back().id)
            return err(req, "UNSUPPORTED", "only the newest checkpoint can be restored; checkpoint_pop newer ones first");
        start_info["checkpoint_id"] = want;
    } else if (kind == "zero") {
        set_practice(false);  // a full run always starts clean from 0% (plan: clean-start gate)
    } else {
        return err(req, "UNSUPPORTED", "start.kind must be zero or checkpoint (startpos: use a level_string with a start position)");
    }
    press(false);
    g_bot_reset = true;
    reinterpret_cast<Void0_t>(rva_ptr(PlayLayer__resetLevel))(g_layer);  // goes through our hook
    g_bot_reset = false;
    ++g_episode;
    g_death = DeathInfo{};
    cbf_clear();
    cbf_force_vanilla_click_off();
    if (kind == "zero") ++g_vstats.runs; else ++g_vstats.practice;
    g_prev_tick = -1;
    g_tick_x = read_field<float>(player1(), fields::kPosTickX);
    g_tick_vx = 0.0f;
    rebuild_object_cache();
    json r = ok(req);
    r["episode"] = g_episode;
    r["tick"] = g_tick;
    r["start"] = start_info;
    bool cbs = false, cos = false;
    cbf_click_flags(&cbs, &cos);
    r["input_timing"] = {{"cbf", g_cbf_ok}, {"click_between_steps", cbs}, {"click_on_steps", cos}};
    r["state"] = state_json();
    r["obs"] = obs_json();
    return r;
}

// ---- step execution (step and step_seq share one resumable cursor; M8) ----
// Fast path: the whole request runs inside one frame, exactly as before. Watch at 1x (g_watch): the cursor
// keeps its place (decision index, ticks done in the decision, held state, trace/xs/events, terminal) and
// advances at 240 ticks per wall-clock second across frames; the reply is deferred until it finishes.
struct Exec {
    bool active = false;      // a deferred (paced) request is pending
    bool seq = false;         // step_seq (else step)
    json req;
    std::vector<int> actions; // one per decision (step: exactly one)
    std::vector<double> fracs; // M8 CBF: press/release at this fraction of the decision's first step (empty = all 0)
    bool cbf_armed = false;
    int k = 1;                // ticks per decision
    bool want_xs = false;
    bool want_cells = false;  // M9: a cell observation after every completed decision
    json cells = json::array();
    size_t idx = 0;           // current decision
    long long in_dec = 0;     // ticks done in the current decision
    bool pressed = false;     // the current decision's press/release has been applied
    int calls = 0;            // update calls in the current decision (stuck-physics guard)
    long long t0 = 0;
    int decisions = 0;
    const char* terminal = nullptr;
    std::string error;
    json events = json::array(), trace = json::array(), xs = json::array();
};
Exec g_exec;
double g_pace_last_ms = 0.0, g_pace_carry = 0.0;

// Runs until the request is finished (returns true) or max_ticks physics ticks have run (returns false).
bool exec_advance(Exec& e, long long max_ticks) {
    const long long start = g_tick;
    while (e.idx < e.actions.size() && !e.terminal && e.error.empty()) {
        // Paced (watch) runs: never apply the next decision's input on a frame with no tick budget left;
        // it is applied at the start of the frame that runs that decision's first tick, as on the fast path.
        if (g_tick - start >= max_ticks) return false;
        if (!e.pressed) {
            bool down = e.actions[e.idx] == 1;
            double f = e.fracs.empty() ? 0.0 : e.fracs[e.idx];
            // CBF: a press/release that changes the held state lands at fraction f of the first step;
            // f = 0 (or no change) presses at the step start exactly as before.
            if (f > 0.0 && down != g_held && cbf_arm(down, f)) e.cbf_armed = true;
            else press(down);
            e.pressed = true;
            e.calls = 0;
        }
        while (e.in_dec < e.k && !e.terminal) {
            if (g_tick - start >= max_ticks) return false;
            long long before = g_tick;
            g_in_step = true;
            o_bglUpdate(g_layer, kTickDt);
            g_in_step = false;
            if (++e.calls > 4 * e.k + 16) {
                GLOG("step: update calls are not producing ticks (calls=%d advanced=%lld)", e.calls, g_tick - e.t0);
                e.error = "update calls are not producing physics ticks";
                return true;
            }
            if (g_tick == before) continue;
            if (g_tick - before > 1) GLOG("step: one update call advanced %lld ticks", g_tick - before);
            if (e.cbf_armed) { cbf_settle(); e.cbf_armed = false; }
            e.in_dec += g_tick - before;
            g_vstats.ticks_run += g_tick - before;
            void* p = player1();
            float x = read_field<float>(p, fields::kPosTickX);
            g_tick_vx = (x - g_tick_x) / float(g_tick - before);
            g_tick_x = x;
            void* p2 = dual_mode() ? player2() : nullptr;
            if (read_field<uint8_t>(p, fields::kIsDead) || (p2 && read_field<uint8_t>(p2, fields::kIsDead)) || g_death.set) {
                e.terminal = "death";
                if (!e.seq) e.events.push_back({{"type", "death"}, {"tick", g_tick}});
            } else if (g_end_reached) {  // tick-driven; GD's levelComplete itself arrives later on a wall-clock timer
                e.terminal = "complete";
                if (!e.seq) e.events.push_back({{"type", "complete"}, {"tick", g_tick}});
            }
            if (!e.seq && g_trace) {
                json row_events = json::array();
                if (e.terminal) row_events.push_back({{"type", e.terminal}, {"tick", g_tick}});
                e.trace.push_back({{"tick", g_tick}, {"players", json::array({player_json(p)})},
                                   {"button", {{"held", g_held}, {"queued", nullptr}}}, {"events", row_events}});
            }
        }
        if (e.terminal) break;
        ++e.decisions;
        if (e.want_xs) e.xs.push_back(read_field<float>(player1(), fields::kPosTickX));
        if (e.want_cells) e.cells.push_back(cell_json(g_tick));
        ++e.idx;
        e.in_dec = 0;
        e.pressed = false;
    }
    return true;
}

json exec_reply(Exec& e) {
    if (!e.error.empty()) return err(e.req, "INTERNAL", e.error);
    json r = ok(e.req);
    r["episode"] = g_episode;
    r["tick"] = g_tick;
    r["ticks_advanced"] = g_tick - e.t0;
    r["terminal"] = e.terminal ? json(e.terminal) : json();
    if (e.seq) {
        r["decisions"] = e.decisions;
        r["player"] = player_json(player1());
        if (e.want_xs) r["xs"] = e.xs;
        if (e.want_cells) r["cells"] = e.cells;
    } else {
        r["obs"] = obs_json();
        r["events"] = e.events;
        if (g_trace) r["trace"] = e.trace;
    }
    r["mode"] = mode_str(g_mode);  // so the trainer can match its own CPU use (threads, priority)
    r["dual"] = dual_mode();
    r["state"] = state_json();
    if (e.seq && r["dual"].get<bool>()) r["player2"] = player_json(player2());
    if (e.terminal && std::string(e.terminal) == "death" && g_death.set)
        r["death"] = {{"player", g_death.player}, {"object_null", g_death.object_null}, {"object_id", g_death.obj_id},
                      {"object_type", g_death.obj_type}, {"uid", g_death.uid}, {"object_group_disabled", g_death.obj_disabled},
                      {"x", g_death.x}, {"y", g_death.y}, {"tick", g_death.tick}, {"caller_rva", g_death.caller_rva}};
    float pr = e.terminal && std::string(e.terminal) == "complete" ? 1.0f : progress();
    if (pr > g_vstats.best) g_vstats.best = pr;
    return r;
}

// Starts a request: runs it now (fast path) or defers it (watch at 1x). Returns the reply, or null if deferred.
json exec_start(Exec&& e) {
    e.t0 = g_tick;
    cbf_force_vanilla_click_off();
    g_exec = std::move(e);
    if (g_watch) {
        g_exec.active = true;
        g_pace_last_ms = log::now_ms();
        g_pace_carry = 0.0;
        return json();
    }
    exec_advance(g_exec, LLONG_MAX);
    return exec_reply(g_exec);
}

// Called every frame while a paced request is pending. Watch turned off mid-request: finish at full speed.
void exec_pace_frame() {
    long long allowed = LLONG_MAX;
    if (g_watch) {
        double now = log::now_ms();
        g_pace_carry += (now - g_pace_last_ms) * 0.240;  // 240 ticks per second
        g_pace_last_ms = now;
        if (g_pace_carry > 16.0) g_pace_carry = 16.0;   // catch-up after a stalled frame: at most 4 frames' worth
        allowed = (long long)g_pace_carry;
        g_pace_carry -= double(allowed);
    }
    if (exec_advance(g_exec, allowed)) {
        g_exec.active = false;
        send_reply(exec_reply(g_exec));
    }
}

// Optional CBF fractions: finite, in [0, 1). Returns an error message, or empty on success.
std::string parse_fracs(const json& req, const char* key, size_t n, std::vector<double>* out, bool scalar) {
    if (!req.contains(key)) return "";
    const json& v = req[key];
    std::vector<double> f;
    if (scalar && !v.is_number()) return std::string(key) + " must be a number";
    if (!scalar && !v.is_array()) return std::string(key) + " must be an array with one number per action";
    if (v.is_number()) {
        f.push_back(v.get<double>());
    } else if (v.is_array()) {
        for (const json& x : v) {
            if (!x.is_number()) return std::string(key) + " must be numbers";
            f.push_back(x.get<double>());
        }
    } else {
        return std::string(key) + " must be a number or an array";
    }
    if (f.size() != n) return std::string(key) + " must have exactly one value per action";
    bool any = false;
    for (double x : f) {
        if (!std::isfinite(x) || x < 0.0 || x >= 1.0) return std::string(key) + " values must be finite and in [0, 1)";
        any |= x > 0.0;
    }
    if (any && !g_cbf_ok) return "CBF is unavailable in this bridge (see bridge.log)";
    *out = std::move(f);
    return "";
}

json op_step(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (req.value("episode", -1) != g_episode) return err(req, "EPISODE_MISMATCH", "stale episode");
    int action = req.value("action", -1), k = req.value("k", 0);
    if ((action != 0 && action != 1) || k < 1 || k > 240 * 60) return err(req, "BAD_REQUEST", "bad action or k");
    Exec e;
    e.req = req;
    e.actions = {action};
    e.k = k;
    if (std::string m = parse_fracs(req, "frac", 1, &e.fracs, true); !m.empty()) return err(req, "BAD_REQUEST", m);
    return exec_start(std::move(e));
}

// Search helper (M5c): apply a whole action sequence in one request, k ticks per action, stopping
// at the first terminal. Returns only the outcome and the final player state (no objects), so a
// solver can evaluate a candidate continuation from a checkpoint with a single round trip.
// {op, episode, actions:[0|1,...], k} -> {tick, ticks_advanced, decisions, terminal, player, xs?}
// "xs": true adds the player x after every completed decision.
json op_step_seq(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (req.value("episode", -1) != g_episode) return err(req, "EPISODE_MISMATCH", "stale episode");
    const json& actions = req.value("actions", json::array());
    int k = req.value("k", 4);
    if (!actions.is_array() || actions.empty() || actions.size() > 20000 || k < 1 || k > 240)
        return err(req, "BAD_REQUEST", "actions must be a non-empty array (<= 20000) and 1 <= k <= 240");
    Exec e;
    e.seq = true;
    e.req = req;
    e.k = k;
    e.want_xs = req.value("xs", false);
    e.want_cells = req.value("cells", false);
    e.actions.reserve(actions.size());
    for (const json& a : actions) {  // validate the whole request before any physics moves
        if (!a.is_number_integer() || (a.get<int>() != 0 && a.get<int>() != 1)) return err(req, "BAD_REQUEST", "actions must be 0/1");
        e.actions.push_back(a.get<int>());
    }
    if (std::string m = parse_fracs(req, "fracs", e.actions.size(), &e.fracs, false); !m.empty()) return err(req, "BAD_REQUEST", m);
    return exec_start(std::move(e));
}

json op_set_overlay(const json& req) {
    std::vector<std::string> lines;
    const json& l = req.value("lines", json::array());
    if (!l.is_array() || l.size() > 3) return err(req, "BAD_REQUEST", "lines must be an array of at most 3 strings");
    for (const json& s : l) {
        if (!s.is_string()) return err(req, "BAD_REQUEST", "lines must be strings");
        lines.push_back(s.get<std::string>());
    }
    view_set_client(req.value("job", std::string()), lines);
    json r = ok(req);
    r["overlay"] = g_overlay_on;
    r["watch"] = g_watch;
    return r;
}

// Dev-only: raw memory read for field mapping. target: "player1" | "player2" | "layer"; len <= 4096.
json op_debug_peek(const json& req) {
    if (!debug_enabled()) return err(req, "UNSUPPORTED", "debug_peek is off; launch with GDBOT_DEBUG=1 for field mapping");
    std::string target = req.value("target", "player1");
    long long off = req.value("off", -1), len = req.value("len", 0);
    if (off < 0 || len <= 0 || len > 4096 || off > 0x10000) return err(req, "BAD_REQUEST", "off/len out of range");
    void* p2 = player2();
    void* base = target == "layer" ? g_layer : target == "player1" ? player1() : target == "player2" ? p2 : nullptr;
    if (!base) return err(req, "NOT_IN_LEVEL", "target not available");
    std::string bytes(size_t(len), ' ');
    if (!safe_copy(bytes.data(), static_cast<char*>(base) + off, size_t(len))) return err(req, "INTERNAL", "read faulted");
    static const char* hx = "0123456789abcdef";
    std::string out;
    out.reserve(size_t(len) * 2);
    for (unsigned char ch : bytes) { out += hx[ch >> 4]; out += hx[ch & 15]; }
    json r = ok(req);
    r["tick"] = g_tick;
    r["hex"] = out;
    return r;
}

// ---- run modes ----
// dedicated : all hardware threads, normal priority, requests served back to back (12 ms per frame)
// background: below-normal priority, GD limited to 4 hardware threads, 6 ms bursts per frame, so the
//             user's own apps always win the CPU
// normal    : real time, one request per frame (parity baselines / watching)
// The user can override the client at any time: hotkey Ctrl+Alt+B (toggles dedicated/background) or
// tools/mode.ps1, which writes gdbot/mode.txt ("dedicated" | "background" | "auto"). A user choice
// persists in that file across trainer restarts; "auto" hands control back to the client's set_mode.
// Modes change pacing and CPU share only, never simulation results.
bool g_user_override = false;
Mode g_client_mode = Mode::Normal;
std::atomic<bool> g_hotkey_hit{false};
FILETIME g_mode_file_time{};

const char* mode_str(Mode m) { return m == Mode::Dedicated ? "dedicated" : m == Mode::Background ? "background" : "normal"; }

void apply_mode(Mode m, const char* why) {
    g_mode = m;
    g_mode_allows_skip = m != Mode::Normal;
    HANDLE proc = GetCurrentProcess();
    DWORD_PTR pmask = 0, smask = 0;
    GetProcessAffinityMask(proc, &pmask, &smask);
    DWORD_PTR mask = smask;
    if (m == Mode::Background) {
        DWORD_PTR four = 0;
        int n = 0;
        for (int b = int(sizeof(DWORD_PTR) * 8) - 1; b >= 0 && n < 4; --b)  // the 4 highest-numbered threads
            if (smask & (DWORD_PTR(1) << b)) { four |= DWORD_PTR(1) << b; ++n; }
        if (four) mask = four;
    }
    SetProcessAffinityMask(proc, mask);
    SetPriorityClass(proc, m == Mode::Background ? BELOW_NORMAL_PRIORITY_CLASS : NORMAL_PRIORITY_CLASS);
    GLOG("mode -> %s (%s); affinity 0x%llx", mode_str(m), why, (unsigned long long)mask);
}

std::wstring mode_file() { return g_paths.bot_dir + L"/mode.txt"; }

void write_mode_file(const char* text) {
    FILE* f = _wfopen(mode_file().c_str(), L"w");
    if (f) { fputs(text, f); fclose(f); }
    WIN32_FILE_ATTRIBUTE_DATA a{};
    if (GetFileAttributesExW(mode_file().c_str(), GetFileExInfoStandard, &a)) g_mode_file_time = a.ftLastWriteTime;
}

// Called about once a second from control_frame: hotkey toggles, then mode.txt changes.
void poll_user_mode() {
    if (g_hotkey_hit.exchange(false)) {
        Mode next = g_mode == Mode::Dedicated ? Mode::Background : Mode::Dedicated;
        g_user_override = true;
        write_mode_file(mode_str(next));
        apply_mode(next, "hotkey Ctrl+Alt+B");
        return;
    }
    WIN32_FILE_ATTRIBUTE_DATA a{};
    if (!GetFileAttributesExW(mode_file().c_str(), GetFileExInfoStandard, &a)) return;
    if (CompareFileTime(&a.ftLastWriteTime, &g_mode_file_time) == 0) return;
    g_mode_file_time = a.ftLastWriteTime;
    char buf[32] = {0};
    FILE* f = _wfopen(mode_file().c_str(), L"r");
    if (!f) return;
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    std::string t(buf, n);
    while (!t.empty() && (unsigned char)t.back() <= 32) t.pop_back();  // trim newline/CR/space
    if (t == "dedicated" || t == "background") {
        g_user_override = true;
        Mode m = t == "dedicated" ? Mode::Dedicated : Mode::Background;
        if (m != g_mode) apply_mode(m, "mode.txt");
    } else if (t == "auto" && g_user_override) {
        g_user_override = false;
        apply_mode(g_client_mode, "mode.txt auto: client decides");
    }
}

DWORD WINAPI hotkey_thread(LPVOID) {
    // Global hotkeys belong to one process at a time. Each slot keeps retrying the keys it doesn't hold, so
    // when the owning slot exits another one takes over (M8). State changes go through shared files
    // (mode.txt, view.json), so it doesn't matter which slot owns which key.
    struct Key { int id; UINT vk; const char* what; } keys[] = {
        {1, 'B', "toggle dedicated/background"}, {2, 'V', "watch at 1x"}, {3, 'O', "overlay on/off"}};
    bool logged_fail[3] = {};
    for (;;) {
        for (int i = 0; i < 3; ++i) {
            int bit = 1 << i;
            if (g_hotkeys_owned & bit) continue;
            if (RegisterHotKey(nullptr, keys[i].id, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, keys[i].vk)) {
                g_hotkeys_owned |= bit;
                GLOG("hotkey Ctrl+Alt+%c registered (%s)", char(keys[i].vk), keys[i].what);
            } else if (!logged_fail[i]) {
                logged_fail[i] = true;
                GLOG("hotkey Ctrl+Alt+%c held elsewhere (error %lu); retrying every 3 s (fallback: tools/mode.ps1, view.json)",
                     char(keys[i].vk), GetLastError());
            }
        }
        DWORD wait = g_hotkeys_owned == 7 ? INFINITE : 3000;
        MsgWaitForMultipleObjects(0, nullptr, FALSE, wait, QS_ALLINPUT);
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message != WM_HOTKEY) continue;
            if (msg.wParam == 1) g_hotkey_hit = true;
            else if (msg.wParam == 2) g_hk_watch = true;
            else if (msg.wParam == 3) g_hk_overlay = true;
        }
    }
}

// Draw-skip: {"op":"set_render","present_every_ms":N}. N > 0 draws and presents the scene at most once per
// N ms while the mode is dedicated or background; 0 draws every frame. Normal mode always draws.
// Reply: present_every_ms, frames, presented (counters since launch).
json op_set_render(const json& req) {
    if (!g_draw_skip_supported) return err(req, "UNSUPPORTED", "draw-skip hooks not installed (see bridge.log)");
    if (req.contains("present_every_ms")) {
        int n = req.value("present_every_ms", 0);
        if (n < 0 || n > 60000) return err(req, "BAD_REQUEST", "present_every_ms must be 0..60000");
        if (n != g_present_every_ms) GLOG("set_render: present every %d ms (0 = every frame)", n);
        g_present_every_ms = n;
    }
    json r = ok(req);
    r["present_every_ms"] = g_present_every_ms;
    r["frames"] = g_frames_total;
    r["presented"] = g_frames_presented;
    return r;
}

json op_set_mode(const json& req) {
    std::string m = req.value("mode", "");
    Mode want;
    if (m == "normal") want = Mode::Normal;
    else if (m == "dedicated") want = Mode::Dedicated;
    else if (m == "background") want = Mode::Background;
    else return err(req, "BAD_REQUEST", "unknown mode");
    g_client_mode = want;
    json r = ok(req);
    if (g_user_override) {
        r["overridden_by_user"] = true;  // the user's hotkey / mode.txt choice stands
    } else {
        apply_mode(want, "client set_mode");
    }
    r["mode"] = mode_str(g_mode);
    return r;
}

BOOL CALLBACK find_game_window(HWND h, LPARAM out);

// Debug: save the last presented frame as a BMP (runs on the GL thread; reads the front buffer).
// Lets an agent see the game without bringing the window over the user's screen.
json op_snapshot(const json& req) {
    HMODULE gl = GetModuleHandleW(L"opengl32.dll");
    using ReadPixels_t = void(WINAPI*)(int, int, int, int, unsigned, unsigned, void*);
    using ReadBuffer_t = void(WINAPI*)(unsigned);
    using PixelStore_t = void(WINAPI*)(unsigned, int);
    auto readPixels = gl ? (ReadPixels_t)GetProcAddress(gl, "glReadPixels") : nullptr;
    auto readBuffer = gl ? (ReadBuffer_t)GetProcAddress(gl, "glReadBuffer") : nullptr;
    auto pixelStore = gl ? (PixelStore_t)GetProcAddress(gl, "glPixelStorei") : nullptr;
    HWND w = nullptr;
    EnumWindows(find_game_window, LPARAM(&w));
    RECT rc{};
    if (!readPixels || !readBuffer || !pixelStore || !w || !GetClientRect(w, &rc) || rc.right <= 0 || rc.bottom <= 0)
        return err(req, "INTERNAL", "no GL window to read");
    int width = rc.right, height = rc.bottom, stride = (width * 3 + 3) & ~3;
    std::vector<unsigned char> px(size_t(stride) * height);
    pixelStore(0x0D05 /*GL_PACK_ALIGNMENT*/, 4);
    readBuffer(0x0404 /*GL_FRONT*/);
    readPixels(0, 0, width, height, 0x80E0 /*GL_BGR*/, 0x1401 /*GL_UNSIGNED_BYTE*/, px.data());
    readBuffer(0x0405 /*GL_BACK*/);
    std::wstring path = g_paths.inst_dir + L"\\snapshot.bmp";
    FILE* f = _wfopen(path.c_str(), L"wb");
    if (!f) return err(req, "INTERNAL", "cannot write snapshot.bmp");
    BITMAPFILEHEADER fh{0x4D42, DWORD(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER) + px.size()), 0, 0,
                        DWORD(sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER))};
    BITMAPINFOHEADER ih{sizeof(BITMAPINFOHEADER), width, height, 1, 24, BI_RGB, DWORD(px.size()), 0, 0, 0, 0};
    fwrite(&fh, sizeof fh, 1, f); fwrite(&ih, sizeof ih, 1, f); fwrite(px.data(), 1, px.size(), f);
    fclose(f);
    char p8[MAX_PATH * 3];
    WideCharToMultiByte(CP_UTF8, 0, path.c_str(), -1, p8, sizeof p8, nullptr, nullptr);
    json r = ok(req);
    r["path"] = p8; r["width"] = width; r["height"] = height;
    return r;
}

json handle(const std::string& text) {
    json req;
    try { req = json::parse(text); } catch (const std::exception&) { return err(json::object(), "BAD_REQUEST", "invalid JSON"); }
    if (!req.is_object() || !req.contains("op") || !req["op"].is_string()) return err(req, "BAD_REQUEST", "missing op");
    std::string op = req["op"];
    try {
        if (op == "hello") return op_hello(req);
        if (!g_controlled) return err(req, "BAD_REQUEST", "send hello first");
        if (op == "load_level") return op_load_level(req);
        if (op == "reset") return op_reset(req);
        if (op == "quit_level") return op_quit_level(req);
        if (op == "step") return op_step(req);
        if (op == "set_mode") return op_set_mode(req);
        if (op == "set_render") return op_set_render(req);
        if (op == "debug_peek") return op_debug_peek(req);
        if (op == "snapshot") return op_snapshot(req);
        if (op == "step_seq") return op_step_seq(req);
        if (op == "set_overlay") return op_set_overlay(req);
        if (op == "set_practice") return op_set_practice(req);
        if (op == "checkpoint_create") return op_checkpoint_create(req);
        if (op == "checkpoint_pop") return op_checkpoint_pop(req);
        if (op == "trace") { g_trace = req.value("enabled", false); return ok(req); }
        if (op == "bye") { press(false); g_close_after_reply = true; return ok(req); }
        return err(req, "UNKNOWN_OP", op);
    } catch (const std::exception& e) {
        return err(req, "INTERNAL", e.what());
    }
}

void release_control(const char* why) {
    if (!g_controlled) return;
    press(false);
    g_controlled = false;
    g_exec.active = false;  // a paced request whose client left: drop it (no one to reply to)
    g_early_load = json();
    cbf_clear();
    view_release();
    g_trace = false;
    g_present_every_ms = 0;  // the next client starts with every frame drawn
    g_client_mode = Mode::Normal;
    if (!g_user_override) apply_mode(Mode::Normal, "client disconnected");
    GLOG("control released (%s); game runs normally again", why);
}

void send_reply(const json& r) {
    g_rep = r.dump();
    SetEvent(g_rep_ev);
}

// ---- pipe thread ----
bool read_exact(HANDLE h, void* buf, DWORD n) {
    auto* p = static_cast<char*>(buf);
    while (n) {
        DWORD got = 0;
        if (!ReadFile(h, p, n, &got, nullptr) || got == 0) return false;
        p += got; n -= got;
    }
    return true;
}

bool write_frame(HANDLE h, const std::string& s) {
    uint32_t len = uint32_t(s.size());
    DWORD w = 0;
    return WriteFile(h, &len, 4, &w, nullptr) && w == 4 && WriteFile(h, s.data(), len, &w, nullptr) && w == len;
}

// A minimized GD stops its frame loop, so control_frame never answers. While a request is waiting,
// un-minimize the window without focus and drop it to the bottom of the z-order: it stays out of
// the user's way but keeps running. (Async calls: this thread must not block on the UI thread.)
BOOL CALLBACK find_game_window(HWND h, LPARAM out) {
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid != GetCurrentProcessId() || GetWindow(h, GW_OWNER) || !IsWindowVisible(h)) return TRUE;
    *reinterpret_cast<HWND*>(out) = h;
    return FALSE;
}

// Primary defence: the window never minimizes. A minimize request (title-bar button, taskbar click,
// Win+Down) is turned into "send behind every other window"; GD never sees the minimize at all.
// Installed from control_frame (the window's own thread).
WNDPROC g_orig_wndproc = nullptr;
LRESULT CALLBACK no_minimize_wndproc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_SYSCOMMAND && (wp & 0xFFF0) == SC_MINIMIZE) {
        SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        GLOG("minimize request: sent behind other windows instead (a minimized GD stalls the bot)");
        return 0;
    }
    // While a bot client controls the game, mouse/keyboard input to GD is ignored: a stray click in
    // the (now windowed, visible) menu started a level under the bot. Window management still works.
    bool input = (msg >= WM_KEYFIRST && msg <= WM_KEYLAST) || (msg >= WM_MOUSEFIRST && msg <= WM_MOUSELAST) ||
                 msg == WM_INPUT || msg == WM_TOUCH || (msg >= WM_POINTERUPDATE && msg <= WM_POINTERWHEEL);
    if (input && g_controlled) {
        static ULONGLONG s_last = 0;
        if (msg != WM_MOUSEMOVE && msg != WM_INPUT && GetTickCount64() - s_last > 5000) {
            s_last = GetTickCount64();
            GLOG("user input to GD ignored while the bot is in control (msg 0x%x)", msg);
        }
        return msg == WM_INPUT ? DefWindowProcW(h, msg, wp, lp) : 0;
    }
    return CallWindowProcW(g_orig_wndproc, h, msg, wp, lp);
}

// The bot copy must run windowed: a fullscreen GLFW window minimizes itself whenever it loses focus,
// which stalled the bridge while the user used the PC (and crashed freshly launched parallel copies).
// The proper fix is GD's own setting, gv_0025=1 ("windowed") in the bot's save
// (tools/gd_save.py <slot> set gv_0025 1), so GD starts windowed. This runtime switch is only a
// FALLBACK: switching after startup leaves stale GL state (white quadrant, flashing, untinted
// black-and-white sprites), so it keeps the bot running but looks broken. Visuals don't affect play.
void force_windowed() {
    static bool s_done = false;
    if (s_done) return;
    s_done = true;
    wchar_t keep[8] = {0};
    if (GetEnvironmentVariableW(L"GDBOT_KEEP_FULLSCREEN", keep, 8) && keep[0] == L'1') {
        GLOG("display: GDBOT_KEEP_FULLSCREEN=1, leaving the window mode alone");
        return;
    }
    HMODULE cc = GetModuleHandleW(L"libcocos2d.dll");
    using View_t = void*(__cdecl*)();
    using IsFs_t = bool(__fastcall*)(void*);
    using Toggle_t = void(__fastcall*)(void*, bool, bool, bool);
    auto view_fn = cc ? (View_t)GetProcAddress(cc, "?sharedOpenGLView@CCEGLView@cocos2d@@SAPEAV12@XZ") : nullptr;
    auto is_fs = cc ? (IsFs_t)GetProcAddress(cc, "?getIsFullscreen@CCEGLView@cocos2d@@QEBA_NXZ") : nullptr;
    auto is_bl = cc ? (IsFs_t)GetProcAddress(cc, "?getIsBorderless@CCEGLView@cocos2d@@QEBA_NXZ") : nullptr;
    auto toggle = cc ? (Toggle_t)GetProcAddress(cc, "?toggleFullScreen@CCEGLView@cocos2d@@QEAAX_N00@Z") : nullptr;
    void* view = view_fn ? view_fn() : nullptr;
    if (!view || !is_fs || !is_bl || !toggle) { GLOG("force_windowed: cocos exports missing"); return; }
    bool fs = is_fs(view), bl = is_bl(view);
    if (fs || bl) {
        toggle(view, false, false, false);
        GLOG("display: WARNING was fullscreen=%d borderless=%d; switched to windowed as a fallback (visuals will be "
             "broken). Fix: close this slot and run tools/gd_save.py <slot> set gv_0025 1", fs, bl);
    } else {
        GLOG("display: already windowed");
    }
}

void install_no_minimize() {
    static bool s_done = false;
    if (s_done) return;
    HWND w = nullptr;
    EnumWindows(find_game_window, LPARAM(&w));
    if (!w) return;
    s_done = true;
    g_orig_wndproc = (WNDPROC)SetWindowLongPtrW(w, GWLP_WNDPROC, (LONG_PTR)no_minimize_wndproc);
    GLOG("window %p: minimize requests redirected (%s)", (void*)w, g_orig_wndproc ? "ok" : "FAILED");
}

// Fallback for minimizes that bypass WM_SYSCOMMAND (e.g. ShowWindow from another program).
void keep_window_running() {
    static HWND s_wnd = nullptr;
    if (!s_wnd || !IsWindow(s_wnd)) { s_wnd = nullptr; EnumWindows(find_game_window, LPARAM(&s_wnd)); }
    if (!s_wnd || !IsIconic(s_wnd)) return;
    ShowWindowAsync(s_wnd, SW_SHOWNOACTIVATE);
    SetWindowPos(s_wnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS);
    GLOG("window was minimized: restored behind other windows so the bot keeps running");
}

// Pipe access (#36): only this user and SYSTEM may connect (remote clients were already rejected).
SECURITY_ATTRIBUTES* pipe_security() {
    static SECURITY_ATTRIBUTES sa{};
    static bool s_done = false;
    if (s_done) return sa.lpSecurityDescriptor ? &sa : nullptr;
    s_done = true;
    HANDLE tok = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) return nullptr;
    alignas(8) BYTE buf[256];
    DWORD n = 0;
    LPWSTR sid = nullptr;
    if (GetTokenInformation(tok, TokenUser, buf, sizeof buf, &n) &&
        ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buf)->User.Sid, &sid)) {
        std::wstring sddl = L"D:P(A;;GA;;;SY)(A;;GA;;;" + std::wstring(sid) + L")";
        PSECURITY_DESCRIPTOR sd = nullptr;
        if (ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &sd, nullptr)) {
            sa.nLength = sizeof sa;
            sa.lpSecurityDescriptor = sd;  // kept for the process lifetime
            sa.bInheritHandle = FALSE;
        }
        LocalFree(sid);
    }
    CloseHandle(tok);
    GLOG("pipe: access %s", sa.lpSecurityDescriptor ? "limited to this user and SYSTEM" : "DEFAULT (security descriptor failed)");
    return sa.lpSecurityDescriptor ? &sa : nullptr;
}

DWORD WINAPI pipe_thread(LPVOID) {
    for (;;) {
        HANDLE h = CreateNamedPipeW(g_pipe_name.c_str(), PIPE_ACCESS_DUPLEX,
                                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                    1, 1 << 20, 1 << 20, 0, pipe_security());
        if (h == INVALID_HANDLE_VALUE) { GLOG("CreateNamedPipe failed: %lu", GetLastError()); return 1; }
        if (!ConnectNamedPipe(h, nullptr) && GetLastError() != ERROR_PIPE_CONNECTED) { CloseHandle(h); continue; }
        GLOG("pipe: client connected");
        g_client_gone = false;
        for (;;) {
            uint32_t len = 0;
            if (!read_exact(h, &len, 4) || len == 0 || len > (64u << 20)) break;
            std::string body(len, '\0');
            if (!read_exact(h, body.data(), len)) break;
            g_req = std::move(body);
            SetEvent(g_req_ev);
            while (WaitForSingleObject(g_rep_ev, 250) == WAIT_TIMEOUT) keep_window_running();
            bool close = g_close_after_reply;
            g_close_after_reply = false;
            if (!write_frame(h, g_rep) || close) break;
        }
        g_client_gone = true;
        FlushFileBuffers(h);
        DisconnectNamedPipe(h);
        CloseHandle(h);
        GLOG("pipe: client disconnected");
    }
}

}  // namespace

bool start_control() {
    view_session_init();  // GDBOT_SESSION fresh (default) | keep: launch defaults before mode.txt is first read
    HMODULE cc = GetModuleHandleW(L"libcocos2d.dll");
    if (cc) {
        f_sharedDirector = (SharedDirector_t)GetProcAddress(cc, "?sharedDirector@CCDirector@cocos2d@@SAPEAV12@XZ");
        f_replaceScene = (ReplaceScene_t)GetProcAddress(cc, "?replaceScene@CCDirector@cocos2d@@QEAA_NPEAVCCScene@2@@Z");
        f_getRotation = (GetRotation_t)GetProcAddress(cc, "?getRotation@CCNode@cocos2d@@UEAAMXZ");
        f_arrCount = (CCArrayCount_t)GetProcAddress(cc, "?count@CCArray@cocos2d@@QEBAIXZ");
        f_arrAt = (CCArrayAt_t)GetProcAddress(cc, "?objectAtIndex@CCArray@cocos2d@@QEAAPEAVCCObject@2@I@Z");
    }
    g_req_ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    g_rep_ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    g_pipe_name = L"\\\\.\\pipe\\gdbot-" + std::to_wstring(GetCurrentProcessId());
    HANDLE t = CreateThread(nullptr, 0, pipe_thread, nullptr, 0, nullptr);
    if (!t) return false;
    CloseHandle(t);
    if (HANDLE hk = CreateThread(nullptr, 0, hotkey_thread, nullptr, 0, nullptr)) CloseHandle(hk);
    g_mode_file_time = FILETIME{};  // apply an existing mode.txt (a persisted user choice) on the first poll
    FILE* f = _wfopen((g_paths.inst_dir + L"\\bridge.json").c_str(), L"w");
    if (f) {
        char name[256];
        WideCharToMultiByte(CP_UTF8, 0, g_pipe_name.c_str(), -1, name, sizeof(name), nullptr, nullptr);
        json d = {{"pipe", name}, {"pid", GetCurrentProcessId()}, {"proto", kProto}, {"instance", g_paths.slot}};
        fputs(d.dump().c_str(), f);
        fclose(f);
    }
    GLOG("control: pipe %ls", g_pipe_name.c_str());
    return true;
}

void control_frame(float) {
    force_windowed();
    install_no_minimize();
    if (g_client_gone.exchange(false)) release_control("client disconnected");
    view_frame(mode_str(g_mode), g_layer ? progress() : 0.0f);
    if (!g_early_load.is_null() && update_ready()) {
        json req = std::move(g_early_load);
        g_early_load = json();
        json r = op_load_level(req);
        if (!r.is_null()) send_reply(r);
        return;
    }
    update_ready();
    if (g_exec.active) {      // a step/step_seq paced at 1x: nothing else is served until it replies
        exec_pace_frame();
        return;
    }
    if (g_quit_pending) {
        // The fade back to the menu is timed in seconds, not frames. At uncapped frame rates (window
        // hidden or minimized) 45 frames passed before it ended, and the next load_level then
        // started inside the transition and never reached startGame. Require both.
        static ULONGLONG s_gone_at = 0;
        if (g_layer) s_gone_at = 0;
        else if (!s_gone_at) s_gone_at = GetTickCount64();
        if (!g_layer && ++g_quit_wait_frames >= 45 && GetTickCount64() - s_gone_at >= 1000) {
            s_gone_at = 0;
            g_quit_pending = false;
            GLOG("quit_level: back at the menu");
            send_reply(g_quit_reply);
        }
        return;
    }
    if (g_load_pending) {
        if (g_load_seen_layer && !g_layer) {
            g_load_pending = false;
            g_load_seen_layer = false;
            GLOG("load_level: the level quit by itself before starting");
            send_reply(err(g_load_reply, "INTERNAL", "level quit before it started (see bridge.log for the onQuit caller)"));
            return;
        }
        if (g_layer) g_load_seen_layer = true;
        if (g_layer && g_frames_in_level > 900 && !g_started) {
            g_load_pending = false;
            GLOG("load_level: level never started (no startGame after 900 frames)");
            send_reply(err(g_load_reply, "INTERNAL", "level did not start"));
            return;
        }
        if (g_layer && g_started && ++g_load_wait_frames >= 10) {
            g_load_pending = false;
            g_load_seen_layer = false;
            GLOG("load_level: level ready");
            send_reply(g_load_reply);
        }
        return;  // nothing else is served until the deferred reply is sent
    }
    static int s_mode_poll = 0;
    if (++s_mode_poll >= 60) { s_mode_poll = 0; poll_user_mode(); }
    const double budget_ms = g_mode == Mode::Dedicated ? 12.0 : g_mode == Mode::Background ? 6.0 : 0.0;
    const double start = log::now_ms();
    for (;;) {
        double left = budget_ms - (log::now_ms() - start);
        DWORD wait = left > 0 ? DWORD(left) : 0;
        if (WaitForSingleObject(g_req_ev, wait) != WAIT_OBJECT_0) break;
        json r = handle(g_req);
        if (r.is_null()) return;  // deferred (load_level, quit_level, a step paced at 1x)
        send_reply(r);
        if (g_mode == Mode::Normal) break;  // normal: one request per frame
    }
}

}  // namespace gdbot
