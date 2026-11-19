"""Why does no agent clear triple spike? Scan single-press timing at k=4 and compare with BC's press.

Usage: python tools/m3/triple_spike.py --pid <launcher GD pid> --output build/m3-triple
"""
import argparse
import json
from pathlib import Path

from stable_baselines3 import PPO

from baseline import ROOT, DrillEnv
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from scale import scaled_fixtures
from gdbot.levels.levelstring import LevelString


def run_pressed(env, fixture, press_decisions, stop_x):
    """Press for the given decision indices; return (terminal, end_x, peak_y) once past stop_x or dead."""
    env.select(fixture)
    env.reset(seed=0)
    d = 0
    while True:
        _, _, term, trunc, info = env.step(1 if d in press_decisions else 0)
        p = env.raw_observation["players"][0]
        d += 1
        if term or trunc or p["x"] > stop_x:
            return info["terminal"] if (term or trunc) else "past", p["x"], d


def bc_trace(env, fixture, model, stop_x):
    env.select(fixture)
    obs, _ = env.reset(seed=0)
    presses, d = [], 0
    while True:
        a, _ = model.predict(obs, deterministic=True)
        a = int(a)
        if a:
            presses.append((d, round(env.raw_observation["players"][0]["x"], 1)))
        obs, _, term, trunc, info = env.step(a)
        d += 1
        p = env.raw_observation["players"][0]
        if term or trunc or p["x"] > stop_x:
            return presses, info["terminal"], p["x"]


def main(pid, output):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    assert discovery["pid"] == pid
    output.mkdir(parents=True, exist_ok=True)
    pools, _ = scaled_fixtures()
    fixtures = {f"{s}:{f.variant}": f for s in pools for f in pools[s] if f.family == "triple-spike"}
    report = {}
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        env = DrillEnv(client, "topk")
        for name, fx in fixtures.items():
            first = min(float(o["2"]) for o in LevelString.decode(fx.level["data"]).objects if o["1"] == "8")
            stop = first + 200
            rows = []
            for d in range(40, 140):
                for hold in (1, 2):
                    term, x, _ = run_pressed(env, fx, set(range(d, d + hold)), stop)
                    rows.append({"decision": d, "hold": hold, "terminal": term, "end_x": round(x, 1)})
            ok = [r for r in rows if r["terminal"] == "past"]
            entry = {"first_spike_x": first, "clearing": ok, "scanned": len(rows)}
            for seed in (1207, 2357, 3907):
                zp = ROOT / f"build/m3-imitation/topk-{seed}-bc.zip"
                if zp.exists():
                    model = PPO.load(zp, device="cpu")
                    entry[f"bc_{seed}"] = bc_trace(env, fx, model, stop)
            report[name] = entry
            print(name, "first spike", first, "clearing", [(r["decision"], r["hold"]) for r in ok],
                  {k: v for k, v in entry.items() if k.startswith("bc_")}, flush=True)
        env.leave()
        client.request("set_mode", mode="normal")
    (output / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    main(a.pid, a.output)
