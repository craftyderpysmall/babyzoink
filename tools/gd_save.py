"""Read/modify the *bot's* GD save (CCGameManager.dat in game/2.2091/gdbot[/inst<N>]/save). Never the real save.

GD 2.2 Windows saves: XOR 11 -> URL-safe base64 -> gzip -> plist-like XML.
Usage: python tools/gd_save.py <slot> get                 (list valueKeeper gv_ settings)
       python tools/gd_save.py <slot> set gv_0025 1 [...]  (set gv_ values; GD must not be running in that slot)
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


if __name__ == "__main__":
    slot, cmd, *rest = sys.argv[1:]
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
