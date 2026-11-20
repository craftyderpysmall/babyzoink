"""Read/modify the *bot's* GD save (CCGameManager.dat in game/2.2091/gdbot[/inst<N>]/save). Never the real save.

GD 2.2 Windows saves: XOR 11 -> URL-safe base64 -> gzip -> plist-like XML.
Usage: python tools/gd_save.py <slot> get                 (list valueKeeper gv_ settings)
       python tools/gd_save.py <slot> set gv_0025 1 [...]  (set gv_ values; GD must not be running in that slot)
       python tools/gd_save.py <slot> root texQuality 1    (set a top-level integer key, e.g. texQuality
                                                            1 low / 2 medium / 3 high; GD closed in that slot)
       python tools/gd_save.py all root texQuality 1       (every existing slot: 0 and each inst<N>)
"""
import base64
import gzip
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gdbot.instances import BOT, owned_pid


def path(slot: int) -> Path:
    if type(slot) is not int or not 0 <= slot <= 63:
        raise ValueError("slot must be an int in 0..63")
    return (BOT if slot == 0 else BOT / f"inst{slot}") / "save" / "CCGameManager.dat"


def load(p: Path) -> str:
    x = bytes(b ^ 11 for b in p.read_bytes()).rstrip(b"\x0b\x00")
    return gzip.decompress(base64.urlsafe_b64decode(x + b"=" * (-len(x) % 4))).decode("utf-8")


def editable_path(slot: int) -> Path:
    p = path(slot)
    if p.resolve(strict=True) != p:
        raise RuntimeError(f"refusing a redirected save path for slot {slot}")
    if owned_pid(slot) is not None:
        raise RuntimeError(f"close the bot game in slot {slot} before editing its save")
    return p


def _atomic_write(target: Path, contents: bytes) -> None:
    file = NamedTemporaryFile(dir=target.parent, prefix=f"{target.name}-", suffix=".tmp", delete=False)
    staging = Path(file.name)
    try:
        with file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def save(slot: int, xml: str) -> None:
    p = editable_path(slot)
    enc = base64.urlsafe_b64encode(gzip.compress(xml.encode("utf-8")))
    _atomic_write(p.with_suffix(".dat.bak"), p.read_bytes())
    editable_path(slot)
    _atomic_write(p, bytes(b ^ 11 for b in enc))


def set_gv(xml: str, key: str, value: str) -> str:
    if re.search(rf"<k>{key}</k><s>[^<]*</s>", xml):
        return re.sub(rf"(<k>{key}</k><s>)[^<]*(</s>)", rf"\g<1>{value}\g<2>", xml)
    return xml.replace("<k>valueKeeper</k><d>", f"<k>valueKeeper</k><d><k>{key}</k><s>{value}</s>", 1)


def set_root_int(xml: str, key: str, value: int) -> str:
    """Set an integer key in the save's root <dict> (GD keeps texQuality etc. there, not in valueKeeper)."""
    pattern = rf"(<k>{key}</k><i>)-?\d+(</i>)"
    if re.search(pattern, xml):
        return re.sub(pattern, rf"\g<1>{value}\g<2>", xml, count=1)
    return xml.replace("<dict>", f"<dict><k>{key}</k><i>{value}</i>", 1)


def slots() -> list:
    return [0] + sorted(int(d.name[4:]) for d in BOT.glob("inst*") if (d / "save" / "CCGameManager.dat").exists())


if __name__ == "__main__":
    slot, cmd, *rest = sys.argv[1:]
    if cmd == "root":
        targets = slots() if slot == "all" else [int(slot)]
        for n in targets:
            editable_path(n)
        for n in targets:
            p = editable_path(n)
            xml = set_root_int(load(p), rest[0], int(rest[1]))
            save(n, xml)
            assert load(p) == xml
            print("saved", p, rest[0], "=", rest[1])
        sys.exit(0)
    n = int(slot)
    p = editable_path(n) if cmd == "set" else path(n)
    xml = load(p)
    if cmd == "get":
        print(re.findall(r"<k>(gv_\d+)</k><s>([^<]*)</s>", xml))
    elif cmd == "set":
        for key, value in zip(rest[::2], rest[1::2]):
            xml = set_gv(xml, key, value)
        save(n, xml)
        assert load(p) == xml
        print("saved", p)
