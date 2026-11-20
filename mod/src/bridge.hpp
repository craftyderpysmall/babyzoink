#pragma once
#include <windows.h>
#include <atomic>
#include <string>
#include <vector>
#include "offsets_gen.hpp"

namespace gdbot {

struct Paths {
    std::wstring game_dir;       // folder containing GeometryDash.exe (no trailing slash)
    std::wstring bot_dir;        // game_dir\gdbot (shared: mode.txt lives here so one toggle drives every instance)
    std::wstring inst_dir;       // per-instance: bot_dir for slot 0, bot_dir\inst<N> for slot N (bridge.json, bridge.log, save\)
    int slot = 0;                // GDBOT_INSTANCE set by gdbot-launch --instance N (absent = 0)
    std::wstring save_dir;       // game_dir\gdbot\save\  (trailing slash)
    std::wstring real_save_dir;  // %LOCALAPPDATA%\GeometryDash (no trailing slash) — never touched
};

inline Paths g_paths;
inline const offsets::Build* g_build = nullptr;
inline uintptr_t g_exe_base = 0;

struct IsolationState {
    bool file_guard = false;      // writes/reads under real_save_dir are denied
    bool saves_redirected = false;  // CCFileUtilsWin32::getWritablePath hooked
    bool http_blocked = false;    // CCHttpClient::send and curl_easy_perform hooked
    bool score_upload_blocked = false;  // GameLevelManager::updateUserScore no-op
};
inline IsolationState g_iso;

// ---- PlayerObject / GJBaseGameLayer fields for exe 4eee06d5c2e2213b (2.2091) ----
// Source of truth: "fields" in mod/offsets/4eee06d5c2e2213b.json (verified from live probe data).
// Only valid for that build; gdbot_init refuses any other exe.
namespace fields {
constexpr size_t kLayerPlayer1 = 0xdb8;
constexpr size_t kPosTickX = 0x4c, kPosTickY = 0x50;  // f32, updated every tick
constexpr size_t kYVelocity = 0x9a8;                  // f64
constexpr size_t kIsShip = 0x9c1, kIsBird = 0x9c2, kIsBall = 0x9c3, kIsDart = 0x9c4, kIsRobot = 0x9c5,
                 kIsSpider = 0x9c6, kIsUpsideDown = 0x9c7, kIsDead = 0x9c8, kIsOnGround = 0x9c9, kIsSwing = 0x9cc;
constexpr size_t kIsDashing = 0x9ec;
// m_stateJumpBuffered: 1 after a fresh press while held, cleared on release, consumed when a jump/orb fires.
// Verified 2026-11-18 with tools/m1/orb_probe.py (held-out yellow-orb drill, 3 input cases).
constexpr size_t kJumpBuffered = 0x98e;
constexpr size_t kVehicleSize = 0x9f8, kPlayerSpeed = 0x9fc;  // f32
// M1b (pending live verification): GJBaseGameLayer::m_objects follows m_player1/m_player2/m_levelSettings;
// GameObject offsets derived from bindings order anchored on the m_unkXXX names (m_unk390, m_unk3D8,
// m_unk3DE, m_unk3E8, m_unk3F8 all consistent).
constexpr size_t kLayerObjects = 0xdd0;          // CCArray*
// Verified live 2026-11-18 (objprobe.bin, Stereo Madness, 400 objects): the anchor-derived estimate
// was 0x18 too low. type: 93% of spike-shaped hitboxes = 2 (hazard), mode 7 (decoration), with the same
// value repeated at +0x3a4 (m_savedObjectType); id: hazards 8/9/39, solids 1/2/3/7/40, decor 5;
// uniqueID: 400/400 unique.
constexpr size_t kObjUniqueID = 0x39c;           // int
constexpr size_t kObjType = 0x3a0;               // GameObjectType (int)
constexpr size_t kObjID = 0x40c;                 // int (object id, e.g. 8 = spike)
// M9 (2026-11-20, live on Because I Loved Her): GJBaseGameLayer::m_player2 = m_player1 + 8; m_gameState.m_isDualMode
// flips 0 -> 1 exactly when player 2 starts moving independently of player 1 (decision ~4224 of that level).
constexpr size_t kLayerPlayer2 = 0xdc0;
constexpr size_t kLayerDualMode = 0x3f3;
constexpr size_t kIsGoingLeft = 0x9ca;           // between m_isOnGround 0x9c9 and m_isSideways 0x9cb (bindings order)
// M9 world state (Codex #55, disassembly of exe 4eee06d5c2e2213b): GJBaseGameLayer::toggleGroup writes
// GameObject::m_isGroupDisabled; activateObject/deactivateObject write m_isActivated (bulk-toggled on group
// enables, so NOT used as a pickup signal); GJEffectManager::countForItem reads the item map.
constexpr size_t kObjGroupDisabled = 0x28e;      // bool
constexpr size_t kObjActivated = 0x305;          // bool (diagnostic only)
constexpr size_t kLayerEffectManager = 0x968;    // GJEffectManager*
constexpr size_t kEffItemMapHead = 0x338;        // MSVC unordered_map<int,int> at +0x330: list head node*; node key/value +0x10/+0x14
constexpr size_t kEffItemMapSize = 0x340;
}  // namespace fields

// ---- shared game-thread state (written by hooks.cpp, read by control.cpp) ----
inline void* g_layer = nullptr;          // current PlayLayer* (null outside a level)
inline long long g_tick = 0;             // processCommands calls since the last reset = physics ticks
inline bool g_held = false;              // player-1 button as last passed to handleButton
inline bool g_completed = false;         // levelComplete fired since the last reset
inline bool g_end_reached = false;
inline bool g_bot_checkpoint = false;    // the current storeCheckpoint call was requested by the bot       // player crossed the level end this episode (tick-driven; playEndAnimationToPos)
inline bool g_controlled = false;        // a client owns the game: physics only advances inside step()
inline bool g_in_step = false;           // we are inside a bot-driven update call
inline bool g_bot_reset = false;         // the current resetLevel call was requested by the bot
inline bool g_in_init = false;           // inside PlayLayer::init
inline int g_frames_in_level = 0;        // frames since PlayLayer::init returned
inline bool g_started = false;
inline void* g_anticheat_obj = nullptr;
// Draw-skip (set_render): in dedicated/background mode with a client in control, the scene is drawn and
// presented at most once per g_present_every_ms; other frames skip the scene visit and swapBuffers.
// 0 = draw every frame (default; identical to earlier builds). Rendering never feeds the simulation.
inline int g_present_every_ms = 0;
inline bool g_skip_draw = false;
inline bool g_mode_allows_skip = false;    // dedicated or background (normal mode always draws)
inline bool g_draw_skip_supported = false; // all four cocos2d exports hooked         // decided once per frame in CCScheduler::update, before the draw
inline long long g_frames_total = 0, g_frames_presented = 0;
inline long long g_anticheat_off = -1;  // GJBaseGameLayer::m_anticheatSpike, learned at runtime  // GD's hidden anticheat spike: the object destroyPlayer gets in the first ticks after a reset           // PlayLayer::startGame has run for the current layer

// ---- original (trampoline) function pointers, set by install_hooks ----
using HandleButton_t = void(__fastcall*)(void*, bool, int, bool);
using BglUpdate_t = void(__fastcall*)(void*, float);
using Void0_t = void(__fastcall*)(void*);
using SchedUpdate_t = void(__fastcall*)(void*, float);
inline HandleButton_t o_handleButton = nullptr;
inline BglUpdate_t o_bglUpdate = nullptr;
inline Void0_t o_resetLevel = nullptr;

// ---- M8 human view (view.cpp; plan .coordination/plans/2026-11-19-m8-human-view-and-cbf.md) ----
// Shared across slots through gdbot/view.json {"overlay": bool, "watch_slot": int|null}; every slot polls it.
inline bool g_watch = false;        // this slot plays at 1x (view.json watch_slot == this slot)
inline bool g_overlay_on = true;    // overlay shown (default on; Ctrl+Alt+O)
inline std::atomic<bool> g_hk_watch{false}, g_hk_overlay{false};  // hotkey presses, consumed by view_frame
inline std::atomic<int> g_hotkeys_owned{0};  // bits: 1 = Ctrl+Alt+B, 2 = V, 4 = O registered by this slot
struct ViewStats {
    std::string level = "-";          // current level name
    long long runs = 0, practice = 0; // full runs from 0% / checkpoint restores since the level loaded
    float best = 0.0f;                // best progress (0..1) this level
    long long ticks_run = 0;          // physics ticks the bot has advanced (monotonic; for ticks/s)
};
inline ViewStats g_vstats;
void view_session_init();                                // at init: GDBOT_SESSION=fresh (default) | keep
void view_frame(const char* mode_label, float progress); // game thread, once per control_frame
void view_set_client(const std::string& job, const std::vector<std::string>& lines);  // set_overlay op
void view_release();                                     // client gone: drop client-provided lines

// ---- M8 CBF (cbf.cpp): presses at a fraction of a physics step, CBF's core mechanism ----
bool install_cbf();                          // hooks PlayerObject::update / updateRotation (not fatal)
extern bool g_cbf_ok;
bool cbf_arm(bool down, double frac);        // next player-1 update splits at frac and applies the input there
void cbf_settle();                           // after the tick: apply an input no player update consumed
void cbf_clear();                            // reset / disconnect
void cbf_force_vanilla_click_off();          // user rule: vanilla Click Between Steps / Click On Steps off
void cbf_click_flags(bool* between, bool* on);
long long cbf_split_count();
long long cbf_buffered_count();

std::string sha256_file_hex(const std::wstring& path);
bool install_isolation();   // fatal if false
bool install_hooks();       // fatal if false (game hooks the controller depends on)
bool start_control();       // pipe server thread + discovery file
void control_frame(float dt);  // called once per frame on the game thread (CCScheduler::update)

bool safe_copy(void* dst, const void* src, size_t n);

inline void* rva_ptr(offsets::Fn fn) {
    uintptr_t r = g_build->rva[fn];
    return r ? reinterpret_cast<void*>(g_exe_base + r) : nullptr;
}

// M9 death attribution: set by the PlayLayer::destroyPlayer hook (excluding GD's hidden anticheat spike).
struct DeathInfo {
    bool set = false; int player = 0; bool object_null = true; int obj_id = 0, obj_type = 0, uid = 0;
    bool obj_disabled = false; float x = 0, y = 0; long long tick = 0;
    unsigned long long caller_rva = 0;  // destroyPlayer's caller (exe-relative), to tell collision from scripted/boundary kills
};
inline DeathInfo g_death;

inline void* player1() {
    if (!g_layer) return nullptr;
    void* p = nullptr;
    if (!safe_copy(&p, static_cast<char*>(g_layer) + fields::kLayerPlayer1, sizeof(p))) return nullptr;
    return p;
}

template <class T>
inline T read_field(void* base, size_t off, T fallback = T{}) {
    T v{};
    return (base && safe_copy(&v, static_cast<char*>(base) + off, sizeof(T))) ? v : fallback;
}

inline void* player2() { return g_layer ? read_field<void*>(g_layer, fields::kLayerPlayer2) : nullptr; }
inline bool dual_mode() { return g_layer && read_field<uint8_t>(g_layer, fields::kLayerDualMode) != 0; }

}  // namespace gdbot
