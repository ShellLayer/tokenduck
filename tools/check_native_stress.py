"""Stress queued UI updates, native child recreation and dialog cleanup offline."""

import faulthandler
import gc
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tokenduck import DEFAULT_CONFIG, TokenDuck


def main():
    Path("build").mkdir(exist_ok=True)
    fault = open("build/native-stress-fault.log", "a", encoding="utf-8")
    faulthandler.enable(file=fault, all_threads=True)
    bar = TokenDuck(dict(DEFAULT_CONFIG), hidden=True)
    done = threading.Event()
    count, recreated = [0], [0]
    target = 1200
    started = time.monotonic()

    def update(index):
        bar.data = {"rate_limit": {"primary_window": {"used_percent": index % 100, "limit_window_seconds": 18000}}}
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": (index+20) % 100}]}
        bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": (index+40) % 100}]}
        if index % 80 == 0:
            bar.show_display_settings(hidden=True)
            bar._settings_mode_buttons["used" if index % 160 else "remaining"].invoke()
            bar._settings_window.destroy()
        bar.render()
        if index % 40 == 0:
            bar.canvas.u.DestroyWindow(bar.canvas.hwnd)
            bar.canvas.ensure_window(force=True)
            recreated[0] += 1
        count[0] += 1

    def worker():
        for index in range(target):
            bar._post_ui(lambda index=index: update(index))
            if index % 20 == 0:
                gc.collect()
                time.sleep(.003)
        done.set()

    thread = threading.Thread(target=worker, daemon=True)

    def watch():
        if done.is_set() and count[0] == target:
            bar.root.quit()
        elif time.monotonic()-started > 40:
            bar.root.quit()
        else:
            bar.root.after(100, watch)

    try:
        thread.start()
        bar.root.after(0, bar._native_tick)
        bar.root.after(100, watch)
        bar.root.mainloop()
        thread.join(timeout=2)
        assert count[0] == target, count
        assert bar.root.winfo_exists() and bar.canvas.hwnd
        print(json.dumps({"queued_updates": count[0], "native_child_recreations": recreated[0],
                          "dialog_cycles": target//80, "worker_gc": True,
                          "quota_requests": 0, "screen_capture_used": False}))
    finally:
        bar.quit()
        faulthandler.disable()
        fault.close()


if __name__ == "__main__":
    main()
