"""Check the PlayerObject layout derived from bindings order + MSVC alignment against probe.bin.

Usage: python -I tools/m1/check_fields.py game/2.2091/gdbot/probe.bin
"""
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from find_fields import load, segments, as_type  # noqa: E402

FIELDS = {  # name: (offset, dtype)
    "m_yVelocity": (0x9A8, "<f8"),
    "m_fallSpeed": (0x9B0, "<f8"),
    "m_isShip": (0x9C1, "u1"),
    "m_isBird": (0x9C2, "u1"),
    "m_isBall": (0x9C3, "u1"),
    "m_isDart": (0x9C4, "u1"),
    "m_isRobot": (0x9C5, "u1"),
    "m_isSpider": (0x9C6, "u1"),
    "m_isUpsideDown": (0x9C7, "u1"),
    "m_isDead": (0x9C8, "u1"),
    "m_isOnGround": (0x9C9, "u1"),
    "m_isSwing": (0x9CC, "u1"),
    "m_isDashing": (0x9EC, "u1"),
    "m_vehicleSize": (0x9F8, "<f4"),
    "m_playerSpeed": (0x9FC, "<f4"),
    "m_position.x": (0xA98, "<f4"),
    "m_position.y": (0xA9C, "<f4"),
    "m_totalTime": (0xAA8, "<f8"),
}


def main(path):
    attempt, tick, held, body = load(path)
    cols = {k: as_type(body, off, dt).astype(np.float64) for k, (off, dt) in FIELDS.items()}
    print(f"{'field':<16}{'min':>12}{'max':>12}  distinct")
    for k, v in cols.items():
        print(f"{k:<16}{v.min():>12.4f}{v.max():>12.4f}  {len(np.unique(v))}")
    segs = [s for s in segments(attempt) if s[1] - s[0] > 60]
    s, e = max(segs, key=lambda x: x[1] - x[0])
    print(f"\nlongest attempt: ticks {e - s}")
    x = cols["m_position.x"][s:e]
    print(f"x: start {x[0]:.2f} end {x[-1]:.2f}; dx/tick median {np.median(np.diff(x)):.4f}")
    press = np.where(held[s + 1:e] & ~held[s:e - 1])[0] + s + 1
    if len(press):
        i = press[0]
        print(f"\nfirst press at tick {tick[i]}; next 8 ticks:")
        for j in range(i - 1, i + 8):
            print(f"  t={tick[j]:5d} held={int(held[j])} y={cols['m_position.y'][j]:8.3f} "
                  f"vy={cols['m_yVelocity'][j]:8.3f} ground={int(cols['m_isOnGround'][j])}")
    ship = np.where(cols["m_isShip"][s:e] == 1)[0]
    if len(ship):
        print(f"\nship: ticks {ship[0]}..{ship[-1]} of attempt, x {x[ship[0]]:.1f}..{x[ship[-1]]:.1f}")
    dead = np.where(cols["m_isDead"][s:e] == 1)[0]
    if len(dead):
        print(f"dead from tick {dead[0]} at x={x[dead[0]]:.1f}")


if __name__ == "__main__":
    main(sys.argv[1])
