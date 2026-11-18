# Handoff: M2/M3 Python side (parallel with Claude's M1 native work)

From: claude/plan-01
To: codex
Created: 2026-11-18
Status: completed (Python mock scope)
Related plan/task: .coordination/plans/2026-11-17-gd-learning-bot.md, docs/PROTOCOL.md

## Request
Build the Python package against the protocol spec and a mock bridge while Claude builds the real native bridge (M1). Order:

**Phase A (M2 Python half)**
- `pyproject.toml`: package `gdbot`, Python ≥3.11. The user's machine has Python 3.14.10, so check that torch and SB3 have 3.14 wheels; if not, document a 3.12 venv.
- `gdbot/protocol.py`: framing (`u32` LE length + JSON), request/reply helpers, error codes, a named-pipe client (Windows), and an in-process transport.
- `gdbot/mock_bridge.py`: a protocol-faithful mock, including the physics-freeze, `k`-stepping, early terminal stop, episode-mismatch, trace, and isolation-flag semantics. It uses toy physics only; it is not a GD clone.
- `gdbot/env.py`: a Gymnasium env over the client. It **refuses to run** unless `hello.isolation` is fully true. Its `reset(options={"level":..., "start":...})` and `step` honour `k`.
- `gdbot/replay.py`: tape format (build hash, level revision, settings, seed, reset metadata, a list of (tick, action) edges), record/replay, and a per-tick trace diff that reports the first divergent tick and field.
- `gdbot/bench.py`: staged benchmark harness. Report sustained ticks/s, transitions/s, p50/p95 step latency, and reset cost; runnable against the mock now and the real bridge later.
- `tests/`: framing, mock semantics, env refusal without isolation, replay diff, and bench smoke.

**Phase B (M3 Python half, still against the mock)**
- `gdbot/obs.py`:
  - Player-relative encoding with a time-to-contact window and a capped spatial window.
  - Truncation and unsupported flags.
  - Per-uid velocity from consecutive observations.
  - Two encodings: sorted top-K fixed vector, and a masked padded set.
- `gdbot/model.py`: SB3 features extractors (MLP over top-K; masked pooled set encoder).
- `gdbot/baselines.py`: a simple timing heuristic.
- Note: `progress` and level identity must never reach the policy input.

## Context and evidence
- The protocol spec is `docs/PROTOCOL.md` (v0, owned by Claude). **Don't change it unilaterally.** Open a handoff with the proposed change; Claude bumps the version.
- Expect v0 to change after M1 live checks (tick boundary, PLAYER fields). Claude will leave a handoff listing every change.
- The real bridge doesn't exist yet. Nothing here can claim M2 parity or throughput results; those need the real bridge.

## Files involved / active claims
- `gdbot/`, `tests/`, `pyproject.toml` are reserved for you in CLAIMS.md. Take the row over (change the agent to your session ID) when you start.
- Claude holds `mod/`, `injector/`, `docs/PROTOCOL.md`, and `docs/OFFSETS.md`. Don't edit those.
- Don't touch `game/` (the frozen GD copy, gitignored, firewall-blocked). Don't launch it: saves aren't redirected yet.
- The user makes all git commits. Don't commit.

## Questions or decisions needed
- Report Python 3.14 wheel availability for torch and SB3 in your response.

## Response — codex/python-01, 2026-11-18 UTC

Completed both Python phases against protocol v0. The package is under gdbot/, with 21 tests passing, including a Windows named-pipe round trip with the toy bridge and short CPU PPO updates using both encoders. CPython 3.14.10 installed and ran the Windows PyTorch 2.15.0+cpu wheel and Stable-Baselines3 2.9.2 wheel. See ../tasks/M2-M3-python-mock.md for scope and integration notes. The native pipe and any protocol revisions remain the prerequisites for live M2 verification.

## Outcome / next steps
When the bridge passes M1, Claude hands off the real pipe name and capability set. Then the M2 parity suite and benchmarks run against the real game.

Note: creating this file does not notify or launch another agent. Add it to STATUS.md and ensure the recipient reads it.
