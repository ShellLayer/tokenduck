"""Maintain the taskbar widget's stacking without activation or repainting."""

import ctypes
from ctypes import wintypes as W
import tkinter as tk


def _windows_api():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetAncestor.argtypes = [W.HWND, W.UINT]
    u.GetAncestor.restype = W.HWND
    u.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
    u.FindWindowW.restype = W.HWND
    u.GetWindow.argtypes = [W.HWND, W.UINT]
    u.GetWindow.restype = W.HWND
    u.IsWindowVisible.argtypes = [W.HWND]
    u.IsWindowVisible.restype = W.BOOL
    u.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    u.GetWindowRect.restype = W.BOOL
    u.SetWindowPos.argtypes = [W.HWND, W.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, W.UINT]
    u.SetWindowPos.restype = W.BOOL
    u.UnhookWinEvent.argtypes = [W.HANDLE]
    u.UnhookWinEvent.restype = W.BOOL
    return u


class TaskbarLayerGuard:
    """React to taskbar activity; a cheap fallback also catches silent reorders."""

    INTERVAL_MS = 50

    def __init__(self, root, can_restore):
        self.root = root
        self.can_restore = can_restore
        self.api = _windows_api()
        self.hwnd = self.api.GetAncestor(root.winfo_id(), 2)
        self._closed = True
        self._poll_job = self._event_job = None
        self._hooks = []
        self._callback = None

    def start(self):
        if not self._closed:
            return
        self._closed = False
        callback_type = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND,
                                          W.LONG, W.LONG, W.DWORD, W.DWORD)
        self._callback = callback_type(self._on_event)
        self.api.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, callback_type,
                                             W.DWORD, W.DWORD, W.DWORD]
        self.api.SetWinEventHook.restype = W.HANDLE
        # Out-of-context, skip our own process; observe no keyboard or mouse content.
        for first, last in ((3, 3), (8, 9)):
            hook = self.api.SetWinEventHook(first, last, None, self._callback, 0, 0, 2)
            if hook:
                self._hooks.append(hook)
        self._poll()

    def _on_event(self, _hook, event, hwnd, _object, _child, _thread, _time):
        if self._closed:
            return
        if event != 3:
            shell = self.api.FindWindowW("Shell_TrayWnd", None)
            if not shell or not hwnd or self.api.GetAncestor(hwnd, 2) != shell:
                return
        if self._event_job is None:
            try:
                self._event_job = self.root.after(0, self._event_check)
            except (tk.TclError, RuntimeError):
                pass

    def _event_check(self):
        self._event_job = None
        self.restore_if_needed()

    def _poll(self):
        self._poll_job = None
        if self._closed:
            return
        self.restore_if_needed()
        self._poll_job = self.root.after(self.INTERVAL_MS, self._poll)

    def is_covered(self):
        shell = self.api.FindWindowW("Shell_TrayWnd", None)
        if not shell or not self.api.IsWindowVisible(shell) or not self.api.IsWindowVisible(self.hwnd):
            return False
        widget_rect, shell_rect = W.RECT(), W.RECT()
        if not self.api.GetWindowRect(self.hwnd, ctypes.byref(widget_rect)) or not self.api.GetWindowRect(shell, ctypes.byref(shell_rect)):
            return False
        if (widget_rect.right <= shell_rect.left or widget_rect.left >= shell_rect.right or
                widget_rect.bottom <= shell_rect.top or widget_rect.top >= shell_rect.bottom):
            return False
        previous = self.api.GetWindow(self.hwnd, 3)  # GW_HWNDPREV: higher in Z order.
        for _ in range(512):
            if not previous:
                return False
            if previous == shell:
                return True
            previous = self.api.GetWindow(previous, 3)
        return False

    def restore_if_needed(self):
        if self._closed or not self.is_covered() or not self.can_restore():
            return False
        # NOMOVE | NOSIZE | NOACTIVATE | NOOWNERZORDER. No show/hide or redraw.
        return bool(self.api.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0213))

    def close(self):
        if self._closed:
            return
        self._closed = True
        for name in ("_poll_job", "_event_job"):
            job = getattr(self, name)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        for hook in self._hooks:
            self.api.UnhookWinEvent(hook)
        self._hooks.clear()
