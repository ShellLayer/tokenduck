"""Raise the real taskbar above a synthetic widget and time passive recovery."""

import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tokenduck import DEFAULT_CONFIG, TokenDuck


def main():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetForegroundWindow.restype = W.HWND
    u.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
    u.FindWindowW.restype = W.HWND
    u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, W.UINT]
    u.SetWindowPos.restype = W.BOOL
    bar = TokenDuck(dict(DEFAULT_CONFIG), hidden=True)
    bar.root.title("TokenDuck layer regression")
    bar.root.attributes("-alpha", 0.0)
    bar.root.deiconify()
    bar.root.update_idletasks()
    bar._start_layer_guard()
    guard = bar._layer_guard
    assert guard is not None
    recoveries, failures = [], []

    def challenge():
        shell = u.FindWindowW("Shell_TrayWnd", None)
        if not shell:
            failures.append("Taskbar is unavailable")
            bar.root.quit()
            return
        before = u.GetForegroundWindow()
        started = time.perf_counter()
        u.SetWindowPos(shell, -1, 0, 0, 0, 0, 0x0013)
        if not guard.is_covered():
            failures.append("The stacking challenge was not established")
            bar.root.quit()
            return

        def observe():
            elapsed = (time.perf_counter()-started)*1000
            if not guard.is_covered():
                if u.GetForegroundWindow() != before:
                    failures.append("Layer recovery activated another window")
                recoveries.append(round(elapsed, 1))
            elif elapsed > 200:
                failures.append("Recovery waited longer than 200 ms")
                bar.root.quit()
            else:
                bar.root.after(5, observe)

        observe()

    try:
        for delay in (210, 590, 1030):
            bar.root.after(delay, challenge)
        bar.root.after(1500, bar.root.quit)
        bar.root.mainloop()
        assert not failures, failures
        assert len(recoveries) == 3, recoveries
        print(json.dumps({"taskbar_recovery_ms": recoveries, "foreground_unchanged": True,
                          "quota_fetches": 0, "screen_capture_used": False}))
    finally:
        # Leave the desktop in a normal state even when an assertion fails.
        guard.restore_if_needed()
        bar.quit()


if __name__ == "__main__":
    main()
