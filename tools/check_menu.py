"""Check the real Tk menu without posting it or capturing the screen."""

import ctypes
import json
from pathlib import Path
import sys
import time
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tokenduck import DEFAULT_CONFIG, TokenDuck


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    bar = TokenDuck(dict(DEFAULT_CONFIG), hidden=True)
    reports = []
    try:
        now = time.time()
        bar.data = {"plan_type": "plus", "credits": {"has_credits": True, "balance": 20}}
        bar.kimi_data = {"level": "Kimi Moderato", "used_ratio": .15, "amount": 10000000,
                         "amount_left": 8500000, "code_used_ratio": .05, "reset_at": now+86400*21,
                         "windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 0}]}
        bar.zcode_data = {"plan_name": "GLM Coding Plan · Pro", "until": now+86400*22,
                          "windows": [{"tag": "5h", "used_percent": 24}]}
        bar.last_success = {name: now-900 for name in ("codex", "kimi", "zcode")}
        for scaling, mode, stale in ((96/72, "remaining", False), (96/72, "used", False),
                                     (2.0, "remaining", True)):
            bar.root.tk.call("tk", "scaling", scaling)
            bar.cfg["quota_display"] = mode
            bar.kimi_error = "网络暂时不可用，当前显示上次记录" if stale else None
            bar.update_menu_details()
            count = bar.menu.index("end")+1
            labels = [bar.menu.entrycget(i, "label") for i in range(count) if bar.menu.type(i) == "command"]
            assert sum(label == "立即刷新" for label in labels) == 1
            assert sum("月总额度：" in label for label in labels) == 1
            assert any("最后成功更新" in label for label in labels) == stale
            assert not bar.canvas.bind("<Enter>") and not bar.canvas.bind("<Leave>")
            assert not bar.canvas.bind("<Button-1>")
            widths = []
            for i in range(bar._menu_detail_count):
                if bar.menu.type(i) != "command":
                    continue
                assert bar.menu.entrycget(i, "state") == "disabled"
                assert not bar.menu.entrycget(i, "command")
                font = tkfont.Font(root=bar.root, font=bar.menu.entrycget(i, "font"))
                widths.append(font.measure(bar.menu.entrycget(i, "label")))
            scale = float(bar.root.tk.call("tk", "scaling"))/(96/72)
            assert max(widths) <= round(420*scale)
            reports.append({"mode": mode, "stale": stale, "scale": round(scale, 2),
                            "detail_rows": bar._menu_detail_count, "max_text_width": max(widths)})
        print(json.dumps({"menu_checks": reports, "popup_posted": False, "screen_capture_used": False}))
    finally:
        bar.quit()


if __name__ == "__main__":
    main()
