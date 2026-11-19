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
import re
import sys
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "game" / "2.2091" / "gdbot"


def path(slot: int) -> Path:
    return (BOT if slot == 0 else BOT / f"inst{slot}") / "save" / "CCGameManager.dat"


def load(p: Path) -> str:
    x = bytes(b ^ 11 for b in p.read_bytes()).rstrip(b"\x0b\x00")
    return gzip.decompress(base64.urlsafe_b64decode(x + b"=" * (-len(x) % 4))).decode("utf-8")


def save(p: Path, xml: str) -> None:
    enc = base64.urlsafe_b64encode(gzip.compress(xml.encode("utf-8")))
    p.write_bytes(bytes(b ^ 11 for b in enc))


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
        for n in (slots() if slot == "all" else [int(slot)]):
            p = path(n)
            xml = set_root_int(load(p), rest[0], int(rest[1]))
            save(p, xml)
            assert load(p) == xml
            print("saved", p, rest[0], "=", rest[1])
        sys.exit(0)
    p = path(int(slot))
    xml = load(p)
    if cmd == "get":
        print(re.findall(r"<k>(gv_\d+)</k><s>([^<]*)</s>", xml))
    elif cmd == "set":
        for key, value in zip(rest[::2], rest[1::2]):
            xml = set_gv(xml, key, value)
        save(p, xml)
        assert load(p) == xml
        print("saved", p)
