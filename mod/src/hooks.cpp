// Game hooks. Pass-through by default (same behaviour as the verified M1 live checks);
// when a client controls the game (g_controlled), physics only advances inside step():
//   - GJBaseGameLayer::update runs only when g_in_step (bot-driven); otherwise it is skipped (frozen)
//   - resetLevel runs only when the bot requested it (or during PlayLayer::init)
//   - pauseGame is suppressed (no auto-pause on focus loss)
// CCScheduler::update (libcocos2d export) drives control_frame() once per frame on the game thread.
#include <windows.h>
#include <MinHook.h>
#include <intrin.h>
#include "bridge.hpp"
#include "log.hpp"

namespace gdbot {

bool safe_copy(void* dst, const void* src, size_t n) {
    __try { memcpy(dst, src, n); return true; } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

namespace {
using namespace offsets;

DWORD g_game_thread = 0;

void thread_check(const char* who) {
    DWORD t = GetCurrentThreadId();
    if (!g_game_thread) { g_game_thread = t; GLOG("game thread = %lu (first seen in %s)", t, who); }
    else if (t != g_game_thread) GLOG("WARN %s on non-game thread %lu", who, t);
}

void __fastcall h_handleButton(void* self, bool down, int button, bool p1) {
    if (!g_controlled) GLOG("handleButton down=%d button=%d isPlayer1=%d tick=%lld", down, button, p1, g_tick);
    if (button == 1) g_held = down;
    o_handleButton(self, down, button, p1);
}

using ProcessCommands_t = void(__fastcall*)(void*, float, bool, bool);
ProcessCommands_t o_processCommands;
void __fastcall h_processCommands(void* self, float dt, bool half, bool last) {
    ++g_tick;
    o_processCommands(self, dt, half, last);
}

long long g_skipped_updates = 0;
void __fastcall h_bglUpdate(void* self, float dt) {
    thread_check("GJBaseGameLayer::update");
    if (g_controlled && !g_in_step) {
        if ((++g_skipped_updates % 600) == 1) GLOG("frozen: skipped scheduler update #%lld", g_skipped_updates);
        return;
    }
    o_bglUpdate(self, dt);
}

using PLInit_t = bool(__fastcall*)(void*, void*, bool, bool);
PLInit_t o_plInit;
bool __fastcall h_plInit(void* self, void* level, bool a, bool b) {
    thread_check("PlayLayer::init");
    GLOG("PlayLayer::init this=%p level=%p", self, level);
    g_in_init = true;
    bool r = o_plInit(self, level, a, b);
    g_in_init = false;
    GLOG("PlayLayer::init -> %d", r);
    if (r) { g_layer = self; g_frames_in_level = 0; g_started = false; g_anticheat_obj = nullptr; }
    return r;
}

void __fastcall h_resetLevel(void* self) {
    if (g_controlled && !g_bot_reset && !g_in_init) {
        GLOG("suppressed non-bot resetLevel at tick %lld (bot in control)", g_tick);
        return;
    }
    if (!g_controlled) GLOG("PlayLayer::resetLevel (tick was %lld)", g_tick);
    g_tick = 0;
    g_completed = false;
    g_end_reached = false;
    o_resetLevel(self);
}

Void0_t o_levelComplete, o_onQuit, o_startGame;
using StoreCp_t = void(__fastcall*)(void*, void*);
StoreCp_t o_storeCheckpoint;
long long g_blocked_cps = 0;
void __fastcall h_storeCheckpoint(void* self, void* cp) {
    if (g_controlled && !g_bot_checkpoint) {  // practice auto-checkpoints: the bot manages its own
        if ((++g_blocked_cps % 50) == 1) GLOG("blocked non-bot storeCheckpoint #%lld (bot in control)", g_blocked_cps);
        return;
    }
    o_storeCheckpoint(self, cp);
}
void __fastcall h_startGame(void* self) {
    GLOG("PlayLayer::startGame");
    o_startGame(self);
    g_started = true;
}
using EndAnim_t = void(__fastcall*)(void*, uint64_t);  // CCPoint (2 x f32) passed by value in one register
EndAnim_t o_endAnim;
void __fastcall h_endAnim(void* self, uint64_t pos) {
    GLOG("PlayLayer::playEndAnimationToPos tick=%lld (level end reached)", g_tick);
    g_end_reached = true;
    o_endAnim(self, pos);
}
void __fastcall h_levelComplete(void* self) {
    if (g_controlled && !g_end_reached) {
        // A real-time end-animation callback from an episode the bot already reset: ignore it.
        GLOG("suppressed stale levelComplete at tick %lld (bot in control, episode was reset)", g_tick);
        return;
    }
    GLOG("PlayLayer::levelComplete tick=%lld", g_tick);
    g_completed = true;
    o_levelComplete(self);
}
void __fastcall h_onQuit(void* self) {
    uintptr_t ra = reinterpret_cast<uintptr_t>(_ReturnAddress());
    if (ra >= g_exe_base && ra < g_exe_base + 0x2000000) GLOG("PlayLayer::onQuit (caller exe+0x%llx)", (unsigned long long)(ra - g_exe_base));
    else GLOG("PlayLayer::onQuit (caller %p, outside exe)", (void*)ra);
    g_layer = nullptr;
    g_started = false;
    o_onQuit(self);
}

using DestroyPlayer_t = void(__fastcall*)(void*, void*, void*);
DestroyPlayer_t o_destroyPlayer;
void __fastcall h_destroyPlayer(void* self, void* player, void* obj) {
    if (g_tick <= 20 && obj && obj != g_anticheat_obj) {
        g_anticheat_obj = obj;
        if (g_anticheat_off < 0) {  // learn GJBaseGameLayer::m_anticheatSpike's offset once
            static unsigned char buf[0x4000];
            if (safe_copy(buf, self, sizeof(buf)))
                for (size_t off = 0; off + 8 <= sizeof(buf); off += 8) {
                    void* v; memcpy(&v, buf + off, 8);
                    if (v == obj) { g_anticheat_off = (long long)off; break; }
                }
            GLOG("anticheat spike object = %p, m_anticheatSpike at layer+0x%llx", obj, (unsigned long long)g_anticheat_off);
        }
    }
    if (!g_controlled && g_tick > 20) GLOG("PlayLayer::destroyPlayer object=%p tick=%lld", obj, g_tick);
    o_destroyPlayer(self, player, obj);
}

using PauseGame_t = void(__fastcall*)(void*, bool);
PauseGame_t o_pauseGame;
void __fastcall h_pauseGame(void* self, bool unfocused) {
    if (g_controlled) { GLOG("suppressed pauseGame(unfocused=%d) (bot in control)", unfocused); return; }
    GLOG("PlayLayer::pauseGame unfocused=%d", unfocused);
    o_pauseGame(self, unfocused);
}

SchedUpdate_t o_schedUpdate;
void __fastcall h_schedUpdate(void* self, float dt) {
    o_schedUpdate(self, dt);
    if (g_layer) ++g_frames_in_level;
    control_frame(dt);
}

bool hook(Fn fn, void* detour, void** orig) {
    void* p = rva_ptr(fn);
    if (!p) { GLOG("hook FAIL %s: not mapped", kFnNames[fn]); return false; }
    MH_STATUS s = MH_CreateHook(p, detour, orig);
    GLOG("hook %s @ exe+0x%llx: %s", kFnNames[fn], (unsigned long long)g_build->rva[fn], MH_StatusToString(s));
    return s == MH_OK;
}

}  // namespace

bool install_hooks() {
    bool ok = true;
    ok &= hook(GJBaseGameLayer__handleButton, (void*)h_handleButton, (void**)&o_handleButton);
    ok &= hook(GJBaseGameLayer__processCommands, (void*)h_processCommands, (void**)&o_processCommands);
    ok &= hook(GJBaseGameLayer__update, (void*)h_bglUpdate, (void**)&o_bglUpdate);
    ok &= hook(PlayLayer__init, (void*)h_plInit, (void**)&o_plInit);
    ok &= hook(PlayLayer__resetLevel, (void*)h_resetLevel, (void**)&o_resetLevel);
    ok &= hook(PlayLayer__levelComplete, (void*)h_levelComplete, (void**)&o_levelComplete);
    ok &= hook(PlayLayer__onQuit, (void*)h_onQuit, (void**)&o_onQuit);
    ok &= hook(PlayLayer__destroyPlayer, (void*)h_destroyPlayer, (void**)&o_destroyPlayer);
    ok &= hook(PlayLayer__playEndAnimationToPos, (void*)h_endAnim, (void**)&o_endAnim);
    ok &= hook(PlayLayer__storeCheckpoint, (void*)h_storeCheckpoint, (void**)&o_storeCheckpoint);
    ok &= hook(PlayLayer__startGame, (void*)h_startGame, (void**)&o_startGame);
    ok &= hook(PlayLayer__pauseGame, (void*)h_pauseGame, (void**)&o_pauseGame);

    HMODULE cc = GetModuleHandleW(L"libcocos2d.dll");
    void* sched = cc ? (void*)GetProcAddress(cc, "?update@CCScheduler@cocos2d@@UEAAXM@Z") : nullptr;
    MH_STATUS s = sched ? MH_CreateHook(sched, (void*)h_schedUpdate, (void**)&o_schedUpdate) : MH_ERROR_FUNCTION_NOT_FOUND;
    GLOG("hook CCScheduler::update (export): %s", MH_StatusToString(s));
    ok &= (s == MH_OK);
    return ok;
}

}  // namespace gdbot
