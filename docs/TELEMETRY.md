# Section telemetry (feeds the per-mode ratings on the dashboard site)

Producer: `gdbot/sections.py`. Consumer: `tools/site/export.py` → `tools/site/rating.py`.
Files: `build/telemetry/<run>.jsonl` (one row per attempt × entered section), plus `build/telemetry/section_maps.json` (learned section boundaries per level, so IDs stay stable).

## Recording from a runner
```python
from gdbot.sections import EnvTelemetry, TelemetryWriter, attempt_meta
tel = EnvTelemetry(env, TelemetryWriter("m5-g3-s1207"))            # one writer per run
obs, info = env.reset(...)
tel.started(attempt_meta(level="drill:ship/heldout-7100", attempt=1, start="zero",
                         generation=3, seed=1207, zero_shot=True))
obs, r, term, trunc, info = env.step(a)
tel.stepped(info, term, trunc)                                      # after every step
tel.stopped()                                                       # only if you abandon an attempt mid-way
```

## Row
| field | meaning |
| --- | --- |
| `run`, `t` | run name, unix time written |
| `level` | `drill:<family>/<variant>`, `official:<n>` or `online:<GD level id>` |
| `generation` (int ≥ 0), `seed`, `attempt` (int ≥ 1) | which model and which attempt on this level |
| `start` | `zero`, `checkpoint` or `startpos` |
| `zero_shot` | true only for the first attempt from zero on a level the model has never seen |
| `practice` | true for practice-loop attempts (checkpoint drilling, local search) |
| `section` | int: x of the section's boundary in the level (0 = the level start). Stable across attempts, start kinds and runs |
| `mode`, `speed`, `mini`, `dual` | the section's key; a change in any of them starts a new section |
| `entry_tick`, `exit_tick`, `ticks_in_section` (≥ 1), `entry_x`, `exit_x` | exposure, at the runner's decision resolution (k ticks) |
| `died` | the attempt died in this section |
| `cleared` | the attempt left this section alive (into the next section, or level complete) |
| neither | censored: the attempt stopped (timeout, abandoned) while inside |

## Stable section IDs
- A boundary is the x of the first observed mode, speed, mini or dual transition.
- Later transitions within 60 units (2 blocks) of a known boundary map to it.
- A checkpoint or start-position attempt that begins mid-level is assigned the known section containing its start x.
- Boundaries are learned the first time any attempt crosses them. A start position placed past an unseen boundary is therefore attributed to the preceding section until a run reaches that boundary.

## Online levels
`python -m gdbot.levels.online <id> ...` downloads levels from GD's servers outside the game (the game stays offline) into `levels/online/<id>.json`:
- the level data;
- name, stars, `demon`, `difficulty` and `length`.

`gdbot.levels.online.level_spec(record)` gives the `load_level` spec. Use `online:<id>` as the telemetry level key. Platformer levels are refused.
