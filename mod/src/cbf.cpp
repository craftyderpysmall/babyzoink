// M8 CBF: a bot press lands at a fraction of a physics step, using the core mechanism of Click Between Frames
// (theyareonit/Click-Between-Frames v1.5.0 @9fa7c6f, MIT; src/main.cpp L389-489). User rule: always on, every
// level; vanilla Click Between Steps / Click On Steps forced off; no physics bypass.
//
// For an input at fraction f of a step, player 1's PlayerObject::update(dt) becomes (when not buffering):
//   update(dt*f); [first sub-step: restore m_isOnGround if moving down relative to gravity];
//   checkCollisions(p, slope && !dart ? dt : 0, true); updateRotation(dt*f); reset the collision log;
//   handleButton(input); update(dt*(1-f))
// and the vanilla end-of-step updateRotation applies the remaining rotation (dt*(1-f)) and restores
// m_lastPosition to the pre-step position. A buffering player (airborne without ring/dash/ship/bird/dart/
// swing) is not split: the input is applied before a full-step update, as click-on-steps would. Player 2 is
// split only in dual mode (the bridge has no dual control; m_isDualMode is not mapped yet, so player 2 is never
// split and, as in CBF, gets its full-step update inside player 1's split with its own call skipped that tick).
//
// Offsets (exe 4eee06d5c2e2213b, GD 2.2091), from geode-sdk/bindings 2.2091 member order anchored on verified
// fields, then checked live (tools/m8/cbf_offsets notes in docs/PROTOCOL.md):
#include <windows.h>
#include <MinHook.h>
#include <cstdint>
#include "bridge.hpp"
#include "log.hpp"

