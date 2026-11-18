import ctypes
import sys

import pytest

from gdbot import runmode


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process controls")
def test_follow_switches_priority_affinity_and_threads():
    torch = pytest.importorskip("torch")
    k32 = runmode.kernel32()
    h = k32.GetCurrentProcess()
    try:
        assert runmode.follow("background")
        assert k32.GetPriorityClass(h) == 0x00004000
        pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
        k32.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm))
        assert bin(pm.value).count("1") == min(4, bin(sm.value).count("1"))
        assert torch.get_num_threads() == 2
        assert not runmode.follow("background")  # no change, no work
        assert runmode.follow("dedicated")
        assert k32.GetPriorityClass(h) == 0x00000020
        k32.GetProcessAffinityMask(h, ctypes.byref(pm), ctypes.byref(sm))
        assert pm.value == sm.value
        assert runmode.current() == "dedicated"
    finally:
        runmode.follow("dedicated")


def test_unknown_modes_are_ignored():
    assert not runmode.follow(None)
    assert not runmode.follow("turbo")
