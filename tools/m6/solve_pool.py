"""Run the search teacher on disjoint shards of the frozen M6 training manifests."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

from pool import ROOT, save_json

sys.path.insert(0, str(ROOT / "tools/m5c"))
from solver import Solver  # noqa: E402
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402


def levels(pool, split):
    for row in json.loads((pool / f"{split}-train.json").read_text(encoding="utf-8")):
        if split == "online":
            key = f"online:{row['id']}"
            record = json.loads((pool / "online" / f"{row['id']}.json").read_text(encoding="utf-8"))
            data = record["data"]
            name = row["name"]
        else:
            key = f"drill:{row['family']}/{row['variant']}"
            data = (pool / row["path"]).read_text(encoding="ascii")
            name = f"{row['family']}-{row['variant']}"
        if hashlib.sha256(data.encode("ascii")).hexdigest() != row["sha256"]:
            raise RuntimeError(f"training level {key} differs from its manifest")
        yield key, name, row["sha256"], {"kind": "level_string", "name": name, "data": data}


def run(pool, split, slot, shard, shards, budget, limit, look, present_every_ms):
    directory = pool / "solutions"
    directory.mkdir(parents=True, exist_ok=True)
    attempted = 0
    with BridgeClient(NamedPipeTransport(discovery(slot)["pipe"])) as client:
        hello = client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        draw_skip = present_every_ms > 0 and hello.get("capabilities", {}).get("set_render")
        try:
            for index, (key, name, digest, spec) in enumerate(levels(pool, split)):
                if index % shards != shard:
                    continue
                path = directory / f"{key.replace(':', '_').replace('/', '_')}.json"
                prior = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                if prior and prior["sha256"] != digest:
                    raise RuntimeError(f"search state for {key} is from a different version")
                if prior.get("verified") or prior.get("budget", 0) >= budget:
                    continue
                attempted += 1
                print(f"{key} {name}:", flush=True)
                solver = Solver(client, spec, budget=budget, look=look, progress=path.with_suffix(".progress.json"),
                                log=lambda message: print(message, flush=True))
                solver.verification_attempts = prior.get("normal_attempts", 0)
                started = perf_counter()
                if draw_skip:
                    # Scene transitions need normal frames. The solver reuses the loaded level.
                    client.load_level(spec)
                    client.request("set_render", present_every_ms=present_every_ms)
                result = solver.solve()
                solver.save_progress()
                report = {
                    "level": key, "name": name, "sha256": digest, "budget": budget,
                    "lookahead": look,
                    "verified": bool(result and result["verified"]), "result": result,
                    "practice_attempts": solver.evals,
                    "normal_attempts": solver.verification_attempts,
                    "wall_s": round(prior.get("wall_s", 0.0) + perf_counter() - started, 2),
                }
                save_json(path, report)
                if draw_skip:
                    client.request("set_render", present_every_ms=0)
                client.request("quit_level")
                print(f"  verified={report['verified']}, evaluations={solver.evals}", flush=True)
                if attempted == limit:
                    break
        finally:
            client.request("set_mode", mode="normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=ROOT / "build/m6-scale")
    parser.add_argument("--split", choices=("drills", "online"), required=True)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--budget", type=int, default=20_000)
    parser.add_argument("--look", type=int, default=28, help="lookahead in four-tick decisions")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many newly attempted levels")
    parser.add_argument("--present-every-ms", type=int, default=0,
                        help="limit game rendering to this interval on supported bridges")
    args = parser.parse_args()
    if not 0 <= args.shard < args.shards or min(args.budget, args.look) <= 0 or min(args.limit, args.present_every_ms) < 0:
        parser.error("invalid shard, budget, lookahead, limit or render interval")
    run(args.pool, args.split, args.slot, args.shard, args.shards, args.budget, args.limit, args.look, args.present_every_ms)
