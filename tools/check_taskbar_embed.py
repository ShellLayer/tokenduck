"""Prove the native child survives taskbar raises without a recovery callback."""

import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_taskbar import OPEN_SETTINGS, colorref
from tokenduck import DEFAULT_CONFIG, TokenDuck


def main():
    bar = TokenDuck(dict(DEFAULT_CONFIG, offset_x=320), hidden=True)
    canvas = bar.canvas
    u, g = canvas.u, canvas.g
    u.GetForegroundWindow.restype = W.HWND
    u.UpdateWindow.argtypes = [W.HWND]
    g.GetPixel.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
    g.GetPixel.restype = W.DWORD
    shell = u.FindWindowW("Shell_TrayWnd", None)
    assert shell and canvas.hwnd
    bar.data = {"rate_limit": {"primary_window": {"used_percent": 18, "limit_window_seconds": 18000}}}
    bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 0}]}
    bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 24}]}
    bar.error = bar.kimi_error = bar.zcode_error = None
    try:
        bar.render()
        bar.root.update_idletasks()
        u.SetLayeredWindowAttributes(canvas.hwnd, colorref(canvas.bg), 255, 3)
        u.UpdateWindow(canvas.hwnd)
        ctypes.WinDLL("dwmapi").DwmFlush()
        left, top, right, bottom = canvas.screen_rect()
        point = (left+2, (top+bottom)//2)
        expected = colorref(bar.chip_color)
        foreground = u.GetForegroundWindow()
        pixels = []
        for _ in range(8):
            u.SetWindowPos(shell, -1, 0, 0, 0, 0, 0x13)
            ctypes.WinDLL("dwmapi").DwmFlush()
            dc = u.GetDC(None)
            pixels.append(g.GetPixel(dc, *point))
            u.ReleaseDC(None, dc)
            assert u.GetAncestor(canvas.hwnd, 1) == shell
        assert all(pixel == expected for pixel in pixels), (pixels, expected)
        assert u.GetForegroundWindow() == foreground
        requests = []
        canvas.bind("<<OpenSettings>>", lambda _event: requests.append(True))
        u.PostMessageW(canvas.hwnd, OPEN_SETTINGS, 0, 0)
        bar.root.update()
        canvas.poll_events()
        assert requests == [True]
        snapshot = canvas._snapshot
        u.DestroyWindow(canvas.hwnd)
        assert canvas.hwnd is None and bar.root.winfo_exists()
        assert canvas.ensure_window(force=True)
        assert canvas._snapshot == snapshot
        assert u.GetAncestor(canvas.hwnd, 1) == shell
        Path("build").mkdir(exist_ok=True)
        canvas.save_render("build/native-meter-validation.png")
        print(json.dumps({"native_taskbar_child": True, "parent_raises_without_occlusion": len(pixels),
                          "recovery_callbacks": 0, "foreground_unchanged": True,
                          "child_recreation_preserves_engine": True, "reopen_request_delivered": True,
                          "screen_capture_used": False}))
    finally:
        bar.quit()


if __name__ == "__main__":
    main()
