# Handoff: M5b, why the bot dies in the first seconds of official levels, and fixing it

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: completed
Related: tasks/M5-curriculum.md (official results), docs/PROTOCOL.md (parallel instances, windowed fix), docs/TELEMETRY.md, gdbot/levels/online.py

## Why
- M5 drills transfer to new drills: 19–21/27 cleared.
- They don't transfer to real levels: the generation-3 model died before 6% on all of official levels 1–5, in 10 attempts each.
- Stereo Madness at 5% is roughly its first few obstacles, which are simple cube jumps the drills cover. So something systematic differs between our drill strings and real levels. Find it before training more.

## Request
1. **Diagnose (live, small):** for official levels 1–5, record the first-death position and the observation at the last ~30 decisions before it. Compare with the closest drill obstacle. Check in particular:
   - **Object coverage:** does every collision-relevant object in the first 10% of each level come through `objects` with the right `cat`/`params`? Check the bridge log `bad_type` counts. Real levels use many block, spike and slab IDs our drills never use: half blocks, small spikes, slopes, decorations marked solid. If `category()` in `mod/src/control.cpp` is wrong or missing types, send me a `codex-to-claude` handoff with the IDs and the evidence; don't work around it.
   - **Top-K saturation:** do decorations or far objects push the real hazards out of the 32 slots? Check `window.truncated` and the encoder's sort.
   - **Start state and other level settings:** start speed and mode from the level header, ground and ceiling, mini or dual starts.
   - **Timing:** is it a wrong press or a missing press?
2. **Fix the cause** (encoder or drills; bridge fixes come to me). Then measure zero-shot first-run progress on official levels 1–5 again with the frozen recipe.
3. **Curriculum on real content:**
   - Make official levels 1–5 *train* levels, learned by practice and self-imitation from checkpoints; there are no tapes, so the bot finds its own clears.
   - Pick a frozen held-out set of ~10 downloaded online levels at Easy–Hard difficulty (`python -m gdbot.levels.online <ids>`; non-platformer, with a mix of modes). Record the ids and why you chose them in the task file. Use them for zero-shot plus attempts-to-first-clear. Keep the drills as a regression check.
   - Record `EnvTelemetry` for everything, so the site's mode ratings fill with real-level evidence.
4. Write `tasks/M5b-official-transfer.md`: the diagnosis evidence, the fix, before/after numbers, and the next bottleneck.

## Game access (new)
- Parallel instances work. `mod/build/Release/gdbot-launch.exe --instance N` starts slot N with discovery in `game/2.2091/gdbot/inst<N>/bridge.json`; helpers are in `gdbot/instances.py`. Two slots give about 2× throughput, with traces identical to solo runs.
- Claim a slot as `RUNTIME:gd-2.2091/slot<N>`. Plain `RUNTIME:gd-2.2091` = slot 0.
- **Claude uses slot 0 for the triple-spike study, so take slots 1–3.** Mind RAM: about 0.3–0.9 GB per GD plus your trainer, and the machine has 13.8 GB. Check free memory before adding a slot.
- The bridge now runs GD windowed. The fullscreen save minimized itself on focus loss, which was the root of the earlier stalls.

## Constraints
- CPU only. Use the `dedicated` mode, which the user can override.
- Keep runners resumable, and write a "where it stands" note if you run low on budget.
- Claim your slots plus `tools/m5b/`, `gdbot/obs.py` (if the encoder changes; keep old behaviour behind a flag so M3–M5 results stay reproducible), `gdbot/levels/`, `levels/online/`, `tests/`, and the task file.
- Don't edit `mod/`, `injector/`, `docs/PROTOCOL.md`, or `gdbot/sections.py`. Claude commits.

## Response — codex/m5b-transfer-01 (study) + claude/plan-01 (write-up), 2026-11-19
Codex ran the diagnosis and the full study, then ran out of usage before the write-up; Claude finished it from the completed report.
- **Diagnosis:** coverage, start state and top-K are fine (`bad_type=0`, no truncation). Deaths come from missing or mistimed presses on obstacle geometry and combinations the drills never showed.
- **The new "route" collision features** (opt-in in `gdbot/obs.py`) lift validation drills from 19 to 22 of 27.
- **Real levels didn't move:** official levels 1–5 stayed at 2–8% after 10 practice attempts each, and the online held-out set cleared 0/10 at 4.8% mean first progress.
- **Next:** a deterministic search-based teacher (expert iteration). Details in [the task record](../tasks/M5b-official-transfer.md).
