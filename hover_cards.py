"""Passive supplementary tooltip; standard-library Tkinter only."""

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


def make_passive_window(window, click_through=False):
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
        style = style | 0x80020 if click_through else style & ~0x20
        set_style(hwnd, -20, style)
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


def supplemental_content(sections):
    """Project only information that supplements the always-visible taskbar quotas."""
    totals, facts = [], []
    for section in sections:
        months = [w for w in section["windows"] if w.get("tag") == "月"]
        for window in months:
            totals.append({"id": section["id"], "title": section["title"], "color": section["color"],
                           "plan": section.get("plan", ""), "window": deepcopy(window),
                           "error": section.get("error"), "updated": section.get("updated", "")})
        lines = [] if months else [str(section.get("plan") or "")]
        lines.extend(section.get("notes", []))
        if section["id"] == "kimi" and section["windows"] and not months:
            lines.append("暂无月总额度信息")
        if section["id"] == "zcode" and any(
                w.get("tag") == "5h" and ("滚动" in w.get("reset", "") or "5 小时后恢复" in w.get("reset", ""))
                for w in section["windows"]):
            lines.append("5 小时额度按消耗时间恢复")
        error = section.get("error")
        if error:
            message = " ".join(str(error).split())
            lines.append("读取失败：" + (message[:35] + "…" if len(message) > 36 else message))
            if section.get("updated"):
                lines.append(section["updated"])
        lines = [line for line in lines if line]
        if lines:
            facts.append({"id": section["id"], "title": section["title"], "lines": lines, "error": bool(error)})
    totals.sort(key=lambda item: item["id"] != "kimi")
    facts.sort(key=lambda item: not item["error"])
    mode = sections[0].get("display_mode", "remaining") if sections else "remaining"
    return {"totals": totals, "facts": facts, "display_mode": mode}


