"""Exercise visible settings across native timers and deferred data updates."""

import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tokenduck as app


def main():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetForegroundWindow.restype = W.HWND
    u.SetForegroundWindow.argtypes = [W.HWND]
    u.GetAncestor.argtypes, u.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
    u.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    foreground = u.GetForegroundWindow()
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(app, "DATA_DIR", directory), \
            patch.object(app, "CONFIG_PATH", str(Path(directory)/"config.json")), \
            patch.object(app, "AUTH_PATH", str(Path(directory)/"missing-auth.json")), \
            patch.object(app, "_read_kimi_web_cred", return_value=None), \
            patch.object(app, "ACCOUNT_STORE") as store:
        store.get.return_value = None
        # Simulate login starting the app before Explorer exposes its taskbar.
        with patch.object(app.ctypes.windll.user32, "FindWindowW", return_value=0):
            bar = app.TokenDuck(dict(app.DEFAULT_CONFIG), hidden=True)
        assert bar.canvas.hwnd is None and bar.root.winfo_exists()
        bar.root.deiconify()
        bar.root.update_idletasks()
        bar.anchor()
        assert bar.canvas.hwnd and bar.canvas._snapshot
        bar.error = bar.kimi_error = bar.zcode_error = None
        events, handles, errors = [], {}, []
        checked = {"used": False, "remaining": False}
        start = time.monotonic()
        hook_type = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)

        @hook_type
        def changed(_hook, event, hwnd, object_id, child_id, _thread, _stamp):
            if object_id == 0 and child_id == 0 and hwnd in handles.values():
                rect = W.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(rect))
                events.append((round((time.monotonic()-start)*1000), event, hwnd,
                               (rect.left, rect.top, rect.right, rect.bottom)))

        u.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, hook_type, W.DWORD, W.DWORD, W.DWORD]
        u.SetWinEventHook.restype = W.HANDLE
        u.UnhookWinEvent.argtypes = [W.HANDLE]
        hook = u.SetWinEventHook(0x8002, 0x800b, None, changed, os.getpid(), 0, 0)
        assert hook

        def fail(exc, value, _traceback):
            errors.append(exc.__name__+": "+str(value))
            bar.root.quit()

        def open_settings():
            bar.show_display_settings()
            bar.root.update_idletasks()
            handles["settings"] = u.GetAncestor(bar._settings_window.winfo_id(), 2)

        def select(mode):
            assert bar._settings_window.state() == "normal"
            bar._settings_mode_buttons[mode].invoke()
            checked[mode] = bar._settings_mode_buttons[mode].instate(["selected"])

        def save():
            assert bar._render_pending
            bar._settings_save_button.invoke()
            assert app.load_config()["quota_display"] == "used"
            assert not bar._settings_window.winfo_exists()

        def open_accounts():
            bar.show_account_settings()
            bar.root.update_idletasks()
            handles["accounts"] = u.GetAncestor(bar._account_window.winfo_id(), 2)

        bar.root.report_callback_exception = fail
        try:
            bar.root.after(0, bar._native_tick)
            bar.root.after(100, open_settings)
            bar.root.after(600, lambda: select("used"))
            bar.root.after(800, lambda: threading.Thread(target=lambda: bar._post_ui(bar.render), daemon=True).start())
            bar.root.after(900, bar._anchor_tick)
            bar.root.after(1000, bar._render_tick)
            bar.root.after(1200, lambda: select("remaining"))
            bar.root.after(1600, lambda: select("used"))
            bar.root.after(2400, save)
            bar.root.after(2700, open_accounts)
            bar.root.after(3200, bar.render)
            bar.root.after(3600, bar.apply_theme)
            bar.root.after(5000, lambda: bar._account_window.destroy())
            bar.root.after(6200, bar.root.quit)
            bar.root.mainloop()
            assert not errors, errors
            assert all(checked.values())
            assert not bar._render_pending, "Deferred data did not resume after closing the dialogs"
            assert all(any(e[2] == handles[name] for e in events) for name in ("settings", "accounts")), \
                "Native window events were not observed for both dialogs"
            stable = [e for e in events if (e[2] == handles.get("settings") and 400 <= e[0] < 2300) or
                      (e[2] == handles.get("accounts") and 3000 <= e[0] < 4900)]
            flickers = [e for e in stable if e[1] in (0x8002, 0x8003, 0x800b)]
            assert not flickers, flickers[:8]
            print(json.dumps({"visible_settings_operated": True, "visible_accounts_checked": True,
                              "mode_buttons_and_save_work": True, "post_opening_show_hide_resize_events": len(flickers),
                              "native_window_events_observed": len(events),
                              "deferred_update_resumed": True, "delayed_taskbar_startup_recovers": True,
                              "screen_capture_used": False}))
        finally:
            u.UnhookWinEvent(hook)
            bar.quit()
            if foreground:
                u.SetForegroundWindow(foreground)


if __name__ == "__main__":
    main()
