"""Run first-press and checkpoint contract probes against a claimed CBF game slot."""

import argparse
import sys
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gdbot.instances import discovery
from gdbot.levels.levelstring import LevelString
from gdbot.protocol import BridgeClient, NamedPipeTransport, ProtocolError, RemoteError


def player_signature(player):
    return (tuple(round(player[field], 5) for field in ("x", "y", "vx", "vy", "rot")),
            tuple(player[field] for field in ("mode", "on_ground", "holding", "buffered")))


def step(client, state, action, frac=None):
    request = {"episode": state["episode"], "action": action, "k": 1}
    if frac is not None:
        request["frac"] = frac
    reply = client.request("step", **request)
    if reply["terminal"] is not None or reply["tick"] != state["tick"] + 1:
        raise RuntimeError(f"unexpected outcome in the flat CBF fixture: {reply['terminal']}")
    return reply


def ground(client):
    state = client.request("reset", start={"kind": "zero"})
    for _ in range(120):
        if state["obs"]["players"][0]["on_ground"]:
            return state
        state = step(client, state, 0)
    raise RuntimeError("cube did not settle on the fixture floor")


def press_trace(client, state, fraction):
    trace = []
    for index in range(8):
        state = step(client, state, 1, fraction if index == 0 else None)
        trace.append(player_signature(state["obs"]["players"][0]))
    return trace


def run(client):
    hello = client.require_isolated()
    if hello.get("capabilities", {}).get("cbf") is not True:
        raise RuntimeError("slot does not report CBF support")
    level = LevelString()
    level.add(1, 4000, 15)  # a distant block defines the level length and leaves the first jump clear
    client.load_level({"kind": "level_string", "name": "M8 flat CBF probe", "data": level.encode()})

    omitted = press_trace(client, ground(client), None)
    at_start = press_trace(client, ground(client), 0.0)
    half_tick = press_trace(client, ground(client), 0.5)
    if omitted != at_start:
        raise RuntimeError("omitted fraction differs from explicit zero")
    if not any(a[0][1] > b[0][1] + 1e-5 for a, b in zip(at_start, half_tick)):
        raise RuntimeError("half-tick press did not postpone upward displacement")
    print("Zero-fraction parity and fractional onset passed.")

    beginning = ground(client)
    pressed = step(client, beginning, 1, 0.5)
    released = step(client, pressed, 0, 0.25)
    beginning = ground(client)
    batch = client.request("step_seq", episode=beginning["episode"], actions=[1, 0], fracs=[0.5, 0.25], k=1)
    if (batch["terminal"] or batch["decisions"] != 2 or batch["tick"] != released["tick"] or
            player_signature(batch["player"]) != player_signature(released["obs"]["players"][0])):
        raise RuntimeError("fractional press/release differs between step and step_seq")
    print("Fractional step and step_seq parity passed.")

    beginning = ground(client)
    client.request("set_practice", enabled=True)
    client.request("checkpoint_create")
    first = press_trace(client, step(client, beginning, 0), 0.5)
    checkpoint = client.request("reset", start={"kind": "checkpoint"})
    again = press_trace(client, step(client, checkpoint, 0), 0.5)
    if first != again:
        raise RuntimeError("fractional press diverged after a released checkpoint warm-up")
    print("Warm checkpoint parity passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    args = parser.parse_args()
    with BridgeClient(NamedPipeTransport(discovery(args.slot)["pipe"])) as client:
        client.require_isolated()
        with suppress(RemoteError):
            client.request("quit_level")
        try:
            run(client)
        finally:
            with suppress(OSError, EOFError, ProtocolError):
                client.request("quit_level")
