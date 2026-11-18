# Handoff: M3 drill levels as generated level strings

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: steps 1–4 complete; step 5 awaits live level_string support
Related plan/task: plan M3 ("original hand-authored drills ... known-good tape for each"), docs/PROTOCOL.md "Planned v0 additions"

## Request
Generate the M3 drill set as **original** GD level strings, in pure Python. Don't copy existing levels. Do this after your M2-live work, or in parallel if it doesn't need the game.

1. **`gdbot/levels/levelstring.py`:** a builder that emits GD's inner level string, plus `encode()` producing what the bridge's `data` field expects: URL-safe base64 of gzip, starting with `H4sI` (see PROTOCOL.md). Round-trip test it. It needs a minimal header (classic mode, 1x speed, cube start, default colours) and objects as `1,id,2,x,3,y[,6,rot,4,flipX,5,flipY,32,scale]`. Document every object id you use, with its source.
2. **`gdbot/levels/drills.py`:** seeded, parameterised drill families. Each family has a `train` and a `heldout` variant set (shifted or recombined layouts, never identical to training).
   - jump timing: single spike, double spike, triple spike, block steps, pillar gaps
   - yellow orb: an orb over a spike pit
   - gravity portal: flip, plus a ceiling hazard
   - speed change: a speed portal followed by jump timing
   - moving geometry: one move trigger moving a block into the path (exercises trigger state). Mark this one "needs trigger support" if the bridge can't load triggers yet.
   - forward-only: every drill keeps the player moving right. Add a `progress_ok_dx` flag so Δx reward is valid.
3. **Write files** to `levels/drills/<family>/<variant>.txt`, plus `levels/drills/index.yaml` (family, variant, split, seed, sha256, notes). Keep each drill short: 10–25 s at 1x speed.
4. **Tests:** builder round-trip parsing, determinism per seed, sha256 stability, and no train/heldout overlap.
5. **Later, once Claude reports `kind: "level_string"` loading as live:** search for a known-good input tape per drill with the real bridge, which is deterministic. Store it with `replay.py` metadata. A drill without a tape doesn't go into training.

## Context and evidence
- The bridge will accept `load_level {"level": {"kind": "level_string", "name": ..., "data": ...}}` (see PROTOCOL.md). Claude is implementing this now, together with `quit_level` and object extraction.
- Physics facts measured on the real game (useful for spacing drills):
  - 1x speed: x advances 1.2982 per tick (240 ticks/s), so one 30-unit block takes about 23 ticks.
  - Cube jump: vy 11.18, minus 0.216 per tick. Peak height is about 2.3 blocks.
- Originality rule (user requirement): the drills are our own designs. They must not reproduce official or online levels.

## Files involved / active claims
- Claim `gdbot/levels/`, `levels/drills/`, and `tests/test_levels.py` before you start.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md` (Claude's). Request protocol changes by handoff.
- The game runtime is claimed via `RUNTIME:gd-2.2091` in CLAIMS.md, and only one client can drive it at a time.
- No git commits; the user handles those.

## Questions or decisions needed
- The encoding is decided: Python sends `data` in GD's stored format (base64+gzip). If GD rejects a drill, report the exact string and the bridge log line.

## Response — codex/m3-drills-01, 2026-11-18 UTC

Completed the Python assignment. The builder, seeded drill generator, and 18 original payloads are available under gdbot/levels/ and levels/drills/. The manifest has distinct train and held-out layouts, exact payload hashes, and training_ready=false for all entries. The moving variants explicitly require trigger support. All 37 tests passed. No GD session was started. Queue the live capture and verification work once the bridge can load level_string fixtures. See ../tasks/M3-drills.md for details.

## Outcome / next steps
Drills plus tapes feed the M3 baseline comparison (top-K vs set encoder, plus the heuristic) on unseen variants.

Note: creating this file does not notify or launch another agent. Add it to STATUS.md and ensure the recipient reads it.
