"""M1 unattended live test against the real bridge (protocol v0), via gdbot.protocol.BridgeClient.

Checks, each printed as PASS/FAIL with evidence:
  1. hello: protocol 0, build hash, isolation flags true
  2. load_level main 1 (Stereo Madness) through the mod, no manual clicks
  3. reset -> episode 1, tick 0, player alive near the start
  4. freeze: with no step requests for 1 s, tick and x do not change
  5. k=1 stepping: every step advances exactly one tick; x advances ~1.298/tick
  6. injected press: vy = 11.18 on the press tick, y rises, on_ground clears
  7. death: holding still until a hazard ends the episode with terminal="death", dead=true
  8. reset after death -> new episode, alive, x back at the start
  9. determinism (mini parity): the same input tape twice from reset gives identical per-tick traces
 10. k=4 stepping and dedicated-mode throughput (steps/s and ticks/s)
Screenshots of the GD window go to game/2.2091/gdbot/m1_screens/.

Usage (GD must be running through gdbot-launch): python -I tools/m1/live_test.py
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

BOT = os.path.join(ROOT, "game", "2.2091", "gdbot")
SHOTS = os.path.join(BOT, "m1_screens")
results = []


def check(name, cond, evidence):
    results.append((name, bool(cond), evidence))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {evidence}", flush=True)


def shot(pid, label):
    os.makedirs(SHOTS, exist_ok=True)
    out = os.path.join(SHOTS, f"{len(os.listdir(SHOTS)):02d}_{label}.png")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        os.path.join(ROOT, "tools", "m1", "screenshot.ps1"), "-ProcessId", str(pid), "-Out", out],
                       capture_output=True, text=True)
    print("   screenshot:", (r.stdout or r.stderr).strip())


def p0(reply):
    return reply["obs"]["players"][0]


def main():
    info = json.load(open(os.path.join(BOT, "bridge.json")))
    pid = info["pid"]
    c = BridgeClient(NamedPipeTransport(info["pipe"]))

    h = c.require_isolated()
    check("1 hello", h["proto"] == 0 and h["build"]["game_version"] == "2.2091",
          f"build={h['build']['exe_sha256'][:16]} isolation={h['isolation']} caps={h['capabilities']}")

    t = time.time()
    lv = c.request("load_level", level={"kind": "main", "id": 1})
    check("2 load_level", lv["ok"], f"{lv['level']} in {time.time() - t:.1f}s")

    r = c.request("reset", start={"kind": "zero"})
    pl = p0(r)
    check("3 reset", r["episode"] == 1 and r["tick"] == 0 and not pl["dead"],
          f"episode={r['episode']} tick={r['tick']} x={pl['x']:.2f} y={pl['y']:.2f} mode={pl['mode']}")
    ep, tick = r["episode"], r["tick"]
    shot(pid, "after_reset")

    # 4 freeze
    s1 = c.step(episode=ep, tick=tick, action=0, k=1); tick = s1["tick"]
    x1 = p0(s1)["x"]
    time.sleep(1.0)
    s2 = c.step(episode=ep, tick=tick, action=0, k=1); tick = s2["tick"]
    check("4 frozen between requests", s2["ticks_advanced"] == 1 and abs(p0(s2)["x"] - x1) < 2.0,
          f"after 1 s idle: tick {s1['tick']}->{s2['tick']}, x {x1:.3f}->{p0(s2)['x']:.3f}")

    # 5 k=1 stepping
    xs, adv = [], []
    for _ in range(60):
        s = c.step(episode=ep, tick=tick, action=0, k=1); tick = s["tick"]
        xs.append(p0(s)["x"]); adv.append(s["ticks_advanced"])
    dx = [b - a for a, b in zip(xs, xs[1:])]
    check("5 k=1 stepping", all(a == 1 for a in adv) and all(abs(d - 1.2982) < 0.01 for d in dx[20:]),
          f"advanced={set(adv)} dx/tick last={dx[-1]:.4f} (expect 1.2982 at 1x speed) x={xs[-1]:.2f}")

    # 6 press
    before = p0(s)
    s = c.step(episode=ep, tick=tick, action=1, k=1); tick = s["tick"]
    first = p0(s)
    rows = [first]
    for _ in range(12):
        s = c.step(episode=ep, tick=tick, action=1, k=1); tick = s["tick"]
        rows.append(p0(s))
    shot(pid, "mid_jump")
    s = c.step(episode=ep, tick=tick, action=0, k=1); tick = s["tick"]
    vys = [round(q["vy"], 3) for q in rows[:4]]
    # Observations are post-tick: on the press tick vy=11.18 is set and one tick of gravity (-0.216)
    # is applied before we read it, so the first post-step value is 10.964.
    check("6 injected press", abs(vys[0] - (11.18 - 0.216)) < 0.01 and rows[-1]["y"] > before["y"] + 10
          and not rows[2]["on_ground"],
          f"y {before['y']:.2f}->{rows[-1]['y']:.2f}, vy first ticks {vys}, on_ground {before['on_ground']}->{rows[2]['on_ground']}")

    # 7 death: hold still until the first spike kills us
    death = None
    for _ in range(2000):
        s = c.step(episode=ep, tick=tick, action=0, k=4); tick = s["tick"]
        if s["terminal"]:
            death = s
            break
    shot(pid, "after_death")
    check("7 death terminal", death is not None and death["terminal"] == "death" and p0(death)["dead"],
          f"terminal={death and death['terminal']} at tick {death and death['tick']} x={death and round(p0(death)['x'], 2)}"
          f" events={death and death['events']} advanced={death and death['ticks_advanced']}")

    # 8 reset after death
    r = c.request("reset", start={"kind": "zero"})
    check("8 reset after death", r["episode"] == ep + 1 and not p0(r)["dead"] and p0(r)["x"] < 50,
          f"episode={r['episode']} x={p0(r)['x']:.2f} dead={p0(r)['dead']}")

    # 9 determinism: same tape twice
    tape = [0] * 100 + [1] * 18 + [0] * 140 + [1] * 10 + [0] * 200
    traces = []
    for run in range(2):
        r = c.request("reset", start={"kind": "zero"})
        ep, tick = r["episode"], r["tick"]
        c.request("trace", enabled=True)
        rows = []
        for a in tape:
            s = c.step(episode=ep, tick=tick, action=a, k=1); tick = s["tick"]
            rows += [(row["tick"], round(row["players"][0]["x"], 4), round(row["players"][0]["y"], 4),
                      round(row["players"][0]["vy"], 4)) for row in s.get("trace", [])]
            if s["terminal"]:
                rows.append(("terminal", s["terminal"], s["tick"]))
                break
        c.request("trace", enabled=False)
        traces.append(rows)
    first_div = next((i for i, (a, b) in enumerate(zip(*traces)) if a != b), None)
    same = traces[0] == traces[1]
    check("9 same tape twice -> identical trace", same,
          f"{len(traces[0])} rows; first divergence at row {first_div}"
          + ("" if same or first_div is None else f": {traces[0][first_div]} vs {traces[1][first_div]}"))

    # 10 throughput
    for mode in ("normal", "dedicated"):
        c.request("set_mode", mode=mode)
        for k in (1, 4):
            r = c.request("reset", start={"kind": "zero"})
            ep, tick = r["episode"], r["tick"]
            n, t0, ticks = 0, time.perf_counter(), 0
            while time.perf_counter() - t0 < 3.0:
                s = c.step(episode=ep, tick=tick, action=(n // 40) % 2, k=k); tick = s["tick"]
                n += 1; ticks += s["ticks_advanced"]
                if s["terminal"]:
                    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
            el = time.perf_counter() - t0
            check(f"10 throughput {mode} k={k}", True,
                  f"{n / el:.0f} steps/s, {ticks / el:.0f} ticks/s ({ticks / el / 240:.1f}x real time)")
    c.request("set_mode", mode="normal")
    c.close()

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    json.dump([dict(name=n, ok=o, evidence=e) for n, o, e in results],
              open(os.path.join(BOT, "m1_live_test.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