class QuotaHover(tk.Toplevel):
    """A passive, click-through tooltip for supplementary subscription information."""
    def __init__(self, owner, sections, anchor, light=False, on_dismiss=None):
        super().__init__(owner)
        self.withdraw()
        self.transient(owner)
        self.title("TokenDuck · 补充信息")
        self.overrideredirect(True)
        self.attributes("-toolwindow", True)
        self.attributes("-topmost", True)
        self.palette = PALETTES["light" if light else "dark"]
        self.scale = max(0.8, float(self.tk.call("tk", "scaling")) / (96 / 72))
        self.anchor_rect = anchor
        self.workarea = monitor_workarea(owner)
        self.on_dismiss = on_dismiss
        self._key = "#010203"
        self.configure(bg=self._key)
        self.attributes("-transparentcolor", self._key)
        self.shell = tk.Canvas(self, bg=self._key, bd=0, highlightthickness=0)
        self.shell.pack(fill="both", expand=True)
        self.content = None
        self.update_sections(sections)
        self.bind("<Escape>", lambda _event: self.dismiss())
        self.update_idletasks()
        self._native_position()
        self.deiconify()
        self._native_position()

    def px(self, value):
        return max(1, round(value * self.scale))

    def label(self, parent, text, size=8, weight="normal", color=None, **kwargs):
        options = dict(bg=parent.cget("bg"), fg=color or self.palette["text"],
                       font=("Microsoft YaHei UI", size, weight), bd=0, padx=0, pady=0)
        options.update(kwargs)
        return tk.Label(parent, text=text, **options)

    def update_sections(self, sections):
        model = supplemental_content(sections)
        workarea = monitor_workarea(self.master)
        render_key = (deepcopy(model), dict(self.palette), self.anchor_rect, workarea)
        if self.content is not None and render_key == self._render_key:
            return
        self._render_key = render_key
        self.content_model = model
        self.workarea = workarea
        if self.content is not None:
            self.content.destroy()
        self.shell.delete("all")
        p = self.palette
        margin = self.px(12)
        width = min(self.px(320), workarea[2] - workarea[0] - self.px(16))
        self.inner_width = max(1, width - 2*margin)
        self.content = tk.Frame(self.shell, bg=p["shell"])
        self.shell.create_window(margin, margin, window=self.content, width=self.inner_width, anchor="nw")
        header = tk.Frame(self.content, bg=p["shell"])
        header.pack(fill="x", pady=(0, self.px(10)))
        self.label(header, "补充信息", 10, "bold").pack(side="left")
        kind = "已用额度" if model["display_mode"] == "used" else "剩余额度"
        self.label(header, kind, color=p["muted"]).pack(side="right")
        self.body = tk.Frame(self.content, bg=p["shell"])
        self.body.pack(fill="x")
        self.quota_rows = []
        for index, total in enumerate(model["totals"]):
            self._total(total, index)
        facts = tk.Frame(self.body, bg=p["shell"])
        facts.pack(fill="x")
        if model["totals"] and model["facts"]:
            tk.Frame(facts, bg=p["border"], height=1).pack(fill="x", pady=(self.px(10), self.px(4)))
        footer = tk.Frame(self.content, bg=p["shell"])
        footer.pack(fill="x", pady=(self.px(10), 0))
        self.label(footer, "移开自动收起", color=p["muted"]).pack(side="left")
        more = self.label(footer, "任务栏右键管理", color=p["muted"])
        more.pack(side="right")
        self.visible_facts = self.omitted_facts = 0
        max_content_height = min(self.px(360), workarea[3]-workarea[1]-self.px(16)) - 2*margin
        for fact in model["facts"]:
            row = tk.Frame(facts, bg=p["shell"])
            row.pack(fill="x", pady=(self.px(6), 0))
            row.columnconfigure(0, minsize=self.px(47))
            row.columnconfigure(1, weight=1)
            self.label(row, fact["title"], 9, "bold").grid(row=0, column=0, sticky="nw", padx=(0, self.px(9)))
            self.label(row, "\n".join(fact["lines"]), color=p["warn"] if fact["error"] else p["muted"],
                       wraplength=max(self.px(80), self.inner_width-self.px(60)), justify="left").grid(row=0, column=1, sticky="nw")
            self.content.update_idletasks()
            if self.content.winfo_reqheight() > max_content_height:
                row.destroy()
                self.omitted_facts += 1
            else:
                self.visible_facts += 1
        if self.omitted_facts:
            more.configure(text="更多详情：任务栏右键")
        if not model["totals"] and not model["facts"]:
            self.label(self.body, "暂无补充信息，正在等待额度更新。", color=p["muted"],
                       wraplength=self.inner_width, justify="left").pack(anchor="w")
        self.content.update_idletasks()
        height = self.content.winfo_reqheight()+2*margin
        self.placement = fit_popup(self.anchor_rect, (width, height), workarea, self.px(8))
        x,y,width,height = self.placement
        self.shell.configure(width=width, height=height)
        background = rounded(self.shell, (1,1,width-1,height-1), self.px(12),
                             fill=p["shell"], outline=p["border"], width=1)
        self.shell.tag_lower(background)
        self.geometry("%dx%d+%d+%d" % (width,height,max(0,x),max(0,y)))
        self.update_idletasks()
        if self.winfo_ismapped():
            self._native_position()

    def _total(self, total, index):
        p = self.palette
        win = total["window"]
        row = tk.Frame(self.body, bg=p["shell"])
        row.pack(fill="x", pady=(self.px(10) if index else 0,0))
        title = tk.Frame(row, bg=p["shell"])
        title.pack(fill="x")
        self.label(title, total["title"]+" 月总额度", 9, "bold").pack(side="left")
        stale = bool(total["error"])
        remaining = win["remaining"]
        percent = win.get("display_percent", remaining)
        color = p["muted"] if stale else p["danger"] if remaining<=10 else p["warn"] if remaining<=25 else total["color"]
        value = self.label(title, "%d%%" % percent, 12, "bold", color=p["muted"] if stale else p["text"])
        value.pack(side="right")
        progress = tk.Canvas(row, width=self.inner_width, height=self.px(6), bg=p["shell"], bd=0, highlightthickness=0)
        progress.pack(fill="x", pady=(self.px(5),self.px(5)))
        radius = self.px(3)
        progress.create_line(radius,radius,self.inner_width-radius,radius,
                             fill=p["track"], width=self.px(5), capstyle="round")
        if percent>0:
            progress.create_line(radius,radius,max(radius+.1,(self.inner_width-2*radius)*percent/100+radius),radius,
                                 fill=color,width=self.px(5),capstyle="round")
        meta = tk.Frame(row,bg=p["shell"])
        meta.pack(fill="x")
        meta.columnconfigure(0,weight=1)
        meta.columnconfigure(1,weight=1)
        self.label(meta,win.get("detail",""),color=p["muted"],justify="left",
                   wraplength=self.inner_width//2).grid(row=0,column=0,sticky="nw")
        reset_parts = win["reset"].split(" · ",1)
        timing = (win.get("reset_label","重置于 ")+reset_parts[1]
                  if len(reset_parts)>1 and reset_parts[1][0].isdigit() else win["reset"])
        self.label(meta,timing,color=p["muted"],justify="right",
                   wraplength=self.inner_width//2).grid(row=0,column=1,sticky="ne")
        if win.get("footnote"):
            self.label(row,win["footnote"],color=p["muted"],justify="left",
                       wraplength=self.inner_width).pack(anchor="w",pady=(self.px(4),0))
        plan = total.get("plan","")
        stamp = total.get("updated","")
        if stamp and not stale:
            stamp = "更新 "+stamp.rsplit(" ",1)[-1][:5]
        else:
            stamp = ""
        if plan or stamp:
            note = tk.Frame(row,bg=p["shell"])
            note.pack(fill="x",pady=(self.px(5),0))
            if stamp:
                self.label(note,stamp,color=p["muted"]).pack(side="right")
            self.label(note,plan,color=p["muted"],wraplength=max(1,self.inner_width-self.px(80)),
                       justify="left").pack(side="left")
        self.quota_rows.append({"provider":total["id"],"tag":win.get("tag"),"full_width":True,
                                "row":row,"value":value,"progress":progress,"display_percent":percent})

    def dismiss(self):
        if self.on_dismiss is not None:
            self.on_dismiss()
        else:
            self.destroy()

    def _native_position(self):
        try:
            user32,hwnd = make_passive_window(self,click_through=True)
            if user32 is None:
                return
            user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            # Preserve Tk opacity (including invisible layout tests) and the corner color key.
            alpha = max(0, min(255, round(float(self.attributes("-alpha"))*255)))
            user32.SetLayeredWindowAttributes(hwnd, 0x030201, alpha, 3)
            user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,
                                           ctypes.c_int,ctypes.c_int,wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            x,y,width,height = self.placement
            user32.SetWindowPos(hwnd,-1,x,y,width,height,0x0010)
        except (AttributeError,OSError,tk.TclError):
            pass
