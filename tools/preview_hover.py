"""Preview hover cards with synthetic data, without opening account files or networking.

F2: dark, F3: light, F4: stale, F5: used, F6: remaining, F7: pin, Escape: close.
"""

from pathlib import Path
import sys
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hover_cards import PALETTES, QuotaHover
from tokenduck import DEFAULT_CONFIG, TokenDuck


def sample_sections(stale=False, mode="remaining"):
    now = time.time()
    bar = TokenDuck.__new__(TokenDuck)
    bar.cfg = dict(DEFAULT_CONFIG, quota_display=mode)
    bar.data = {"plan_type": "plus", "rate_limit": {
        "primary_window": {"used_percent": 18, "limit_window_seconds": 18000, "reset_at": now+8100},
        "secondary_window": {"used_percent": 36, "limit_window_seconds": 604800, "reset_at": now+384000}}}
    bar.kimi_data = {"level": "Kimi Moderato", "windows": [
        {"tag": "5h", "used_percent": 0, "reset_at": now+17700},
        {"tag": "w", "used_percent": 0, "reset_at": now+527000}],
        "used_ratio": 0.15, "amount": 10000000, "amount_left": 8500000}
    bar.zcode_data = {"plan_name": "GLM Coding Plan · Pro", "windows": [
        {"tag": "5h", "used_percent": 24, "reset_at": now+12600},
        {"tag": "w", "used_percent": 9, "reset_at": now+440000}], "until": now+86400*22}
    bar.error = bar.zcode_error = None
    bar.kimi_error = "网络暂时不可用，当前显示上次记录" if stale else None
    bar.last_success = {name: now - (900 if stale and name == "kimi" else 40)
                        for name in ("codex", "kimi", "zcode")}
    return bar.hover_sections(now)


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.title("TokenDuck preview controls")
    root.geometry("280x110+1020+45")
    tk.Label(root, text="示例数据 · F2 深色 / F3 浅色\nF4 旧数据 · F5 已用 / F6 剩余\nF7 固定卡片 · Esc 退出", padx=15, pady=15).pack()
    root.update()
    # A normal titled preview window makes the synthetic layout easy to inspect.
    # Production flyouts keep their tool-window and no-activation styles.
    QuotaHover._native_position = lambda self: None
    current = [None]
    state = {"light": False, "stale": False, "mode": "remaining"}

    def show(light=None, stale=None, mode=None):
        state.update({key: value for key, value in (("light", light), ("stale", stale), ("mode", mode)) if value is not None})
        light, stale, mode = state["light"], state["stale"], state["mode"]
        if current[0] is not None:
            tip = current[0]
            tip.palette = PALETTES["light" if light else "dark"]
            tip.update_sections(sample_sections(stale, mode))
        else:
            tip = QuotaHover(root, sample_sections(stale, mode), (560, 1000, 940, 1048), light=light, on_dismiss=root.destroy)
            tip.transient("")
            tip.overrideredirect(False)
            tip.attributes("-toolwindow", False)
        tip.title("TokenDuck preview · sample data · " + ("light" if light else "dark"))
        _, _, width, height = tip.placement
        tip.geometry("%dx%d+560+45" % (width, height))
        tip.deiconify()
        tip.protocol("WM_DELETE_WINDOW", root.destroy)
        tip.bind("<F2>", lambda _e: show())
        tip.bind("<F3>", lambda _e: show(light=True))
        tip.bind("<F4>", lambda _e: show(stale=True))
        tip.bind("<F5>", lambda _e: show(mode="used"))
        tip.bind("<F6>", lambda _e: show(mode="remaining"))
        tip.bind("<F7>", lambda _e: tip.set_pinned(not tip.pinned))
        tip.bind("<Escape>", lambda _e: root.destroy())
        current[0] = tip
        root.update_idletasks()

    show()
    root.after(300000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
