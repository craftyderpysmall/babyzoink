"""Which player state does a GD practice checkpoint fail to restore exactly?

Walks a verified solution (build/m5c/<level>.json). At every released segment boundary: checkpoint
`warm` released decisions before it, run warm-up + next segment (true continuation), restore, run the
same inputs again, and compare the final player state field by field.

Usage: python tools/m5c/restore_probe.py --slot 0 --solution build/m5c/main_1.json [--seg 8] [--warm 1]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/m5c"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402
from solver import level_spec  # noqa: E402


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k), b.get(k), f"{path}.{k}" if path else k)
    elif isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or abs(a - b) > 1e-4:
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--solution", type=Path, required=True)
    ap.add_argument("--seg", type=int, default=8)
    ap.add_argument("--warm", type=int, default=0, help="released warm-up decisions between restore and segment")
    a = ap.parse_args()
    sol = json.loads(a.solution.read_text())
    actions = sol["result"]["actions"]
    W, S = a.warm, a.seg
    stats = {"probes": 0, "mismatch": 0, "fields": {}, "warm": W}
    examples = []
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as c:
        c.require_isolated()
        try:
            c.request("quit_level")
        except RemoteError:
            pass
        c.request("set_mode", mode="dedicated")
        c.load_level(level_spec(sol["level"]))
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        c.request("set_practice", enabled=True)
        pos = 0                                       # decisions applied on the true path so far
        for b in range(max(S, W), len(actions) - S + 1, S):
            if actions[b - 1] != 0 or any(actions[b - W:b]) or b - W < pos:
                continue                              # only released boundaries / warm-up
            if b - W > pos:
                c.request("step_seq", episode=ep, actions=actions[pos:b - W], k=4)
            c.request("checkpoint_create")
            probe = actions[b - W:b + S]
            true = c.request("step_seq", episode=ep, actions=probe, k=4)
            ep = c.request("reset", start={"kind": "checkpoint"})["episode"]
            again = c.request("step_seq", episode=ep, actions=probe, k=4)
            c.request("checkpoint_pop")
            pos = b + S
            stats["probes"] += 1
            d = diff({"terminal": true["terminal"], "player": true["player"]},
                     {"terminal": again["terminal"], "player": again["player"]})
            if d:
                stats["mismatch"] += 1
                for path, *_ in d:
                    stats["fields"][path] = stats["fields"].get(path, 0) + 1
                if len(examples) < 10:
                    examples.append({"decision": b, "x": round(true["player"]["x"], 1),
                                     "mode": true["player"].get("mode"), "first_action": actions[b], "diffs": d[:6]})
                ep = c.request("reset", start={"kind": "zero"})["episode"]   # re-sync on the true path
                c.request("set_practice", enabled=True)
                c.request("step_seq", episode=ep, actions=actions[:pos], k=4)
        c.request("quit_level")
        c.request("set_mode", mode="normal")
    print(json.dumps(stats))
    for e in examples:
        print(e)


if __name__ == "__main__":
    main()
