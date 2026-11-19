"""M8 CBF smoke test on a live slot (new bridge with capability `cbf`).

1. hello reports cbf; reset reports vanilla Click Between Steps / Click On Steps off.
2. Parity: the verified Stereo Madness clear (no fracs) completes on the same tick as before; explicit
   all-zero fracs give the identical end tick.
3. Validation: a fraction outside [0, 1) or a wrong-length fracs array is refused before physics moves.
4. Onset shift: from the same grounded state, a jump pressed at fraction f of a step. After the press tick,
   the later the press, the less of the jump has happened: y after the first ticks must fall as f rises,
   and the trajectory should match f=0 shifted by about f ticks.

Usage: python tools/m8/cbf_smoke.py --slot 3
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402


def jump_trace(c, f, settle=60, ticks=24):
    ep = c.request("reset", start={"kind": "zero"})["episode"]
    c.request("step_seq", episode=ep, actions=[0] * settle, k=1)
    ys = []
    r = c.request("step", episode=ep, action=1, k=1, frac=f)
    ys.append(r["obs"]["players"][0]["y"])
    for _ in range(ticks - 1):
        r = c.request("step", episode=ep, action=1, k=1)
        ys.append(r["obs"]["players"][0]["y"])
    return ys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    a = ap.parse_args()
    sol = json.loads((ROOT / "build/m5c/main_1.json").read_text(encoding="utf-8"))["result"]
    actions, k = sol["actions"], sol["k"]
    results = []
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as c:
        hello = c.require_isolated()
        results.append(("hello: cbf capability", bool(hello["capabilities"].get("cbf")), hello["capabilities"].get("cbf")))
        try:
            c.request("quit_level")
        except RemoteError:
            pass
        c.request("set_mode", mode="dedicated")
        c.load_level({"kind": "main", "id": 1})
        rr = c.request("reset", start={"kind": "zero"})
        it = rr.get("input_timing", {})
        results.append(("reset: vanilla click-between/on-steps off", it.get("cbf") and not it.get("click_between_steps")
                        and not it.get("click_on_steps"), it))
        r = c.request("step_seq", episode=rr["episode"], actions=actions, k=k)
        end = r["tick"]
        results.append(("parity: verified clear completes, no fracs", r["terminal"] == "complete" and end == 20332,
                        f"{r['terminal']} at tick {end} (pre-CBF build: complete at 20332)"))
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        r = c.request("step_seq", episode=ep, actions=actions, k=k, fracs=[0.0] * len(actions))
        results.append(("parity: explicit zero fracs identical", r["terminal"] == "complete" and r["tick"] == end,
                        f"{r['terminal']} at tick {r['tick']}"))
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        bad = []
        for fr in ([1.0], [-0.1], [0.5, 0.5]):
            try:
                c.request("step_seq", episode=ep, actions=[1], k=1, fracs=fr)
                bad.append(f"{fr} accepted")
            except RemoteError:
                pass
        tick_after = c.request("step", episode=ep, action=0, k=1)["tick"]
        results.append(("validation: bad fracs refused before physics", not bad and tick_after == 1,
                        "; ".join(bad) or f"all refused; next step reached tick {tick_after}"))
        traces = {f: jump_trace(c, f) for f in (0.0, 0.25, 0.5, 0.75)}
        first = {f: round(t[0], 3) for f, t in traces.items()}
        mono = traces[0.0][0] > traces[0.25][0] > traces[0.5][0] > traces[0.75][0]
        results.append(("onset shift: later press = less jump after the press tick", mono, first))
        # shift check: y_f(t) ~ y_0(t - f): compare f=0.5 at tick n with the mean of f=0 at ticks n-1 and n
        y0, yh = traces[0.0], traces[0.5]
        err = max(abs(yh[n] - (y0[n - 1] + y0[n]) / 2) for n in range(2, 12))
        rise = max(abs(y0[n] - y0[n - 1]) for n in range(2, 12))
        results.append(("onset shift ~ f ticks (f=0.5 vs midpoint of f=0)", err < 0.35 * rise,
                        f"max deviation {err:.3f} vs per-tick rise {rise:.3f}"))
        c.request("quit_level")
    ok = 0
    for name, passed, detail in results:
        ok += bool(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