namespace gdbot {
namespace {

constexpr uintptr_t kRvaUpdateRotation = 0x4ef390;   // PlayerObject::updateRotation(float)  (bindings 2.2091)
constexpr uintptr_t kRvaCheckCollisions = 0x31aae0;  // GJBaseGameLayer::checkCollisions(PlayerObject*, float, bool)
constexpr size_t kLayerPlayer2 = 0xdc0;              // GJBaseGameLayer::m_player2 (m_player1 0xdb8 + 8; m_objects 0xdd0)
constexpr size_t kLayerClickBetweenSteps = 0x38f1;   // m_anticheatSpike 0x38e0, m_timestamp 0x38e8, m_isBetweenSteps 0x38f0
constexpr size_t kLayerClickOnSteps = 0x38f2;
constexpr size_t kIsOnSlope = 0x9b8;                 // m_yVelocity 0x9a8, m_fallSpeed 0x9b0, m_isOnSlope, m_wasOnSlope 0x9b9
constexpr size_t kTouchingRings = 0xa40;             // CCArray*; forward from m_playerSpeed 0x9fc = backward from m_position 0xa98
constexpr size_t kLastPosition = 0x4d0;              // CCPoint; live: holds the previous tick's x
constexpr size_t kCollisionLogs = 0x5b0;             // 4 x CCDictionary* (top, bottom, left, right); live: unique heap run
constexpr size_t kLastCollisions = 0x5d0;            // 4 x int, -1 when clear (bottom, top, left, right)
constexpr size_t kPosX = 0x4c, kPosY = 0x50;         // CCNode position (= PlayerObject::getPosition)

using PlayerUpdate_t = void(__fastcall*)(void*, float);
using UpdateRotation_t = void(__fastcall*)(void*, float);
using CheckCollisions_t = int(__fastcall*)(void*, void*, float, bool);
using DictRemoveAll_t = void(__fastcall*)(void*);
using ArrCount_t = unsigned(__fastcall*)(void*);
PlayerUpdate_t o_playerUpdate = nullptr;
UpdateRotation_t o_updateRotation = nullptr;
CheckCollisions_t f_checkCollisions = nullptr;
DictRemoveAll_t f_dictRemoveAll = nullptr;
ArrCount_t f_arrCount = nullptr;

struct Pending { bool armed = false; bool down = false; double frac = 0.0; };
Pending g_in;                // the input to apply inside the next player-1 update
bool g_mid = false;          // inside the split (sub-step updates go straight to the original)
bool g_p1_split = false, g_p2_split = false;
bool g_p2_done = false;      // player 2 already advanced inside player 1's split this tick
float g_rot_delta = 0.0f;
float g_p1_pos[2] = {0, 0}, g_p2_pos[2] = {0, 0};
long long g_splits = 0, g_buffered = 0;

template <class T> void write_field(void* base, size_t off, T v) { if (base) *reinterpret_cast<T*>(static_cast<char*>(base) + off) = v; }

void* player2() { return g_layer ? read_field<void*>(g_layer, kLayerPlayer2) : nullptr; }

void reset_collision_log(void* p) {  // PlayerObject::resetCollisionLog, inlined on Windows (CBF's decomp)
    for (int i = 0; i < 4; ++i)
        if (void* d = read_field<void*>(p, kCollisionLogs + 8 * i)) f_dictRemoveAll(d);
    for (int i = 0; i < 4; ++i) write_field<int>(p, kLastCollisions + 4 * i, -1);
}

bool not_buffering(void* p) {
    if (read_field<uint8_t>(p, fields::kIsOnGround)) return true;
    void* rings = read_field<void*>(p, kTouchingRings);
    if (rings && f_arrCount(rings) > 0) return true;
    if (read_field<uint8_t>(p, fields::kIsDashing)) return true;
    return read_field<uint8_t>(p, fields::kIsDart) || read_field<uint8_t>(p, fields::kIsBird) ||
           read_field<uint8_t>(p, fields::kIsShip) || read_field<uint8_t>(p, fields::kIsSwing);
}

void apply_input() {
    o_handleButton(g_layer, g_in.down, 1, true);
    g_held = g_in.down;
    g_in.armed = false;
}

void __fastcall h_playerUpdate(void* self, float dt) {
    void* p1 = player1();
    if (!g_in_step || !g_layer || g_mid || self != p1) {
        if (self == player2() && g_p2_done) { g_p2_done = false; return; }  // already advanced in p1's split
        o_playerUpdate(self, dt);
        return;
    }
    g_p2_done = false;  // a new tick starts with player 1's update
    if (!g_in.armed) {
        g_p1_split = false;
        o_playerUpdate(self, dt);
        return;
    }
    void* p2 = player2();
    bool p1_ground = read_field<uint8_t>(self, fields::kIsOnGround) != 0;
    g_p1_split = not_buffering(self);
    g_p2_split = false;  // dual not mapped: see header
    g_p1_pos[0] = read_field<float>(self, kPosX), g_p1_pos[1] = read_field<float>(self, kPosY);
    g_mid = true;
    if (g_p1_split) {
        float f = float(g_in.frac);
        float first = dt * f, rest = dt * (1.0f - f);
        g_rot_delta = first;
        o_playerUpdate(self, first);
        if ((read_field<double>(self, fields::kYVelocity) < 0) ^ (read_field<uint8_t>(self, fields::kIsUpsideDown) != 0))
            write_field<uint8_t>(self, fields::kIsOnGround, p1_ground ? 1 : 0);
        bool slope = read_field<uint8_t>(self, kIsOnSlope) != 0, dart = read_field<uint8_t>(self, fields::kIsDart) != 0;
        f_checkCollisions(g_layer, self, (!slope || dart) ? 0.0f : dt, true);
        o_updateRotation(self, first);
        reset_collision_log(self);
        apply_input();
        g_rot_delta = rest;
        o_playerUpdate(self, rest);
        ++g_splits;
    } else {
        apply_input();  // buffering: click-on-steps behaviour (input, then a full step)
        o_playerUpdate(self, dt);
        ++g_buffered;
    }
    if (p2 && p2 != self) {  // as CBF: player 2 advances here (full step, not split) and skips its own call
        o_playerUpdate(p2, dt);
        g_p2_done = true;
    }
    g_mid = false;
}

void __fastcall h_updateRotation(void* self, float t) {
    if (g_layer && !g_mid && g_p1_split && self == player1()) {
        o_updateRotation(self, g_rot_delta);  // the rotation left incomplete by the split
        write_field<float>(self, kLastPosition, g_p1_pos[0]);
        write_field<float>(self, kLastPosition + 4, g_p1_pos[1]);
        g_p1_split = false;
        return;
    }
    o_updateRotation(self, t);
}

}  // namespace

bool g_cbf_ok = false;

bool install_cbf() {
    HMODULE cc = GetModuleHandleW(L"libcocos2d.dll");
    f_dictRemoveAll = cc ? (DictRemoveAll_t)GetProcAddress(cc, "?removeAllObjects@CCDictionary@cocos2d@@QEAAXXZ") : nullptr;
    f_arrCount = cc ? (ArrCount_t)GetProcAddress(cc, "?count@CCArray@cocos2d@@QEBAIXZ") : nullptr;
    f_checkCollisions = reinterpret_cast<CheckCollisions_t>(g_exe_base + kRvaCheckCollisions);
    void* upd = rva_ptr(offsets::PlayerObject__update);
    void* rot = reinterpret_cast<void*>(g_exe_base + kRvaUpdateRotation);
    MH_STATUS a = upd ? MH_CreateHook(upd, (void*)h_playerUpdate, (void**)&o_playerUpdate) : MH_ERROR_FUNCTION_NOT_FOUND;
    MH_STATUS b = MH_CreateHook(rot, (void*)h_updateRotation, (void**)&o_updateRotation);
    g_cbf_ok = f_dictRemoveAll && f_arrCount && a == MH_OK && b == MH_OK;
    GLOG("cbf: PlayerObject::update %s, updateRotation %s, exports %d -> %s", MH_StatusToString(a), MH_StatusToString(b),
         f_dictRemoveAll && f_arrCount, g_cbf_ok ? "ready" : "UNAVAILABLE");
    return g_cbf_ok;
}

// Called by the step executor at the start of a decision whose press/release has fraction f in (0, 1).
// Returns false if CBF can't take it (the caller then presses at the step start).
bool cbf_arm(bool down, double frac) {
    if (!g_cbf_ok || !g_layer) return false;
    g_in = {true, down, frac};
    return true;
}

// After the decision's first tick: an input the split didn't consume (no player-1 update ran) is applied now.
void cbf_settle() {
    if (g_in.armed) {
        GLOG("cbf: input not consumed by a player update this tick; applied after it");
        apply_input();
    }
}

void cbf_clear() { g_in.armed = false; g_p1_split = false; g_p2_done = false; g_mid = false; }

// User rule: vanilla Click Between Steps and Click On Steps are always off.
void cbf_force_vanilla_click_off() {
    if (!g_layer) return;
    write_field<uint8_t>(g_layer, kLayerClickBetweenSteps, 0);
    write_field<uint8_t>(g_layer, kLayerClickOnSteps, 0);
}

void cbf_click_flags(bool* between, bool* on) {
    *between = g_layer && read_field<uint8_t>(g_layer, kLayerClickBetweenSteps) != 0;
    *on = g_layer && read_field<uint8_t>(g_layer, kLayerClickOnSteps) != 0;
}

long long cbf_split_count() { return g_splits; }
long long cbf_buffered_count() { return g_buffered; }

}  // namespace gdbot
