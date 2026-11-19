"""Download chosen online (custom) levels from GD's servers, outside the game.

The game itself stays offline (the bridge blocks its HTTP). This module fetches a level once, caches
the raw level data plus metadata in levels/online/<id>.json, and returns a protocol `level_string`
spec so it loads like any drill. The site exporter reads the same metadata for difficulty anchors
(non-demon stars); demons are joined with the GDDL cache on the level id.

Usage:  python -m gdbot.levels.online 128 10565740      (download / refresh-skip cached ids)
"""
import argparse
import base64
import gzip
import json
import sys
import time
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "levels" / "online"
ENDPOINT = "https://www.boomlings.com/database/downloadGJLevel22.php"
SECRET = "Wmfd2893gb7"  # GD's public, client-embedded request secret (identical for every player)
MIN_INTERVAL_S = 2.0  # be gentle with RobTop's servers
_last_request = 0.0

# downloadGJLevel22 field numbers (https://wyliemaster.github.io/gddocs/#/resources/server/level)
F_ID, F_NAME, F_DATA, F_VERSION, F_DIFF_NUM, F_DEMON, F_STARS, F_AUTO = "1", "2", "4", "5", "9", "17", "18", "25"
F_DEMON_DIFF, F_LENGTH = "43", "15"
DIFFICULTY = {0: "na", 10: "easy", 20: "normal", 30: "hard", 40: "harder", 50: "insane"}
DEMON = {3: "easy_demon", 4: "medium_demon", 0: "hard_demon", 5: "insane_demon", 6: "extreme_demon"}
LENGTH = {0: "tiny", 1: "short", 2: "medium", 3: "long", 4: "xl", 5: "platformer"}


def parse_response(text: str) -> dict:
    body = text.split("#", 1)[0]
    if not body or body.lstrip("-").isdigit():
        raise LookupError(f"server returned {body or 'nothing'} (level missing, private, or request rejected)")
    parts = body.split(":")
    return {parts[i]: parts[i + 1] for i in range(0, len(parts) - 1, 2)}


def normalize_data(data: str) -> str:
    """Return level data as padded URL-safe base64 gzip (the form drills and the bridge use)."""
    data = data.strip()
    raw = None
    try:
        blob = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_")
        try:
            raw = gzip.decompress(blob)
        except OSError:
            raw = zlib.decompress(blob)
    except (ValueError, zlib.error):
        if data.startswith("k") or ";" in data:  # very old levels store the inner string uncompressed
            raw = data.encode("utf-8")
    if raw is None:
        raise ValueError("unrecognised level data encoding")
    out = __import__("io").BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as archive:
        archive.write(raw)
    return base64.urlsafe_b64encode(out.getvalue()).decode("ascii")


def metadata(fields: dict) -> dict:
    num = int(fields.get(F_DIFF_NUM, 0) or 0)
    demon = fields.get(F_DEMON, "") == "1"
    auto = fields.get(F_AUTO, "") == "1"
    difficulty = DEMON.get(int(fields.get(F_DEMON_DIFF, 0) or 0), "hard_demon") if demon else (
        "auto" if auto else DIFFICULTY.get(num, "na"))
    return {
        "id": int(fields[F_ID]), "name": fields.get(F_NAME, ""), "version": int(fields.get(F_VERSION, 0) or 0),
        "stars": int(fields.get(F_STARS, 0) or 0), "demon": demon, "difficulty": difficulty,
        "length": LENGTH.get(int(fields.get(F_LENGTH, 0) or 0), "unknown"),
        "platformer": int(fields.get(F_LENGTH, 0) or 0) == 5,
    }


def _post(level_id: int, timeout: float) -> str:
    global _last_request
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    body = urllib.parse.urlencode({"levelID": level_id, "secret": SECRET}).encode()
    # GD's servers reject requests that carry a browser/Python User-Agent; the game sends none.
    req = urllib.request.Request(ENDPOINT, data=body, headers={"User-Agent": "", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    finally:
        _last_request = time.monotonic()


def download(level_id: int, *, cache: Path = CACHE, refresh: bool = False, timeout: float = 20.0) -> dict:
    """Fetch (or load from cache) one online level. Returns the cached record."""
    if type(level_id) is not int or level_id <= 0:
        raise ValueError("level id must be a positive int")
    path = cache / f"{level_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    fields = parse_response(_post(level_id, timeout))
    record = {**metadata(fields), "data": normalize_data(fields[F_DATA]),
              "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": ENDPOINT}
    if record["platformer"]:
        raise ValueError(f"level {level_id} is a platformer level (out of scope)")
    cache.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
    tmp.replace(path)
    return record


def level_spec(record: dict) -> dict:
    """Protocol v0 load_level spec for a downloaded level (telemetry key: f"online:{id}")."""
    return {"kind": "level_string", "name": f"online-{record['id']}", "data": record["data"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", type=int, nargs="+")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    for level_id in a.ids:
        try:
            r = download(level_id, refresh=a.refresh)
            print(f"{r['id']}: {r['name']!r} {r['difficulty']} {r['stars']}* {r['length']} ({len(r['data'])} bytes)")
        except (LookupError, ValueError, OSError) as exc:
            print(f"{level_id}: FAILED {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
