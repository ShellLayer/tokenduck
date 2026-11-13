"""Read-only subscription details for the taskbar context menu."""

import ctypes
from ctypes import wintypes
from datetime import datetime
import math
import tkinter as tk
import unicodedata


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def reset_caption(reset_at, now):
    stamp = number(reset_at)
    if stamp is None or stamp <= 0:
        return "重置时间暂未提供"
    try:
        exact = datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return "重置时间暂未提供"
    seconds = stamp - now
    if seconds <= 0:
        return "重置时间已到 · 等待刷新"
    minutes = max(1, math.ceil(seconds / 60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        duration = "%d天%s" % (days, "%d小时" % hours if hours else "")
    elif hours:
        duration = "%d小时%s" % (hours, "%d分" % minutes if minutes else "")
    else:
        duration = "%d分钟" % minutes
    return "%s后重置 · %s" % (duration, exact)


def make_passive_window(window):
    """Keep an informational window out of mouse-activation and task switching."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(window.winfo_id(), 2)
        get_style = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
        set_style = user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.SetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        style = (get_style(hwnd, -20) | 0x08000080) & ~0x00040000
        style &= ~0x20
        set_style(hwnd, -20, style)
        return user32, hwnd
    except (AttributeError, OSError, tk.TclError):
        return None, None


def _short_plan(provider, text):
    text = str(text or "")
    for prefix in {"codex": ("ChatGPT ",), "kimi": ("Kimi ",),
                   "zcode": ("GLM Coding Plan", "Coding Plan", "GLM", "ZCode")}.get(provider, ()):
        text = text.removeprefix(prefix).strip(" ·:-")
    return text


def _menu_label(text):
    text = " ".join(str(text).split())
    width = 0
    for index, char in enumerate(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width > 64:
            return text[:index] + "…"
    return text


def subscription_menu_rows(sections):
    """Return (text, heading) rows and separators, without any login fields."""
    rows = []
    for section in sorted(sections, key=lambda s: s["id"] != "kimi"):
        provider = section["id"]
        windows = section["windows"]
        months = [w for w in windows if w.get("tag") == "月"]
        plan = _short_plan(provider, section.get("plan"))
        title = "GLM / ZCode" if provider == "zcode" else section["title"]
        suffix = plan or ("已连接" if windows else "等待获取")
        if section.get("error") and windows:
            suffix += "（旧读数）"
        rows.append((_menu_label(title + " · " + suffix), True))
        kind = "已用" if section.get("display_mode") == "used" else "剩余"
        for window in months:
            percent = window.get("display_percent", window["remaining"])
            line = "月总额度：%s %d%%" % (kind, percent)
            detail = window.get("detail", "").removeprefix(kind+" ")
            if detail:
                line += " · " + detail
            rows.append((_menu_label(line), False))
            rows.append((_menu_label(window["reset"]), False))
            if window.get("footnote"):
                rows.append((_menu_label(window["footnote"]), False))
        if provider == "kimi" and windows and not months:
            rows.append(("月总额度：暂无数据", False))
        for note in section.get("notes", []):
            rows.append((_menu_label(note), False))
        if provider == "zcode" and any(w.get("tag") == "5h" and
                ("滚动" in w.get("reset", "") or "消耗 5 小时后恢复" in w.get("reset", "")) for w in windows):
            rows.append(("5 小时额度按消耗时间动态恢复", False))
        if section.get("error"):
            rows.append((_menu_label("读取失败：" + str(section["error"])), False))
            if section.get("updated"):
                rows.append((_menu_label(section["updated"]), False))
        rows.append(None)
    return rows
