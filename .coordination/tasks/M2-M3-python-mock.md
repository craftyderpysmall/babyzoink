# Task: M2/M3 Python package against the v0 mock bridge

Status: done against mock
Agent/session: codex/python-01
Related plan: ../plans/2026-11-17-gd-learning-bot.md
Related handoff: ../handoffs/2026-11-18-claude-to-codex-python-side.md

## Delivered

- JSON framing and request validation, Windows byte-mode named-pipe client, and deterministic toy bridge for both in-process and Windows-pipe tests.
- Gymnasium environment that requires both isolation flags before play. Tick limits clamp the final request, and terminal steps use the bridge's actual tick count.
- JSON input-edge tapes with build and level identity, settings, seed, reset metadata, and terminal outcome. Replay can compare the first divergent trace tick and field. Protocol v0 has no RNG or game-settings command, so replay expects the caller to configure and attest those settings.
- IPC, observation and CPU PPO benchmark stages. Native replay timing requires the native bridge.
- Player-relative top-K and masked-set features, per-UID motion between samples, a static-hazard timing heuristic, and CPU-compatible SB3 extractors.

## Validation

- 21 tests passed under Windows CPython 3.14.10, including a Windows named pipe using the toy bridge, isolation refusal, replay across mock modes, and PPO updates with both encoders.
- PyTorch 2.15.0+cpu and Stable-Baselines3 2.9.2 installed from wheels and ran under Python 3.14.10. Built the package wheel and smoke-tested the benchmark command.
- The protocol spec and frozen game were outside this task's edit scope. Runtime replay parity, real-game performance, and learning transfer await native integration.

## Next action

Once M1 is ready, use Claude's pipe name and capability list to run against the real bridge. A protocol bump requires reconciling the Python client and mock before the live M2 suite. The current input tapes use JSON edges. Packed-bit tape sizes in the plan were estimates for an alternate representation.
