"""M1b live test: object extraction, quit_level, level_string loading (protocol v0 additions).

Checks:
  1. load main 1, reset: objects reported, the bridge log says the layout check passed
  2. the first hazard ahead sits where the M1 test died (player x 1020.4 at death)
  3. categories look sane for Stereo Madness (solids + hazards present, ship portal present further on)
  4. quit_level returns to the menu; load_level works again afterwards
  5. level_string: a tiny original test level (floor + one spike) loads, the spike is reported, and
     holding still dies at it
  6. throughput with objects on (dedicated, k=1 and k=4)

Usage (GD running through gdbot-launch, RUNTIME claimed): python -I tools/m1/objects_test.py
"""
import base64
import gzip
import json
import os
import sys
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

BOT = os.path.join(ROOT, "game", "2.2091", "gdbot")
results = []


def check(name, cond, evidence):
    results.append((name, bool(cond), evidence))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {evidence}", flush=True)


def encode_level(inner: str) -> str:
    return base64.urlsafe_b64encode(gzip.compress(inner.encode())).decode()


def run_until_terminal(c, ep, tick, k=4, limit=4000):
    for _ in range(limit):
        s = c.step(episode=ep, tick=tick, action=0, k=k)
        tick = s["tick"]
        if s["terminal"]:
            return s
    return None


def main():
    info = json.load(open(os.path.join(BOT, "bridge.json")))
    c = BridgeClient(NamedPipeTransport(info["pipe"]))
    h = c.require_isolated()
    check("0 hello caps", h["capabilities"].get("objects") and h["capabilities"].get("level_string"),
          f"caps={h['capabilities']}")

    c.request("load_level", level={"kind": "main", "id": 1})
    r = c.request("reset", start={"kind": "zero"})
    # the first reset in a process may still list GD's anticheat spike (its layer offset is learned on the
    # first ticks); step a little and reset again so the check sees the steady state.
    for _ in range(20):
        r2 = c.step(episode=r["episode"], tick=r["tick"], action=0, k=1); r["tick"] = r2["tick"]
    r = c.request("reset", start={"kind": "zero"})
    objs = r["obs"]["objects"]
    unsup = r["obs"]["unsupported"]
    check("1 objects reported", objs and "objects" not in unsup,
          f"{len(objs)} objects in window, truncated={r['obs']['window']['truncated']}, unsupported={unsup}")
    cats = Counter(o["cat"] for o in objs)
    hz = sorted((o for o in objs if o["cat"] == "hazard"), key=lambda o: o["x"])
    first = hz[0] if hz else None
    check("2 first hazard is the idle-death spike", first and 515 < first["x"] < 535,  # idle cube dies at x=507.6 (verified twice)
          f"first hazard {first and {k: first[k] for k in ('x', 'y', 'w', 'h', 'type_id', 'uid')}} "
          f"(idle death x=507.6); window cats={dict(cats)}")

    # walk forward with a few jumps to see more categories (ship portal ~ x 4300+)
    ep, tick = r["episode"], r["tick"]
    seen = Counter()
    ids = Counter()
    for i in range(4000):
        s = c.step(episode=ep, tick=tick, action=0, k=8)
        tick = s["tick"]
        for o in s["obs"]["objects"]:
            seen[o["cat"]] += 1
            ids[(o["cat"], o["type_id"])] += 1
        if s["terminal"]:
            break
    check("3 categories", seen.get("solid") and seen.get("hazard"),
          f"category sightings until first death: {dict(seen)}; top ids {ids.most_common(8)}")

    t = time.time()
    q = c.request("quit_level")
    lv = c.request("load_level", level={"kind": "main", "id": 1})
    r = c.request("reset", start={"kind": "zero"})
    check("4 quit_level + reload", q["ok"] and lv["ok"] and r["episode"] > ep,
          f"quit+reload in {time.time() - t:.1f}s, episode {r['episode']}")
    c.request("quit_level")

    # Our own minimal test level: one spike on the floor, 20 blocks ahead. Object id 8 = spike.
    inner = "kA2,0,kA4,0;1,8,2,615,3,15;"
    lv = c.request("load_level", level={"kind": "level_string", "name": "m1b-one-spike", "data": encode_level(inner)})
    r = c.request("reset", start={"kind": "zero"})
    hz = [o for o in r["obs"]["objects"] if o["cat"] == "hazard"]
    d = run_until_terminal(c, r["episode"], r["tick"], k=1)
    px = d and d["obs"]["players"][0]["x"]
    check("5 level_string load + spike + death", lv["ok"] and len(hz) == 1 and d and d["terminal"] == "death"
          and 560 < px < 620,
          f"level={lv['level']} hazards={[(round(o['x'], 1), round(o['w'], 1), o['type_id']) for o in hz]} "
          f"death={d and d['terminal']} at x={px and round(px, 1)}")
    c.request("quit_level")

    c.request("load_level", level={"kind": "main", "id": 1})
    # 7 hold/release state + immediate first step after load (Codex M2 findings)
    r = c.request("reset", start={"kind": "zero"})
    ep, tick = r["episode"], r["tick"]
    s0 = c.step(episode=ep, tick=tick, action=0, k=1); tick = s0["tick"]
    seq = []
    for a in [1, 1, 1, 0, 0, 1, 0]:
        s = c.step(episode=ep, tick=tick, action=a, k=4); tick = s["tick"]
        seq.append((a, s["obs"]["players"][0]["holding"]))
    vxs = [s["obs"]["players"][0]["vx"]]
    check("7 holding mirrors action; first step after load advances", s0["ticks_advanced"] == 1
          and all(bool(a) == h for a, h in seq),
          f"first step advanced {s0['ticks_advanced']}; (action, holding)={seq}; vx={vxs}")
    c.request("set_mode", mode="dedicated")
    for k in (1, 4):
        r = c.request("reset", start={"kind": "zero"})
        ep, tick = r["episode"], r["tick"]
        n, ticks, t0 = 0, 0, time.perf_counter()
        while time.perf_counter() - t0 < 3.0:
            s = c.step(episode=ep, tick=tick, action=(n // 40) % 2, k=k)
            tick = s["tick"]; n += 1; ticks += s["ticks_advanced"]
            if s["terminal"]:
                r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
        el = time.perf_counter() - t0
        check(f"6 throughput with objects k={k}", True,
              f"{n / el:.0f} steps/s, {ticks / el:.0f} ticks/s ({ticks / el / 240:.1f}x real time)")
    c.request("set_mode", mode="normal")
    c.close()
    print(f"\n{sum(o for _, o, _ in results)}/{len(results)} checks passed")
    json.dump([dict(name=n, ok=o, evidence=e) for n, o, e in results],
              open(os.path.join(BOT, "m1b_objects_test.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
