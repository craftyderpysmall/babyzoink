"""Build a reproducible M6 training pool from public classic levels and seeded drills."""

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gdbot.levels.drills import M5_NOTES, MODE_PORTALS, build_m5_drill, iter_drills, iter_m5_drills  # noqa: E402
from gdbot.levels.levelstring import decode_level_bytes  # noqa: E402
from gdbot.levels.online import CACHE, FROZEN_M5B_ONLINE_IDS, MIN_INTERVAL_S, SECRET  # noqa: E402
from gdbot.levels.online import download, metadata, parse_response, read_limited  # noqa: E402


SEARCH = "https://www.boomlings.com/database/getGJLevels21.php"
DIFFICULTIES = ("easy", "normal", "hard", "harder", "insane")
LENGTHS = ("short", "medium", "long", "xl")
PER_GROUP = 3


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".tmp")
    staging.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    staging.replace(path)


def search_page(directory, difficulty, length, tab, page=0):
    suffix = f"-{page}" if page else ""
    path = directory / f"{difficulty}-{length}-{tab}{suffix}.json"
    if path.exists():
        with path.open("rb") as cached:
            return json.loads(read_limited(cached))
    params = {
        "type": tab, "str": "", "diff": difficulty, "len": length, "star": 1,
        "page": page, "gameVersion": 22, "binaryVersion": 47, "secret": SECRET,
    }
    request = urllib.request.Request(
        SEARCH, data=urllib.parse.urlencode(params).encode(),
        headers={"User-Agent": "", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = read_limited(response).decode("utf-8", errors="replace")
    finally:
        time.sleep(MIN_INTERVAL_S)
    rows = [
        {**metadata(fields), "game_version": int(fields.get("13", 0) or 0)}
        for item in result.split("#", 1)[0].split("|") if item.startswith("1:")
        for fields in [parse_response(item)]
    ]
    if not rows and result.strip() != "-1":
        raise RuntimeError("unexpected level search response")
    save_json(path, rows)
    return rows


def portal_modes(data):
    _, _, objects = decode_level_bytes(data).decode("utf-8").partition(";")
    ids = set()
    for record in objects.split(";"):
        tokens = record.split(",")
        ids.update(value for key, value in zip(tokens[::2], tokens[1::2]) if key == "1")
    return sorted({"cube", *(mode for mode, obj in MODE_PORTALS.items() if str(obj) in ids)})


def data_hash(data):
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def candidates(directory, difficulty, length):
    popular = search_page(directory, difficulty, length, 1)
    recent = search_page(directory, difficulty, length, 11)
    # Interleave the older-popular and recently rated feeds for each difficulty and length.
    for _, level in sorted([*enumerate(popular), *enumerate(recent)], key=lambda pair: pair[0]):
        yield level
    for tab in (1, 11, 6):
        yield from search_page(directory, difficulty, length, tab, page=int(tab != 6))


def online_pool(output):
    manifest = output / "online-train.json"
    if manifest.exists():
        rows = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        rows = []
    used = set(FROZEN_M5B_ONLINE_IDS)
    digests = {
        data_hash(json.loads((CACHE / f"{level_id}.json").read_text(encoding="utf-8"))["data"])
        for level_id in used
    }
    unique = []
    for row in rows:
        if row["id"] in used or row["sha256"] in digests:
            continue
        unique.append(row)
        used.add(row["id"])
        digests.add(row["sha256"])
    if len(unique) != len(rows):
        save_json(manifest, unique)
    rows = unique
    for difficulty_id, difficulty in enumerate(DIFFICULTIES, 1):
        for length_id, length in enumerate(LENGTHS, 1):
            group = [row for row in rows if (row["difficulty"], row["length"]) == (difficulty, length)]
            if len(group) >= PER_GROUP:
                continue
            for candidate in candidates(output / "search", difficulty_id, length_id):
                level_id = candidate["id"]
                if level_id in used or candidate["demon"] or candidate["platformer"]:
                    continue
                if (candidate["difficulty"], candidate["length"]) != (difficulty, length):
                    continue
                used.add(level_id)
                try:
                    record = download(level_id, cache=output / "online")
                    modes = portal_modes(record["data"])
                except (LookupError, ValueError) as exc:
                    print(f"skip {level_id}: {exc}", flush=True)
                    continue
                digest = data_hash(record["data"])
                if digest in digests or record["demon"] or (record["difficulty"], record["length"]) != (difficulty, length):
                    continue
                digests.add(digest)
                row = {key: value for key, value in record.items() if key != "data"}
                row.update(game_version=candidate["game_version"], modes=modes, sha256=digest)
                group.append(row)
                rows.append(row)
                save_json(manifest, rows)
                print(f"{len(rows)}/60 {difficulty} {length}: {level_id} {row['name']}", flush=True)
                if len(group) == PER_GROUP:
                    break
            if len(group) < PER_GROUP:
                print(f"only {len(group)} eligible levels found for {difficulty}/{length}", flush=True)
    return rows


def drill_pool(output):
    extra = (build_m5_drill(family, "train", base + i)
             for base in (8100, 9100) for i, family in enumerate(M5_NOTES))
    rows = []
    for drill in (*iter_drills(), *iter_m5_drills(), *extra):
        if drill.split != "train":
            continue
        data = drill.level.encode()
        path = output / "drills" / drill.family / f"{drill.variant}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="ascii")
        rows.append({"family": drill.family, "variant": drill.variant, "seed": drill.seed,
                     "path": path.relative_to(output).as_posix(),
                     "sha256": data_hash(data)})
    save_json(output / "drills-train.json", rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/m6-scale")
    parser.add_argument("--drills-only", action="store_true")
    args = parser.parse_args()
    drills = drill_pool(args.output)
    print(f"{len(drills)} train drills across {len({row['family'] for row in drills})} families", flush=True)
    if not args.drills_only:
        levels = online_pool(args.output)
        print(f"{len(levels)} online levels, modes: {dict(Counter(mode for row in levels for mode in row['modes']))}")
