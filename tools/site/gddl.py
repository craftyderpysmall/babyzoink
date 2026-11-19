"""Local, static snapshots of public GDDL level difficulty ratings."""

import json
import math
from datetime import datetime, timezone
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_URL = "https://gdladder.com/api"
COOLDOWN_SECONDS = 1.5


def read_cache(path):
    if not path.exists():
        return {"api_version": None, "version_checked_at": None, "levels": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def read_api(path):
    request = Request(ROOT_URL + path, headers={"User-Agent": "Babyzoink difficulty dashboard", "Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def cache_update(path, ids, *, refresh=False, fetch=read_api):
    cache = read_cache(path)
    errors = []
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        cache["api_version"] = fetch("/version").strip().strip('"')
        cache["version_checked_at"] = checked_at
    except (OSError, ValueError) as exc:
        errors.append(f"version: {exc}")
    for level_id in sorted(set(ids)):
        if str(level_id) in cache["levels"] and not refresh:
            continue
        sleep(COOLDOWN_SECONDS)
        try:
            raw = json.loads(fetch(f"/levels/{level_id}"))
            if raw["ID"] != level_id:
                raise ValueError("response level ID did not match")
            rating = raw["Rating"]
            if rating is not None and (type(rating) not in (int, float) or not math.isfinite(rating) or rating < 1):
                raise ValueError("unexpected rating")
            cache["levels"][str(level_id)] = {
                "rating": rating, "rating_count": raw.get("RatingCount"),
                "name": raw.get("Meta", {}).get("Name"), "fetched_at": checked_at,
                "api_version": cache["api_version"],
            }
        except HTTPError as exc:
            errors.append(f"level {level_id}: HTTP {exc.code}")
            if exc.code == 429:
                break
        except (KeyError, OSError, URLError, TypeError, ValueError) as exc:
            errors.append(f"level {level_id}: {exc}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return cache, errors
