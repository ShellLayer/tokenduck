"""Compact quota cards for the hover flyout; standard-library Tkinter only."""

import ctypes
from copy import deepcopy
from ctypes import wintypes
from datetime import datetime
import math
import tkinter as tk


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


def fit_popup(anchor, size, workarea, gap=8):
    """Keep a flyout inside its anchor monitor, including negative coordinates."""
    left, top, right, bottom = workarea
    margin = min(gap, max(0, (right - left) // 8), max(0, (bottom - top) // 8))
    width = min(size[0], max(1, right - left - 2 * margin))
    height = min(size[1], max(1, bottom - top - 2 * margin))
    x = min(max(anchor[2] - width, left + margin), right - margin - width)
    above = anchor[1] - gap - height
    below = anchor[3] + gap
    y = above if above >= top + margin else below
    y = min(max(y, top + margin), bottom - margin - height)
    return int(x), int(y), int(width), int(height)


def monitor_workarea(owner):
    try:
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user32.MonitorFromWindow(owner.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    except (AttributeError, OSError, tk.TclError):
        pass
    return 0, 0, owner.winfo_screenwidth(), owner.winfo_screenheight()


PALETTES = {
    "dark": {"shell": "#171d28", "card": "#232c3b", "border": "#354257",
             "text": "#edf2fa", "muted": "#a0afc5", "track": "#3b485d",
             "quiet": "#b6c1d2", "good": "#7cddb0", "good_bg": "#203c34",
             "warn": "#f2c67a", "warn_bg": "#453a29", "danger": "#ff9b9b"},
    "light": {"shell": "#f3f6fb", "card": "#ffffff", "border": "#dce3ee",
              "text": "#1d293b", "muted": "#61718a", "track": "#e7edf5",
              "quiet": "#566983", "good": "#237a51", "good_bg": "#e7f4ec",
              "warn": "#92600b", "warn_bg": "#fcf0d9", "danger": "#b93645"},
}


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
        set_style(hwnd, -20, (get_style(hwnd, -20) | 0x08000080) & ~0x00040000)
        return user32, hwnd
    except (AttributeError, OSError, tk.TclError):
        return None, None


def rounded(canvas, bounds, radius, **options):
    x1, y1, x2, y2 = bounds
    r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
              x2, y2-r, x2, y2, x2-r, y2, x1+r, y2,
              x1, y2, x1, y2-r, x1, y1+r, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=32, **options)


class QuotaHover(tk.Toplevel):
    def __init__(self, owner, sections, anchor, light=False, on_enter=None, on_leave=None, on_dismiss=None):
        super().__init__(owner)
        self.withdraw()
        self.transient(owner)
        self.title("TokenDuck · 订阅额度")
        self.overrideredirect(True)
        self.attributes("-toolwindow", True)
        self.attributes("-topmost", True)
        self.palette = PALETTES["light" if light else "dark"]
        self.scale = max(0.8, float(self.tk.call("tk", "scaling")) / (96 / 72))
        self.anchor_rect = anchor
        self.workarea = monitor_workarea(owner)
        self.sections = sections
        self.on_enter, self.on_leave = on_enter, on_leave
        self.on_dismiss = on_dismiss
        self.pinned = False
        self._key = "#010203"
        self.configure(bg=self._key)
        self.attributes("-transparentcolor", self._key)
        self.shell = tk.Canvas(self, bg=self._key, bd=0, highlightthickness=0)
        self.shell.pack(fill="both", expand=True)
        self.content = None
        self.update_sections(sections)
        if on_enter:
            self.bind("<Enter>", lambda _event: on_enter(), add="+")
        if on_leave:
            self.bind("<Leave>", lambda _event: on_leave(), add="+")
        self.bind("<Escape>", lambda _event: self.dismiss())
        self.update_idletasks()
        self._native_position()
        self.deiconify()
        self._native_position()

    def px(self, value):
        return max(1, round(value * self.scale))

    def label(self, parent, text, size=9, weight="normal", color=None, **kwargs):
        options = dict(bg=parent.cget("bg"), fg=color or self.palette["text"],
                       font=("Microsoft YaHei UI", size, weight), bd=0, padx=0, pady=0)
        options.update(kwargs)
        return tk.Label(parent, text=text, **options)

    def update_sections(self, sections):
        workarea = monitor_workarea(self.master)
        render_key = (deepcopy(sections), dict(self.palette), self.anchor_rect, workarea)
        if self.content is not None and render_key == self._render_key:
            return
        self._render_key = render_key
        self.sections = sections
        old_scroll = self.scroller.yview()[0] if self.content is not None else 0
        if self.content is not None:
            self.content.destroy()
        self.shell.delete("all")
        p = self.palette
        self.workarea = workarea
        margin = self.px(14)
        width = min(self.px(380), self.workarea[2] - self.workarea[0] - self.px(16))
        inner_width = max(self.px(180), width - 2 * margin)
        self.content = tk.Frame(self.shell, bg=p["shell"])
        content_window = self.shell.create_window(margin, margin, window=self.content, width=inner_width, anchor="nw")
        header = tk.Frame(self.content, bg=p["shell"])
        header.pack(fill="x", pady=(0, self.px(12)))
        self.label(header, "TokenDuck", 13, "bold").pack(side="left")
        tk.Button(header, text="×", command=self.dismiss, bg=p["shell"], fg=p["muted"],
                  activebackground=p["card"], activeforeground=p["text"], bd=0, relief="flat",
                  font=("Segoe UI", 12), padx=self.px(3), pady=0, takefocus=False).pack(side="right")
        self.pin_note = self.label(header, "订阅额度", color=p["muted"])
        self.pin_note.pack(side="right", padx=(0, self.px(8)), anchor="center")
        body = tk.Frame(self.content, bg=p["shell"])
        body.pack(fill="both", expand=True)
        self.scroller = tk.Canvas(body, bg=p["shell"], bd=0, highlightthickness=0,
                                  width=inner_width)
        self.scroller.pack(side="left", fill="both", expand=True)
        self.cards = tk.Frame(self.scroller, bg=p["shell"])
        card_window = self.scroller.create_window(0, 0, window=self.cards, width=inner_width, anchor="nw")
        self.quota_rows = []
        for index, section in enumerate(sections):
            self._card(section, inner_width, index)
        self.cards.update_idletasks()
        requested = self.cards.winfo_reqheight()
        footer = tk.Frame(self.content, bg=p["shell"])
        footer.pack(fill="x", pady=(self.px(10), 0))
        kind = "已用" if sections and sections[0].get("display_mode") == "used" else "剩余"
        self.label(footer, "百分比均为%s额度" % kind, 8, color=p["muted"]).pack(side="left")
        self.action_hint = self.label(footer, "", 8, color=p["muted"])
        self.action_hint.pack(side="right")
        self.set_pinned(self.pinned)
        header.update_idletasks()
        footer.update_idletasks()
        available = max(self.px(90), self.workarea[3] - self.workarea[1] -
                        2 * margin - header.winfo_reqheight() - footer.winfo_reqheight() - self.px(40))
        viewport = min(requested, available)
        if requested > viewport:
            scrollbar = tk.Scrollbar(body, orient="vertical", command=self.scroller.yview,
                                     bg=p["shell"], troughcolor=p["shell"], width=self.px(10), bd=0)
            scrollbar.pack(side="right", fill="y")
            self.scroller.configure(yscrollcommand=scrollbar.set)
            content_width = inner_width - self.px(12)
            self.scroller.itemconfigure(card_window, width=content_width)
            # Cards keep their measured width; reserve the scroll gutter in the shell.
            width = min(width + self.px(12), self.workarea[2] - self.workarea[0] - self.px(16))
            inner_width = width - 2 * margin
            self.shell.itemconfigure(content_window, width=inner_width)
            self.scroller.itemconfigure(card_window, width=inner_width - self.px(12))
        self.scroller.configure(height=viewport, scrollregion=(0, 0, inner_width, requested))
        self.scroller.yview_moveto(old_scroll)
        self._bind_wheel(self.cards)
        self.scroller.bind("<MouseWheel>", self._wheel)
        self.content.update_idletasks()
        height = self.content.winfo_reqheight() + 2 * margin
        self.placement = fit_popup(self.anchor_rect, (width, height), self.workarea, self.px(8))
        x, y, width, height = self.placement
        self.shell.configure(width=width, height=height)
        rounded(self.shell, (1, 1, width-1, height-1), self.px(15),
                fill=p["shell"], outline=p["border"], width=1)
        self.shell.tag_lower("all")
        # Embedded widgets must remain above the rounded background.
        for item in self.shell.find_all():
            if self.shell.type(item) == "window":
                self.shell.tag_raise(item)
        self.geometry("%dx%d+%d+%d" % (width, height, max(0, x), max(0, y)))
        self.update_idletasks()
        if self.winfo_ismapped():
            self._native_position()

    def _card(self, section, width, index):
        p = self.palette
        outer = tk.Canvas(self.cards, width=width, bd=0, highlightthickness=0, bg=p["shell"])
        outer.pack(fill="x", pady=(0 if index == 0 else self.px(9), 0))
        pad = self.px(13)
        inside = tk.Frame(outer, bg=p["card"])
        outer.create_window(pad, pad, window=inside, width=width - 2*pad, anchor="nw")
        heading = tk.Frame(inside, bg=p["card"])
        heading.pack(fill="x")
        color = section["color"]
        mark = tk.Canvas(heading, width=self.px(26), height=self.px(26), bg=p["card"], bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, self.px(9)))
        rounded(mark, (0, 0, self.px(26), self.px(26)), self.px(7), fill=color, outline="")
        mark.create_text(self.px(13), self.px(13), text=section["title"][0], fill="#ffffff",
                         font=("Segoe UI", 10, "bold"))
        identity = tk.Frame(heading, bg=p["card"])
        self.label(identity, section["title"], 10, "bold").pack(anchor="w")
        if section.get("plan"):
            self.label(identity, str(section["plan"])[:38], 8, color=p["muted"],
                       wraplength=max(self.px(80), width - 2*pad - self.px(115)), justify="left").pack(anchor="w")
        stale = bool(section.get("error"))
        has_windows = bool(section["windows"])
        limited = bool(section.get("limited")) or any(w["remaining"] <= 0 for w in section["windows"])
        status = ("上次记录" if stale and has_windows else "连接异常" if stale else
                  "额度受限" if limited else "已更新" if has_windows else "等待更新")
        status_color = p["warn"] if stale else p["danger"] if limited else p["good"] if has_windows else p["muted"]
        status_bg = p["warn_bg"] if stale or limited else p["good_bg"] if has_windows else p["track"]
        badge = self.label(heading, status, 8, color=status_color, padx=self.px(6), pady=self.px(3))
        badge.configure(bg=status_bg)
        badge.pack(side="right", padx=(self.px(5), 0))
        identity.pack(side="left", fill="x", expand=True)
        grid = tk.Frame(inside, bg=p["card"])
        grid.pack(fill="x", pady=(self.px(12), 0) if has_windows else 0)
        columns = 2 if len(section["windows"]) > 1 else 1
        gutter = self.px(16) if columns == 2 else 0
        quota_width = (width - 2*pad - gutter) // columns
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="quota")
        for index, win in enumerate(section["windows"]):
            row = tk.Frame(grid, bg=p["card"])
            column = index % columns
            row.grid(row=index // columns, column=column, sticky="nsew",
                     padx=(0 if column == 0 else gutter // 2, gutter // 2 if column == 0 and columns > 1 else 0),
                     pady=(0 if index < columns else self.px(12), 0))
            title = tk.Frame(row, bg=p["card"])
            title.pack(fill="x")
            self.label(title, win["label"], 8, color=p["quiet"]).pack(side="left")
            remaining = win["remaining"]
            display_percent = win.get("display_percent", remaining)
            bar_color = p["muted"] if stale else p["danger"] if remaining <= 10 else p["warn"] if remaining <= 25 else color
            value = self.label(title, "%d%%" % display_percent, 12, "bold", color=p["muted"] if stale else p["text"])
            value.pack(side="right")
            progress = tk.Canvas(row, height=self.px(6), bg=p["card"], bd=0, highlightthickness=0)
            progress.pack(fill="x", pady=(self.px(5), self.px(5)))
            progress_width = quota_width
            radius = self.px(3)
            progress.create_line(radius, radius, progress_width-radius, radius,
                                 fill=p["track"], width=self.px(5), capstyle="round")
            if display_percent > 0:
                progress.create_line(radius, radius, max(radius + 0.1, (progress_width-2*radius)*display_percent/100+radius), radius,
                                     fill=bar_color, width=self.px(5), capstyle="round")
            reset_parts = win["reset"].split(" · ", 1)
            self.label(row, reset_parts[0], 8, color=p["muted"],
                       wraplength=quota_width, justify="left").pack(anchor="w")
            if len(reset_parts) > 1:
                exact = reset_parts[1]
                self.label(row, ("重置于 " if exact[0].isdigit() else "") + exact, 8,
                           color=p["muted"], wraplength=quota_width, justify="left").pack(anchor="w", pady=(self.px(2), 0))
            if win.get("detail"):
                self.label(row, win["detail"], 8, color=p["muted"]).pack(anchor="w", pady=(self.px(2), 0))
            self.quota_rows.append({"provider": section["id"], "value": value, "row": row,
                                    "progress": progress, "display_percent": display_percent})
        if not has_windows:
            self.label(inside, "暂未获取到额度", 9, color=p["muted"]).pack(anchor="w", pady=(self.px(12), self.px(2)))
        for note in section.get("notes", []):
            self.label(inside, note, 8, color=p["muted"], justify="left",
                       wraplength=width - 2*pad).pack(anchor="w", pady=(self.px(7), 0))
        if stale:
            error = " ".join(str(section["error"]).split())
            if len(error) > 120:
                error = error[:117] + "…"
            self.label(inside, error, 8, color=p["warn"], justify="left",
                       wraplength=width - 2*pad).pack(anchor="w", pady=(self.px(8), 0))
        if section.get("updated"):
            self.label(inside, section["updated"], 8, color=p["muted"]).pack(anchor="w", pady=(self.px(9), 0))
        inside.update_idletasks()
        height = inside.winfo_reqheight() + 2*pad
        outer.configure(height=height)
        background = rounded(outer, (1, 1, width-1, height-1), self.px(11), fill=p["card"], outline=p["border"])
        outer.tag_lower(background)

    def set_pinned(self, pinned):
        self.pinned = bool(pinned)
        self.pin_note.configure(text="已固定" if self.pinned else "订阅额度")
        self.action_hint.configure(text="再次左键收起" if self.pinned else "左键固定 · 右键菜单")

    def dismiss(self):
        if self.on_dismiss is not None:
            self.on_dismiss()
        else:
            self.destroy()

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._wheel, add="+")
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self.scroller.yview_scroll(delta * 3, "units")
        return "break"

    def _native_position(self):
        try:
            user32, hwnd = make_passive_window(self)
            if user32 is None:
                return
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            x, y, width, height = self.placement
            user32.SetWindowPos(hwnd, -1, x, y, width, height, 0x0010)
        except (AttributeError, OSError, tk.TclError):
            pass
