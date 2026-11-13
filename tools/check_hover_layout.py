"""Check real Tk layout with synthetic data and transparent windows; no screen capture."""

import ctypes
import json
from pathlib import Path
import sys
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hover_cards import QuotaHover, make_passive_window
from tools.preview_hover import sample_sections


class InvisibleHover(QuotaHover):
    def deiconify(self):
        self.attributes("-alpha", 0.0)
        return super().deiconify()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.attributes("-toolwindow", True)
    root.attributes("-alpha", 0.0)
    root.geometry("1x1+0+0")
    make_passive_window(root)
    root.update()
    reports = []
    try:
        cases = ((96/72, "remaining", False, False),
                 (96/72, "used", True, False),
                 (2.0, "remaining", False, True))
        for scaling, mode, light, stale in cases:
            root.tk.call("tk", "scaling", scaling)
            sections = sample_sections(stale, mode)
            month = next(w for w in sections[1]["windows"] if w["tag"] == "月")
            month["reset"] = "21天后重置 · 12-05 20:00"
            month["footnote"] = "其中 Kimi Code 消耗月总额度的 5%"
            card = InvisibleHover(root, sections, (560, 1000, 940, 1048), light=light)
            root.update()
            monthly = next(r for r in card.quota_rows if r["provider"] == "kimi" and r["tag"] == "月")
            assert len(card.quota_rows) == 1
            assert all(r["tag"] == "月" for r in card.quota_rows)
            for row in card.quota_rows:
                value = row["value"]
                label = next(w for w in value.master.winfo_children() if w is not value)
                assert label.winfo_rootx() + label.winfo_width() + 2 <= value.winfo_rootx(), (row["provider"], row["tag"])
                assert row["detail"].winfo_rootx() + row["detail"].winfo_width() + 2 <= row["timing"].winfo_rootx()
                assert "…" not in row["detail"].cget("text")
                assert row["timing"].cget("text") == "12-05 重置"
                for item in row["progress"].find_all():
                    coordinates = row["progress"].coords(item)
                    assert max(coordinates[0], coordinates[2]) <= row["progress"].winfo_width() + 1
            x, y, width, height = card.placement
            left, top, right, bottom = card.workarea
            assert left <= x and top <= y and x+width <= right and y+height <= bottom
            assert width <= card.px(260)
            assert height <= card.px(220 if stale else 160)
            for label in card.fact_labels:
                assert label.winfo_rootx() + label.winfo_width() <= x+width-card.px(10)+1
                assert "\n" not in label.cget("text")
                if not stale:
                    assert "…" not in label.cget("text")
            if stale:
                assert any("上次更新" in label.cget("text") for label in card.fact_labels)
            reports.append({"mode": mode, "light": light, "scale": round(card.scale, 2),
                            "size": [width, height], "monthly_width": monthly["row"].winfo_width(),
                            "visible_facts": card.visible_facts, "omitted_facts": card.omitted_facts})
            card.destroy()
        print(json.dumps({"layout_checks": reports, "screen_capture_used": False}))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
