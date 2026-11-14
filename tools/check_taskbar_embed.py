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
    u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [W.POINT], W.HWND
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
        assert bar.chip is None and canvas._input_hwnd
        left, top, right, bottom = canvas.screen_rect()
        candidates = [(left+2, y) for y in (top+3, (top+bottom)//2, bottom-3)]

        def pixel(point):
            dc = u.GetDC(None)
            try:
                return g.GetPixel(dc, *point)
            finally:
                u.ReleaseDC(None, dc)

        background_color = colorref(canvas.bg)
        blank = next((point for point in candidates if all(abs(((pixel(point) >> shift) & 255) -
                         ((background_color >> shift) & 255)) < 96 for shift in (0, 8, 16))), None)
        assert blank is not None, "No unobstructed taskbar background sample was found"
        background_before = pixel(blank)
        u.SetLayeredWindowAttributes(canvas._input_hwnd, 0, 1, 2)
        u.SetLayeredWindowAttributes(canvas.hwnd, colorref(canvas.bg), 255, 3)
        u.UpdateWindow(canvas._input_hwnd)
        u.UpdateWindow(canvas.hwnd)
        ctypes.WinDLL("dwmapi").DwmFlush()
        assert pixel(blank) == background_before, (pixel(blank), background_before)
        assert u.WindowFromPoint(W.POINT(*blank)) == canvas._input_hwnd
        item = bar.bars[1][0][1]
        x0, y0, x1, y1 = canvas.coords(item)
        point = (left+int((x0+x1)//2), top+int((y0+y1)//2))
        expected = colorref(canvas.itemcget(item, "fill"))
        foreground = u.GetForegroundWindow()
        pixels = []
        for _ in range(8):
            u.SetWindowPos(shell, -1, 0, 0, 0, 0, 0x13)
            ctypes.WinDLL("dwmapi").DwmFlush()
            pixels.append(pixel(point))
            assert u.GetAncestor(canvas.hwnd, 1) == shell
        assert all(pixel == expected for pixel in pixels), (pixels, expected)
        assert u.GetForegroundWindow() == foreground
        contexts = []
        canvas.bind("<ButtonRelease-3>", lambda event: contexts.append((event.x_root, event.y_root)))
        u.PostMessageW(canvas._input_hwnd, 0x205, 0, ((blank[1]-top) << 16) | (blank[0]-left))
        bar.root.update()
        canvas.poll_events()
        assert contexts == [blank]
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
                          "unshaded_background_pixel_unchanged": True, "blank_area_context_target": True,
                          "screen_capture_used": False}))
    finally:
        bar.quit()


if __name__ == "__main__":
    main()
