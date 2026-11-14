"""Exercise a real native menu across timer ticks; synthetic data, no capture."""

import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tokenduck import DEFAULT_CONFIG, TokenDuck
from subscription_menu import native_menu_active


def main():
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetTickCount.restype = W.DWORD
    u.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
    u.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    u.GetForegroundWindow.restype = W.HWND
    u.SetForegroundWindow.argtypes = [W.HWND]
    u.EndMenu.argtypes = []
    u.EndMenu.restype = W.BOOL
    foreground = u.GetForegroundWindow()
    bar = TokenDuck(dict(DEFAULT_CONFIG), hidden=True)
    bar.root.title("TokenDuck popup regression")
    bar.root.attributes("-alpha", 0.0)
    bar.root.deiconify()
    bar.root.update_idletasks()
    bar.data = {"plan_type": "plus", "rate_limit": {"primary_window": {
        "used_percent": 18, "limit_window_seconds": 18000, "reset_at": time.time()+7200}}}
    bar.kimi_data = {"level": "Moderato", "used_ratio": .15, "amount": 100000,
                     "amount_left": 85000, "windows": [{"tag": "5h", "used_percent": 0}]}
    bar.zcode_data = {"plan_name": "Pro", "windows": [
        {"tag": "5h", "used_percent": 0, "amount": 12000, "amount_left": 12000},
        {"tag": "w", "used_percent": 4, "amount": 60000, "amount_left": 57374}]}
    bar.error = bar.kimi_error = bar.zcode_error = None
    bar.render()
    bar.root.after(0, bar._native_tick)
    for index in range(bar.menu.index("end")+1):
        if bar.menu.type(index) in ("command", "checkbutton"):
            bar.menu.entryconfigure(index, command=lambda: None)
    changes = []
    active_samples = []
    start = k.GetTickCount()
    hook_type = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)

    @hook_type
    def changed(hook, event, hwnd, object_id, child_id, thread, stamp):
        if not hwnd or object_id or child_id:
            return
        name = ctypes.create_unicode_buffer(80)
        u.GetClassNameW(hwnd, name, 80)
        if name.value == "#32768":
            rect = W.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(rect))
            changes.append(((stamp-start) & 0xffffffff, (rect.left, rect.top, rect.right, rect.bottom)))

    u.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, hook_type, W.DWORD, W.DWORD, W.DWORD]
    u.SetWinEventHook.restype = W.HANDLE
    u.UnhookWinEvent.argtypes = [W.HANDLE]
    hook = u.SetWinEventHook(0x800b, 0x800b, None, changed, os.getpid(), 0, 0)
    assert hook, "Cannot observe the native menu"
    try:
        bar.root.after(100, lambda: bar.show_menu(SimpleNamespace(x_root=30, y_root=80)))
        bar.root.after(600, lambda: active_samples.append(native_menu_active()))
        bar.root.after(650, bar._anchor_tick)
        bar.root.after(1200, bar.render)
        bar.root.after(1700, lambda: active_samples.append(native_menu_active()))
        bar.root.after(2400, u.EndMenu)
        bar.root.after(2800, bar.root.quit)
        bar.root.mainloop()
        assert changes, "The native popup was not observed"
        assert len(active_samples) == 2 and all(active_samples), "The native popup closed before the timer checks"
        later = [entry for entry in changes if 500 <= entry[0] < 2300]
        assert not later, "The posted menu changed size during timer ticks: %r" % later[:8]
        assert not bar._render_pending, "Deferred updates did not resume after closing"
        print(json.dumps({"real_popup_observed": True, "timer_induced_menu_resizes": len(later),
                          "popup_held_across_ticks": True, "deferred_render_resumed": True,
                          "screen_capture_used": False}))
    finally:
        u.EndMenu()
        u.UnhookWinEvent(hook)
        bar.quit()
        if foreground:
            u.SetForegroundWindow(foreground)


if __name__ == "__main__":
    main()
