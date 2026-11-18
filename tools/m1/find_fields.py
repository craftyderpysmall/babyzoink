"""Offline field discovery from gdbot\\probe.bin (written by the M1 probe build).

Each record: 'GDPR', u32 attempt, i64 tick_since_reset, u8 last, u8 held, 2 pad, f32 dt,
then 0x2000 bytes of PlayerObject memory, captured right after processCommands for that tick.

Finds candidate offsets by behaviour (not by guessing layouts):
  m_isDead      byte 0 during play, 1 from the death tick until the next reset
  m_isOnGround  byte that is 1 most of the time and drops to 0 shortly after presses
  m_yVelocity   double, ~0 on ground, jumps positive after a press, then decreases steadily
  m_position    float pair (or double) whose x rises at a near-constant rate while alive
  m_isShip      byte 0 early in the attempt and 1 for a later stretch (ship section)

Usage: python -I tools/m1/find_fields.py game/2.2091/gdbot/probe.bin
"""
import struct
import sys

import numpy as np

HDR = 32
BODY = 0x2000


def load(path):
    raw = open(path, "rb").read()
    rec = HDR + BODY
    n = len(raw) // rec
    a = np.frombuffer(raw[: n * rec], dtype=np.uint8).reshape(n, rec)
    assert (a[:, :4] == np.frombuffer(b"GDPR", np.uint8)).all(), "bad magic"
    attempt = a[:, 4:8].copy().view("<u4")[:, 0]
    tick = a[:, 8:16].copy().view("<i8")[:, 0]
    held = a[:, 17].astype(bool)
    body = a[:, HDR:]
    return attempt, tick, held, body


def as_type(body, off, dt):
    size = np.dtype(dt).itemsize
    return body[:, off: off + size].copy().view(dt)[:, 0]


def segments(attempt):
    out = []
    start = 0
    for i in range(1, len(attempt) + 1):
        if i == len(attempt) or attempt[i] != attempt[start]:
            out.append((start, i))
            start = i
    return out


def main(path):
    attempt, tick, held, body = load(path)
    segs = [s for s in segments(attempt) if s[1] - s[0] > 60]
    print(f"{len(tick)} ticks, {len(segs)} attempts (>60 ticks): " + ", ".join(str(b - a) for a, b in segs))
    press = np.zeros(len(held), bool)
    press[1:] = held[1:] & ~held[:-1]

    # --- m_isDead: byte that is 0 at segment start and 1 at segment end (death), for most segments
    print("\n[m_isDead candidates] byte 0 at attempt start, flips to 1 once, stays 1 until the attempt ends")
    dead_c = []
    for off in range(BODY):
        b = body[:, off]
        if not np.isin(b, (0, 1)).all():
            continue
        ok = 0
        for s, e in segs:
            seg = b[s:e]
            if seg[0] != 0 or seg[-1] != 1:
                continue
            first = int(np.argmax(seg == 1))
            if (seg[first:] == 1).all() and (e - s - first) < 600:
                ok += 1
        if ok >= max(1, len(segs) - 1):
            dead_c.append((off, ok))
    for off, ok in dead_c[:12]:
        print(f"  +0x{off:04x}  matches {ok}/{len(segs)} attempts")

    # --- m_yVelocity: double, bounded, positive spikes within 4 ticks after presses
    print("\n[m_yVelocity candidates] double; rises within 4 ticks of a press; finite, bounded")
    vel_c = []
    idx = np.where(press)[0]
    for off in range(0, BODY - 7, 4):
        v = as_type(body, off, "<f8")
        if not np.isfinite(v).all() or np.abs(v).max() > 1e4 or np.abs(v).max() < 1:
            continue
        if len(idx) < 3:
            break
        rises = sum(1 for i in idx if i + 4 < len(v) and v[i: i + 5].max() - v[max(i - 1, 0)] > 3)
        score = rises / len(idx)
        if score > 0.6:
            vel_c.append((score, off, float(v.min()), float(v.max())))
    for score, off, lo, hi in sorted(vel_c, reverse=True)[:10]:
        print(f"  +0x{off:04x}  press->rise {score:.2f}  range [{lo:.2f}, {hi:.2f}]")

    # --- position x: float or double, strictly increasing within long segments at ~constant step
    print("\n[position x candidates] value increases every tick while alive at a near-constant rate")
    pos_c = []
    for dt, step in (("<f4", 4), ("<f8", 8)):
        for off in range(0, BODY - step + 1, 4):
            v = as_type(body, off, dt).astype(np.float64)
            if not np.isfinite(v).all():
                continue
            good = 0
            rates = []
            for s, e in segs:
                d = np.diff(v[s:e][:240])
                if len(d) > 30 and (d > 0).mean() > 0.95 and d.std() < 0.1 * max(abs(d.mean()), 1e-9):
                    good += 1
                    rates.append(d.mean())
            if good >= max(1, len(segs) - 1):
                pos_c.append((off, dt, good, float(np.mean(rates))))
    for off, dt, good, rate in pos_c[:12]:
        print(f"  +0x{off:04x} {dt}  ok {good}/{len(segs)}  dx/tick {rate:.4f}")

    # --- mode flag (ship): byte 0/1 that is 0 at all attempt starts and 1 for a contiguous run in some attempt
    print("\n[mode-flag candidates] 0/1 byte, 0 at every attempt start, 1 for >=120 contiguous ticks somewhere")
    mode_c = []
    for off in range(BODY):
        b = body[:, off]
        if not np.isin(b, (0, 1)).all() or off in {o for o, _ in dead_c}:
            continue
        if any(b[s] != 0 for s, _ in segs):
            continue
        best = 0
        run = 0
        for x in b:
            run = run + 1 if x == 1 else 0
            best = max(best, run)
        if best >= 120:
            mode_c.append((off, best))
    for off, best in mode_c[:16]:
        print(f"  +0x{off:04x}  longest run {best} ticks")


if __name__ == "__main__":
    main(sys.argv[1])
