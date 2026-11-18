"""M0 static verification of the minimal bridge surface.

Reads Windows RVAs for a chosen set of functions from a pinned Geode bindings
file (reference data only, kept in gitignored tools/m0/ref/), then checks each
RVA against the target executable's .pdata (x64 exception directory): every
non-leaf function start in an MSVC x64 binary has a RUNTIME_FUNCTION entry, so
an RVA that is not a .pdata BeginAddress is suspect.

Also lists named exports of companion DLLs we intend to hook by symbol.

Static checks only. Live semantics (breakpoints / hook behaviour) are verified
in M1, inside the injected bridge, before any automated play.

Usage: python -I verify_surface.py <GeometryDash.exe> <GeometryDash.bro> <out.json>
"""
import bisect
import hashlib
import json
import re
import struct
import sys

# (class, method name, why we need it, milestone)
SURFACE = [
    ("GJBaseGameLayer", "update", "frame/tick driver", "M1"),
    ("GJBaseGameLayer", "processCommands", "physics tick boundary (isHalfTick/isLastTick)", "M1"),
    ("GJBaseGameLayer", "handleButton", "press/release injection", "M1"),
    ("PlayLayer", "init", "level entry / attach bridge", "M1"),
    ("PlayLayer", "postUpdate", "post-tick observation point", "M1"),
    ("PlayLayer", "resetLevel", "full reset", "M1"),
    ("PlayLayer", "fullReset", "full reset from 0%", "M1"),
    ("PlayLayer", "destroyPlayer", "terminal event: death", "M1"),
    ("PlayLayer", "levelComplete", "terminal event: completion (must be isolated)", "M1"),
    ("PlayLayer", "onQuit", "detach bridge", "M1"),
    ("PlayLayer", "pauseGame", "suppress auto-pause when unfocused (background mode)", "M1"),
    ("PlayerObject", "update", "player integration step (reference)", "M1"),
    ("GameStatsManager", "completedLevel", "isolation: block completion stats", "M1"),
    ("GameStatsManager", "incrementStat", "isolation: block stat writes", "M1"),
    ("GameLevelManager", "updateUserScore", "isolation: block score upload", "M1"),
    ("PlayLayer", "markCheckpoint", "practice checkpoints", "M4"),
    ("PlayLayer", "storeCheckpoint", "practice checkpoints", "M4"),
    ("PlayLayer", "loadFromCheckpoint", "practice checkpoints", "M4"),
    ("PlayLayer", "removeCheckpoint", "practice checkpoints", "M4"),
    ("GJBaseGameLayer", "loadStartPosObject", "start positions", "M4"),
    ("PlayLayer", "scene", "load_level: create the play scene", "M1"),
    ("PlayLayer", "getCurrentPercent", "obs.progress (reward/metrics only)", "M1"),
    ("PlayLayer", "resetLevelFromStart", "reset reference", "M1"),
    ("GameLevelManager", "sharedState", "load_level: level manager singleton", "M1"),
    ("GameLevelManager", "getMainLevel", "load_level: official level by id", "M1"),
    ("GameObject", "getObjectRect", "obs.objects hitbox", "M1b"),
    ("PlayLayer", "onQuit", "quit_level", "M1b"),
]

COMPANION_EXPORT_PATTERNS = {
    "libcocos2d.dll": [r"getWritablePath", r"CCScheduler@cocos2d@@.*update|update@CCScheduler", r"drawScene@CCDirector",
                       r"setAnimationInterval@CCDirector"],
    "libExtensions.dll": [r"send@CCHttpClient"],
}


def pe_info(path):
    b = open(path, "rb").read()
    e = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, e + 6)[0]
    ts = struct.unpack_from("<I", b, e + 8)[0]
    optsz = struct.unpack_from("<H", b, e + 20)[0]
    opt = e + 24
    assert struct.unpack_from("<H", b, opt)[0] == 0x20B, "not PE32+"
    ddir = opt + 112
    secs = []
    for i in range(nsec):
        s = opt + optsz + 40 * i
        name = b[s:s + 8].rstrip(b"\0").decode()
        vsz, va, rsz, raw = struct.unpack_from("<IIII", b, s + 8)
        secs.append((name, va, vsz, raw, rsz))

    def rva2off(rva):
        for _, va, vsz, raw, rsz in secs:
            if va <= rva < va + max(vsz, rsz):
                return raw + rva - va
        raise ValueError(hex(rva))

    def ddir_entry(i):
        return struct.unpack_from("<II", b, ddir + 8 * i)

    return b, ts, secs, rva2off, ddir_entry


