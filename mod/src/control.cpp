// Protocol v0 server (docs/PROTOCOL.md): named pipe \\.\pipe\gdbot-<pid>, u32 LE length + UTF-8 JSON,
// strictly alternating request/reply. The pipe thread only moves bytes; every request is executed
// on the game thread inside control_frame() (called from CCScheduler::update).
#include <windows.h>
#include <atomic>
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

json err(const json& req, const char* code, const std::string& msg) {
    return {{"id", req.value("id", 0)}, {"ok", false}, {"error", {{"code", code}, {"msg", msg}}}};
}
json ok(const json& req) { return {{"id", req.value("id", 0)}, {"ok", true}}; }

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

json obs_json() {
    void* p = player1();
    bool truncated = false;
    json objs = objects_json(read_field<float>(p, fields::kPosTickX), &truncated);
    json unsupported = json::array({"on_ceiling", "button_queue", "object_active", "moving_objects_partial"});
    if (!g_objects_ok) unsupported.push_back("objects");
    json o = {
        {"players", json::array({player_json(p)})},
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

// ---- operations ----
json op_hello(const json& req) {
    if (req.value("proto", -1) != kProto) return err(req, "BAD_REQUEST", "unsupported protocol version");
    g_controlled = true;
    GLOG("client hello (%s); bot now controls the game", req.value("client", std::string("?")).c_str());
    json r = ok(req);
    r["proto"] = kProto;
    r["build"] = {{"exe_sha256", g_build->exe_sha256}, {"game_version", g_build->game_version}};
    r["capabilities"] = {{"step", true}, {"reset", true}, {"startpos", false}, {"checkpoint", true},
                         {"trace", true}, {"modes", {"normal", "dedicated", "background"}}, {"dual", false},
                         {"objects", true}, {"level_string", true}, {"quit_level", true}, {"debug_peek", true}, {"isolation", true}};
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
    g_load_reply["level"] = std::move(info);
}

json op_load_level(const json& req) {
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
    g_prev_tick = -1;
    g_tick_x = read_field<float>(player1(), fields::kPosTickX);
    g_tick_vx = 0.0f;
    rebuild_object_cache();
    json r = ok(req);
    r["episode"] = g_episode;
    r["tick"] = g_tick;
    r["start"] = start_info;
    r["obs"] = obs_json();
    return r;
}

json op_step(const json& req) {
    if (!g_layer) return err(req, "NOT_IN_LEVEL", "no level loaded");
    if (req.value("episode", -1) != g_episode) return err(req, "EPISODE_MISMATCH", "stale episode");
    int action = req.value("action", -1), k = req.value("k", 0);
    if ((action != 0 && action != 1) || k < 1 || k > 240 * 60) return err(req, "BAD_REQUEST", "bad action or k");
    const long long t0 = g_tick;
    json events = json::array(), trace = json::array();
    const char* terminal = nullptr;
    press(action == 1);
    int calls = 0;
    while (g_tick - t0 < k && !terminal) {
        long long before = g_tick;
        g_in_step = true;
        o_bglUpdate(g_layer, kTickDt);
        g_in_step = false;
        if (++calls > 4 * k + 16) {
            GLOG("step: update calls are not producing ticks (calls=%d advanced=%lld)", calls, g_tick - t0);
            return err(req, "INTERNAL", "update calls are not producing physics ticks");
        }
        if (g_tick == before) continue;
        if (g_tick - before > 1) GLOG("step: one update call advanced %lld ticks", g_tick - before);
        void* p = player1();
        {
            float x = read_field<float>(p, fields::kPosTickX);
            g_tick_vx = (x - g_tick_x) / float(g_tick - before);
            g_tick_x = x;
        }
        if (read_field<uint8_t>(p, fields::kIsDead)) {
            terminal = "death";
            events.push_back({{"type", "death"}, {"tick", g_tick}});
        } else if (g_end_reached) {  // tick-driven; GD's levelComplete itself arrives later on a wall-clock timer
            terminal = "complete";
            events.push_back({{"type", "complete"}, {"tick", g_tick}});
        }
        if (g_trace) {
            json row_events = json::array();
            if (terminal) row_events.push_back({{"type", terminal}, {"tick", g_tick}});
            trace.push_back({{"tick", g_tick}, {"players", json::array({player_json(p)})},
                             {"button", {{"held", g_held}, {"queued", nullptr}}}, {"events", row_events}});
        }
    }
    json r = ok(req);
    r["episode"] = g_episode;
    r["tick"] = g_tick;
    r["ticks_advanced"] = g_tick - t0;
    r["obs"] = obs_json();
    r["events"] = events;
    r["terminal"] = terminal ? json(terminal) : json();
    r["mode"] = mode_str(g_mode);  // so the trainer can match its own CPU use (threads, priority)
    if (g_trace) r["trace"] = trace;
    return r;
}

// Dev-only: raw memory read for field mapping. target: "player1" | "layer"; len <= 4096.
json op_debug_peek(const json& req) {
    std::string target = req.value("target", "player1");
    long long off = req.value("off", -1), len = req.value("len", 0);
    if (off < 0 || len <= 0 || len > 4096 || off > 0x10000) return err(req, "BAD_REQUEST", "off/len out of range");
    void* base = target == "layer" ? g_layer : target == "player1" ? player1() : nullptr;
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
    if (!RegisterHotKey(nullptr, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 'B')) {
        GLOG("hotkey Ctrl+Alt+B unavailable (error %lu); use tools/mode.ps1", GetLastError());
        return 1;
    }
    GLOG("hotkey Ctrl+Alt+B registered (toggle dedicated/background)");
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0)
        if (msg.message == WM_HOTKEY) g_hotkey_hit = true;
    return 0;
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
        if (op == "debug_peek") return op_debug_peek(req);
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
    g_trace = false;
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
    return CallWindowProcW(g_orig_wndproc, h, msg, wp, lp);
}

// The bot copy's save runs GD fullscreen (borderless popup). A fullscreen GLFW window minimizes
// itself whenever it loses focus, which is what kept stalling the bridge while the user used the
// PC (and what crashed freshly launched parallel copies, which start unfocused). Run windowed.
void force_windowed() {
    static bool s_done = false;
    if (s_done) return;
    s_done = true;
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
        GLOG("display: was fullscreen=%d borderless=%d; switched to windowed (fullscreen minimizes on focus loss)", fs, bl);
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

DWORD WINAPI pipe_thread(LPVOID) {
    for (;;) {
        HANDLE h = CreateNamedPipeW(g_pipe_name.c_str(), PIPE_ACCESS_DUPLEX,
                                    PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                    1, 1 << 20, 1 << 20, 0, nullptr);
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
        if (r.is_null()) return;  // deferred (load_level)
        send_reply(r);
        if (g_mode == Mode::Normal) break;  // normal: one request per frame
    }
}

}  // namespace gdbot
