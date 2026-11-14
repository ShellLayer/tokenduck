"""A native child of the Windows taskbar, painted without entering Tcl callbacks."""

from collections import deque
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as W
import os
import struct
import time
from types import SimpleNamespace
import zlib


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
OPEN_SETTINGS = 0x802a
MAIN_PROPERTY = "TokenDuck.Meter.Main"


class WindowClass(ctypes.Structure):
    _fields_ = [("style", W.UINT), ("proc", WNDPROC), ("extra", ctypes.c_int),
                ("window_extra", ctypes.c_int), ("instance", W.HINSTANCE),
                ("icon", W.HANDLE), ("cursor", W.HANDLE), ("background", W.HBRUSH),
                ("menu", W.LPCWSTR), ("name", W.LPCWSTR)]


class PaintStruct(ctypes.Structure):
    _fields_ = [("dc", W.HDC), ("erase", W.BOOL), ("rect", W.RECT),
                ("restore", W.BOOL), ("update", W.BOOL), ("reserved", W.BYTE*32)]


def colorref(color):
    return int(color[1:3], 16) | int(color[3:5], 16) << 8 | int(color[5:7], 16) << 16


def windows_api():
    u = ctypes.WinDLL("user32", use_last_error=True)
    g = ctypes.WinDLL("gdi32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "FindWindowW": ([W.LPCWSTR, W.LPCWSTR], W.HWND),
        "GetAncestor": ([W.HWND, W.UINT], W.HWND),
        "GetWindowThreadProcessId": ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
        "GetWindowRect": ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
        "GetClientRect": ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
        "ClientToScreen": ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
        "ScreenToClient": ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
        "IsWindow": ([W.HWND], W.BOOL),
        "RegisterClassW": ([ctypes.POINTER(WindowClass)], W.WORD),
        "UnregisterClassW": ([W.LPCWSTR, W.HINSTANCE], W.BOOL),
        "CreateWindowExW": ([W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                              ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND),
        "DefWindowProcW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], ctypes.c_ssize_t),
        "DestroyWindow": ([W.HWND], W.BOOL),
        "ShowWindow": ([W.HWND, ctypes.c_int], W.BOOL),
        "SetWindowPos": ([W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, W.UINT], W.BOOL),
        "SetLayeredWindowAttributes": ([W.HWND, W.DWORD, W.BYTE, W.DWORD], W.BOOL),
        "SetPropW": ([W.HWND, W.LPCWSTR, W.HANDLE], W.BOOL),
        "GetPropW": ([W.HWND, W.LPCWSTR], W.HANDLE),
        "RemovePropW": ([W.HWND, W.LPCWSTR], W.HANDLE),
        "PostMessageW": ([W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
        "BeginPaint": ([W.HWND, ctypes.POINTER(PaintStruct)], W.HDC),
        "EndPaint": ([W.HWND, ctypes.POINTER(PaintStruct)], W.BOOL),
        "InvalidateRect": ([W.HWND, ctypes.POINTER(W.RECT), W.BOOL], W.BOOL),
        "FillRect": ([W.HDC, ctypes.POINTER(W.RECT), W.HBRUSH], ctypes.c_int),
        "DrawTextW": ([W.HDC, W.LPCWSTR, ctypes.c_int, ctypes.POINTER(W.RECT), W.UINT], ctypes.c_int),
        "GetDC": ([W.HWND], W.HDC), "ReleaseDC": ([W.HWND, W.HDC], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        fn = getattr(u, name)
        fn.argtypes, fn.restype = arguments, result
    for name, arguments, result in (
        ("CreateCompatibleDC", [W.HDC], W.HDC),
        ("CreateCompatibleBitmap", [W.HDC, ctypes.c_int, ctypes.c_int], W.HBITMAP),
        ("SelectObject", [W.HDC, W.HANDLE], W.HANDLE),
        ("DeleteDC", [W.HDC], W.BOOL), ("DeleteObject", [W.HANDLE], W.BOOL),
        ("CreateSolidBrush", [W.DWORD], W.HBRUSH),
        ("GetStockObject", [ctypes.c_int], W.HANDLE),
        ("RoundRect", [W.HDC]+[ctypes.c_int]*6, W.BOOL),
        ("SetBkMode", [W.HDC, ctypes.c_int], ctypes.c_int),
        ("SetTextColor", [W.HDC, W.DWORD], W.DWORD),
        ("CreateFontW", [ctypes.c_int]*5+[W.DWORD]*8+[W.LPCWSTR], W.HFONT),
        ("BitBlt", [W.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    W.HDC, ctypes.c_int, ctypes.c_int, W.DWORD], W.BOOL),
        ("GetDIBits", [W.HDC, W.HBITMAP, W.UINT, W.UINT, W.LPVOID, W.LPVOID, W.UINT], ctypes.c_int),
    ):
        fn = getattr(g, name)
        fn.argtypes, fn.restype = arguments, result
    k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [W.LPCWSTR], W.HMODULE
    return u, g, k


@contextmanager
def parent_dpi(u, parent):
    old = None
    try:
        u.GetWindowDpiAwarenessContext.argtypes = [W.HWND]
        u.GetWindowDpiAwarenessContext.restype = W.HANDLE
        u.SetThreadDpiAwarenessContext.argtypes = [W.HANDLE]
        u.SetThreadDpiAwarenessContext.restype = W.HANDLE
        old = u.SetThreadDpiAwarenessContext(u.GetWindowDpiAwarenessContext(parent))
    except (AttributeError, OSError):
        pass
    try:
        yield
    finally:
        if old:
            u.SetThreadDpiAwarenessContext(old)


class TaskbarCanvas:
    """Small Canvas-compatible display model backed by a layered WS_CHILD window."""

    def __init__(self, root, bg, transparent=True, hidden=False, capture_background=False):
        self.root, self.bg, self.transparent, self.hidden = root, bg, transparent, hidden
        self.capture_background = capture_background
        self.u, self.g, self.k = windows_api()
        self.hwnd = self.parent = None
        self._input_hwnd = None
        self._closed = False
        self._items, self._bindings, self._fonts = {}, {}, {}
        self._snapshot, self._events = (), deque()
        self._geometry = None
        self._width = self._height = 1
        self._next_host_check = 0
        self._class_name = "TokenDuckMeter_%d_%x" % (os.getpid(), id(self))
        self._instance = self.k.GetModuleHandleW(None)
        self._proc = WNDPROC(self._window_proc)
        wc = WindowClass()
        wc.style, wc.proc, wc.instance, wc.name = 3, self._proc, self._instance, self._class_name
        if not self.u.RegisterClassW(ctypes.byref(wc)):
            raise ctypes.WinError(ctypes.get_last_error())

    def pack(self, **_options):
        pass

    def bind(self, event, function=None):
        if function is None:
            return "native-binding" if event in self._bindings else ""
        self._bindings[event] = function

    def _add(self, kind, coordinates, options):
        if len(coordinates) == 1 and isinstance(coordinates[0], (list, tuple)):
            coordinates = coordinates[0]
        index = len(self._items)+1
        self._items[index] = dict(kind=kind, coords=list(coordinates), state="normal")
        self._items[index].update(options)
        return index

    def create_text(self, *coordinates, **options):
        return self._add("text", coordinates, options)

    def create_rectangle(self, *coordinates, **options):
        return self._add("rectangle", coordinates, options)

    def create_polygon(self, *coordinates, **options):
        return self._add("polygon", coordinates, options)

    def coords(self, index, *coordinates):
        if coordinates:
            self._items[index]["coords"] = list(coordinates)
        return list(self._items[index]["coords"])

    def itemconfig(self, index, **options):
        self._items[index].update(options)

    def itemcget(self, index, option):
        return str(self._items[index].get(option, ""))

    def bbox(self, index):
        item = self._items[index]
        if item["kind"] != "text":
            c = item["coords"]
            return min(c[::2]), min(c[1::2]), max(c[::2]), max(c[1::2])
        x, y = item["coords"]
        width = item["font"].measure(str(item.get("text", "")))
        height = item["font"].metrics("linespace")
        left = x-width if item.get("anchor") == "e" else x
        return left-1, y-height/2, left+width+1, y+height/2

    def configure(self, **options):
        if "bg" in options:
            self.bg = options["bg"]
            self._set_opacity()
            if self._input_hwnd:
                self.u.InvalidateRect(self._input_hwnd, None, False)

    def set_geometry(self, width, height, x, y):
        changed = self._geometry != (width, height, x, y)
        self._geometry = (width, height, x, y)
        created = self.ensure_window(force=True)
        if changed and self.hwnd and not created:
            self._place()

    def _owned_window(self, hwnd=None):
        hwnd = self.hwnd if hwnd is None else hwnd
        if not hwnd or not self.u.IsWindow(hwnd):
            return False
        pid = W.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()

    def ensure_window(self, force=False):
        if self._closed or self._geometry is None:
            return False
        if not force and self.hwnd and time.monotonic() < self._next_host_check:
            return False
        self._next_host_check = time.monotonic()+0.5
        shell = self.u.FindWindowW("Shell_TrayWnd", None)
        input_ready = (not self.capture_background or
                       (self._input_hwnd and self._owned_window(self._input_hwnd) and
                        self.u.GetAncestor(self._input_hwnd, 1) == shell))
        if self._owned_window() and shell and self.u.GetAncestor(self.hwnd, 1) == shell and input_ready:
            return False
        for hwnd in (self.hwnd, self._input_hwnd):
            if hwnd and self._owned_window(hwnd):
                self.u.DestroyWindow(hwnd)
        self.hwnd = self._input_hwnd = None
        if not shell:
            return False
        with parent_dpi(self.u, shell):
            # Layered children compose above the taskbar's DirectComposition surface.
            if self.capture_background:
                self._input_hwnd = self.u.CreateWindowExW(0x08080004, self._class_name, "TokenDuck input",
                    0x44000000, 0, 0, 1, 1, shell, None, self._instance, None)
                if not self._input_hwnd:
                    raise ctypes.WinError(ctypes.get_last_error())
            self.hwnd = self.u.CreateWindowExW(0x08080004, self._class_name, "TokenDuck quotas",
                                               0x44000000, 0, 0, 1, 1, shell, None, self._instance, None)
        if not self.hwnd:
            error = ctypes.get_last_error()
            if self._input_hwnd:
                self.u.DestroyWindow(self._input_hwnd)
            raise ctypes.WinError(error)
        self.parent = shell
        if not self.hidden:
            self.u.SetPropW(self.hwnd, MAIN_PROPERTY, 1)
        self._set_opacity()
        self._place()
        if self._input_hwnd:
            self.u.ShowWindow(self._input_hwnd, 4)
        self.u.ShowWindow(self.hwnd, 4)
        self.u.InvalidateRect(self.hwnd, None, False)
        self._events.append(("<<HostReady>>", 0, 0))
        return True

    def _set_opacity(self):
        if self._input_hwnd and self._owned_window(self._input_hwnd):
            # Alpha 1 retains a generous input target while blending the sampled
            # taskbar color below visible contrast; alpha 0 would pass clicks through.
            self.u.SetLayeredWindowAttributes(self._input_hwnd, 0, 0 if self.hidden else 1, 2)
        if self._owned_window():
            flags = 3 if self.transparent else 2
            self.u.SetLayeredWindowAttributes(self.hwnd, colorref(self.bg), 0 if self.hidden else 255, flags)

    def _place(self):
        width, height, x, y = self._geometry
        with parent_dpi(self.u, self.parent):
            point, bounds = W.POINT(x, y), W.RECT()
            self.u.ScreenToClient(self.parent, ctypes.byref(point))
            self.u.GetClientRect(self.parent, ctypes.byref(bounds))
            self._width, self._height = min(width, bounds.right), min(height, bounds.bottom)
            point.x = max(0, min(point.x, bounds.right-self._width))
            point.y = max(0, min(point.y, bounds.bottom-self._height))
            for hwnd in (self._input_hwnd, self.hwnd):
                if hwnd:
                    self.u.SetWindowPos(hwnd, 0, point.x, point.y, self._width, self._height, 0x0210)

    def screen_rect(self):
        if self._owned_window():
            r = W.RECT()
            if self.u.GetWindowRect(self.hwnd, ctypes.byref(r)):
                return r.left, r.top, r.right, r.bottom
        return None

    def _font_info(self, font):
        actual = font.actual()
        scale = float(self.root.tk.call("tk", "scaling"))
        pixels = max(1, round(abs(actual["size"])*(scale if actual["size"] > 0 else 1)))
        key = (actual["family"], pixels, actual["weight"], actual["slant"], actual["underline"], actual["overstrike"])
        if key not in self._fonts:
            self._fonts[key] = self.g.CreateFontW(-pixels, 0, 0, 0, 700 if actual["weight"] == "bold" else 400,
                                                 actual["slant"] == "italic", actual["underline"], actual["overstrike"],
                                                 1, 0, 0, 5, 0, actual["family"])
        return self._fonts[key], font.metrics("linespace")

    def commit(self):
        snapshot = []
        for item in self._items.values():
            if item.get("state") == "hidden":
                continue
            entry = dict(item, coords=tuple(item["coords"]))
            if item["kind"] == "text":
                entry["font"], entry["linespace"] = self._font_info(item["font"])
            snapshot.append(entry)
        self._snapshot = tuple(snapshot)
        if self._owned_window():
            self.u.InvalidateRect(self.hwnd, None, False)

    def _draw(self, dc):
        rectangle = W.RECT(0, 0, self._width, self._height)
        brush = self.g.CreateSolidBrush(colorref(self.bg))
        self.u.FillRect(dc, ctypes.byref(rectangle), brush)
        self.g.DeleteObject(brush)
        self.g.SetBkMode(dc, 1)
        for item in self._snapshot:
            c = item["coords"]
            self.g.SetTextColor(dc, colorref(item.get("fill", "#000000")))
            if item["kind"] == "text":
                old = self.g.SelectObject(dc, item["font"])
                x, y = c
                top = round(y-item["linespace"]/2)
                right = item.get("anchor") == "e"
                r = W.RECT(0 if right else round(x), top, round(x) if right else self._width, top+item["linespace"])
                text = str(item.get("text", ""))
                self.u.DrawTextW(dc, text, len(text), ctypes.byref(r), 0x824 | (2 if right else 0))
                self.g.SelectObject(dc, old)
            else:
                brush = self.g.CreateSolidBrush(colorref(item["fill"]))
                if item["kind"] == "rectangle":
                    r = W.RECT(*(round(v) for v in c))
                    self.u.FillRect(dc, ctypes.byref(r), brush)
                else:
                    old = self.g.SelectObject(dc, brush)
                    pen = self.g.SelectObject(dc, self.g.GetStockObject(8))
                    self.g.RoundRect(dc, round(min(c[::2])), round(min(c[1::2])),
                                     round(max(c[::2])), round(max(c[1::2])), 14, 14)
                    self.g.SelectObject(dc, pen)
                    self.g.SelectObject(dc, old)
                self.g.DeleteObject(brush)

    def _paint(self, hwnd):
        ps = PaintStruct()
        target = self.u.BeginPaint(hwnd, ctypes.byref(ps))
        memory = self.g.CreateCompatibleDC(target)
        bitmap = self.g.CreateCompatibleBitmap(target, max(1, self._width), max(1, self._height))
        old = self.g.SelectObject(memory, bitmap)
        try:
            self._draw(memory)
            self.g.BitBlt(target, 0, 0, self._width, self._height, memory, 0, 0, 0xcc0020)
        finally:
            self.g.SelectObject(memory, old)
            self.g.DeleteObject(bitmap)
            self.g.DeleteDC(memory)
            self.u.EndPaint(hwnd, ctypes.byref(ps))

    def _paint_input(self, hwnd):
        ps = PaintStruct()
        dc = self.u.BeginPaint(hwnd, ctypes.byref(ps))
        brush = self.g.CreateSolidBrush(colorref(self.bg))
        try:
            rectangle = W.RECT(0, 0, self._width, self._height)
            self.u.FillRect(dc, ctypes.byref(rectangle), brush)
        finally:
            self.g.DeleteObject(brush)
            self.u.EndPaint(hwnd, ctypes.byref(ps))

    def _window_proc(self, hwnd, message, wparam, lparam):
        # Never call Tk/Tcl here: native messages may arrive inside a Tcl operation.
        try:
            if message == 15:
                if hwnd == self._input_hwnd:
                    self._paint_input(hwnd)
                else:
                    self._paint(hwnd)
                return 0
            if message == 20:
                return 1
            if message == 0x21:
                return 3  # MA_NOACTIVATE
            if message == 0x205:
                p = W.POINT(ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value)
                self.u.ClientToScreen(hwnd, ctypes.byref(p))
                self._events.append(("<ButtonRelease-3>", p.x, p.y))
                return 0
            if message == OPEN_SETTINGS:
                self._events.append(("<<OpenSettings>>", 0, 0))
                return 0
            if message == 0x82 and hwnd == self.hwnd:
                self.hwnd = None
            if message == 0x82 and hwnd == self._input_hwnd:
                self._input_hwnd = None
        except Exception as error:
            self._events.append(("<<NativeError>>", type(error).__name__, 0))
        return self.u.DefWindowProcW(hwnd, message, wparam, lparam)

    def poll_events(self):
        if self._closed:
            return
        self.ensure_window()
        while self._events:
            event, x, y = self._events.popleft()
            callback = self._bindings.get(event)
            if callback:
                callback(SimpleNamespace(x_root=x, y_root=y, widget=self))
            if self._closed:
                break

    def close(self):
        self._closed = True
        if self._owned_window():
            self.u.RemovePropW(self.hwnd, MAIN_PROPERTY)
        for hwnd in (self.hwnd, self._input_hwnd):
            if hwnd and self._owned_window(hwnd):
                self.u.DestroyWindow(hwnd)
        self.u.UnregisterClassW(self._class_name, self._instance)
        for font in self._fonts.values():
            if font:
                self.g.DeleteObject(font)
        self._fonts.clear()
        self._items.clear()
        self._snapshot = ()
        self._events.clear()
        self._bindings.clear()
        self.root = None

    def save_render(self, path):
        """Export only this model's own offscreen bitmap for synthetic layout checks."""
        dc = self.u.GetDC(None)
        memory = self.g.CreateCompatibleDC(dc)
        bitmap = self.g.CreateCompatibleBitmap(dc, self._width, self._height)
        old = self.g.SelectObject(memory, bitmap)
        try:
            self._draw(memory)
            self.g.SelectObject(memory, old)
            header = struct.pack("<IiiHHIIiiII", 40, self._width, -self._height, 1, 32, 0, 0, 0, 0, 0, 0)
            info = ctypes.create_string_buffer(header+b"\0"*1024)
            pixels = ctypes.create_string_buffer(self._width*self._height*4)
            if not self.g.GetDIBits(memory, bitmap, 0, self._height, pixels, info, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            raw, rows = pixels.raw, []
            for row in range(self._height):
                offset = row*self._width*4
                rows.append(b"\0"+b"".join(bytes((raw[i+2], raw[i+1], raw[i])) for i in range(offset, offset+self._width*4, 4)))

            def chunk(name, data):
                return struct.pack("!I", len(data))+name+data+struct.pack("!I", zlib.crc32(name+data))

            with open(path, "wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack("!2I5B", self._width, self._height, 8, 2, 0, 0, 0))+
                             chunk(b"IDAT", zlib.compress(b"".join(rows)))+chunk(b"IEND", b""))
        finally:
            self.g.SelectObject(memory, old)
            self.g.DeleteObject(bitmap)
            self.g.DeleteDC(memory)
            self.u.ReleaseDC(None, dc)


def request_open_settings():
    u, _g, _k = windows_api()
    shell = u.FindWindowW("Shell_TrayWnd", None)
    if not shell:
        return False
    found = []
    callback_type = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

    @callback_type
    def inspect(hwnd, _parameter):
        if u.GetPropW(hwnd, MAIN_PROPERTY) == 1:
            found.append(bool(u.PostMessageW(hwnd, OPEN_SETTINGS, 0, 0)))
            return False
        return True

    u.EnumChildWindows.argtypes = [W.HWND, callback_type, W.LPARAM]
    u.EnumChildWindows.restype = W.BOOL
    u.EnumChildWindows(shell, inspect, 0)
    return any(found)