def pdata_starts(path):
    b, ts, secs, rva2off, dd = pe_info(path)
    rva, size = dd(3)  # exception directory
    off = rva2off(rva)
    starts, ends = [], []
    for i in range(size // 12):
        bgn, end, _ = struct.unpack_from("<III", b, off + 12 * i)
        starts.append(bgn)
        ends.append(end)
    return b, ts, secs, starts, ends


def exports(path):
    b, ts, secs, rva2off, dd = pe_info(path)
    rva, size = dd(0)
    off = rva2off(rva)
    n_names, _, names_rva = struct.unpack_from("<I", b, off + 24)[0], 0, struct.unpack_from("<I", b, off + 32)[0]
    out = []
    noff = rva2off(names_rva)
    for i in range(n_names):
        nrva = struct.unpack_from("<I", b, noff + 4 * i)[0]
        o = rva2off(nrva)
        out.append(b[o:b.index(b"\0", o)].decode("latin1"))
    return ts, out


def parse_bro(path):
    """Map (class, method) -> list of (signature, win RVA or 'inline' or None)."""
    cls = None
    depth = 0
    table = {}
    meth_re = re.compile(r"\b([A-Za-z_~][A-Za-z0-9_]*)\s*\(")
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        m = re.match(r"^class\s+([A-Za-z0-9_:]+)", s)
        if m and depth == 0:
            cls = m.group(1)
        if cls and depth >= 1 and "=" in s and "(" in s and not s.startswith("//"):
            head = s.split("=")[0]
            names = meth_re.findall(head)
            if names:
                name = names[-1]
                w = re.search(r"\bwin\s+(0x[0-9a-fA-F]+|inline)", s)
                win = None if not w else (w.group(1) if w.group(1) == "inline" else int(w.group(1), 16))
                if re.search(r"=\s*inline\s*;", s):
                    win = "inline"
                table.setdefault((cls, name), []).append((head.strip(), win))
        depth += line.count("{") - line.count("}")
        if depth == 0:
            cls = None if not m else cls
    return table


def main(exe, bro, out):
    raw, ts, secs, starts, ends = pdata_starts(exe)
    sha = hashlib.sha256(raw).hexdigest()
    table = parse_bro(bro)
    results = []
    for cls, name, why, ms in SURFACE:
        entries = table.get((cls, name), [])
        if not entries:
            results.append(dict(cls=cls, name=name, why=why, milestone=ms, status="MISSING"))
            continue
        for sig, win in entries:
            r = dict(cls=cls, name=name, sig=sig, why=why, milestone=ms)
            if win is None:
                r["status"] = "NO_WIN_ENTRY"
            elif win == "inline":
                r["status"] = "INLINE"
            else:
                i = bisect.bisect_left(starts, win)
                if i < len(starts) and starts[i] == win:
                    r.update(rva=hex(win), status="PDATA_START", size=ends[i] - win)
                else:
                    r.update(rva=hex(win), status="NOT_FUNCTION_START")
            results.append(r)
    companions = {}
    import os
    d = os.path.dirname(exe)
    for dll, pats in COMPANION_EXPORT_PATTERNS.items():
        p = os.path.join(d, dll)
        dts, names = exports(p)
        companions[dll] = dict(
            sha256=hashlib.sha256(open(p, "rb").read()).hexdigest(),
            pe_timestamp=hex(dts),
            matches={pat: [n for n in names if re.search(pat, n)][:6] for pat in pats},
        )
    report = dict(exe=os.path.basename(exe), sha256=sha, pe_timestamp=hex(ts),
                  pdata_functions=len(starts), surface=results, companions=companions)
    json.dump(report, open(out, "w"), indent=2)
    for r in results:
        print(f"{r['status']:<19} {r['milestone']} {r['cls']}::{r['name']:<22} {r.get('rva', '')}")
    for dll, c in companions.items():
        for pat, ms in c["matches"].items():
            print(f"{dll:<18} {pat:<45} {ms[:2]}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
