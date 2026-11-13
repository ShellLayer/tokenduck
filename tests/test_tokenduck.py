"""离线行为测试：不读取真实登录凭证，不访问网络，不创建桌面窗口。"""

import base64
import io
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import tokenduck as app


FUTURE = "2099-11-13T10:00:00Z"


def token(exp, user="test-user"):
    claims = json.dumps({"exp": exp, "sub": user}).encode()
    payload = base64.urlsafe_b64encode(claims).decode().rstrip("=")
    return "test." + payload + ".test"


def session(exp=None):
    return {"_来源": "独立会话（自动绑定）",
            "access_token": token(exp if exp is not None else time.time() + 3600),
            "refresh_token": "synthetic-refresh"}


def full_quota():
    # ProtoJSON 在零用量时可省略 ratio，而 enabled 和 resetTime 仍存在。
    return {"ratelimitCode5h": {"enabled": True, "resetTime": FUTURE},
            "ratelimitCode7d": {"enabled": True, "resetTime": FUTURE}}


class KimiQuotaTests(unittest.TestCase):
    def test_unused_enabled_windows_show_100_percent_remaining(self):
        data = app._parse_kimi_web_quota(full_quota())
        windows = app._display_windows("kimi", data)
        self.assertEqual([w["tag"] for w in windows], ["5h", "w"])
        self.assertEqual([app._remain(w["used_percent"]) for w in windows], [100, 100])

    def test_explicit_zero_is_not_missing(self):
        data = app._parse_kimi_web_quota({"ratelimitCode5h": {"ratio": 0}})
        self.assertEqual(data["windows"][0]["used_percent"], 0)

    def test_reset_metadata_also_identifies_zero_usage_window(self):
        data = app._parse_kimi_web_quota({"ratelimitCode5h": {"resetTime": FUTURE}})
        self.assertEqual(data["windows"][0]["used_percent"], 0)

    def test_disabled_empty_and_invalid_windows_are_not_fabricated_as_full(self):
        for window in ({}, {"enabled": False}, {"ratio": None},
                       {"enabled": True, "ratio": "nan"},
                       {"enabled": True, "ratio": None}):
            with self.subTest(window=window), self.assertRaises(RuntimeError):
                app._parse_kimi_web_quota({"ratelimitCode5h": window})

    def test_missing_response_is_not_full_quota(self):
        for data in ({}, None, []):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                app._parse_kimi_web_quota(data)

    def test_monthly_only_membership_shows_on_taskbar(self):
        data = app._parse_kimi_web_quota({
            "subscriptionBalance": {"amount": "100", "amountLeft": "100"}})
        windows = app._display_windows("kimi", data)
        self.assertEqual(windows[0]["tag"], "月")
        self.assertEqual(app._remain(windows[0]["used_percent"]), 100)

    def test_active_monthly_subscription_can_omit_zero_ratio(self):
        data = app._parse_kimi_web_quota({"subscriptionBalance": {"expireTime": FUTURE}})
        self.assertEqual(data["used_ratio"], 0)
        self.assertEqual(app._remain(app._display_windows("kimi", data)[0]["used_percent"]), 100)

    def test_expired_subscription_does_not_default_to_full(self):
        with self.assertRaises(RuntimeError):
            app._parse_kimi_web_quota({"subscriptionBalance": {"expireTime": "2000-01-01T00:00:00Z"}})

    def test_snake_case_web_response(self):
        data = app._parse_kimi_web_quota({
            "ratelimit_code_5h": {"ratio": 0.25, "reset_time": FUTURE},
            "subscription_balance": {"amount_used_ratio": 0.4}})
        self.assertEqual(data["windows"][0]["used_percent"], 25)
        self.assertEqual(data["used_ratio"], 0.4)

    def test_legacy_api_keeps_short_and_weekly_windows_and_converts_minutes(self):
        data = app._parse_kimi_api_quota({
            "usage": {"limit": "100", "used": "80", "resetTime": FUTURE},
            "limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                        "detail": {"limit": "100", "used": "20", "resetTime": FUTURE}}]})
        self.assertEqual([(w["tag"], w["secs"], w["used_percent"]) for w in data["windows"]],
                         [("5h", 18000, 20), ("w", 604800, 80)])

    def test_legacy_api_zero_used_can_be_derived_from_remaining(self):
        data = app._parse_kimi_api_quota({"usage": {"limit": "100", "remaining": "100"}})
        self.assertEqual(app._remain(data["windows"][0]["used_percent"]), 100)

    def test_new_ratio_api_supports_short_weekly_and_monthly(self):
        data = app._parse_kimi_api_quota({"usages": {
            "limit_5h": {"used_ratio": 0, "reset_time": FUTURE},
            "limit_7d": {"used_ratio": 0.4, "reset_time": FUTURE},
            "limit_month_total": {"used_ratio": 0.2, "reset_time": FUTURE},
            "limit_month_code": {"used_ratio": 0.1}}})
        self.assertEqual([w["used_percent"] for w in data["windows"]], [0, 40])
        self.assertEqual(data["used_ratio"], 0.2)
        self.assertEqual(data["code_used_ratio"], 0.1)

    def test_new_plan_displays_short_and_month_when_weekly_absent(self):
        data = app._parse_kimi_api_quota({"usages": {
            "limit_5h": {"used_ratio": 0}, "limit_month_total": {"used_ratio": 0}}})
        self.assertEqual([w["tag"] for w in app._display_windows("kimi", data)], ["5h", "月"])

    def test_counter_takes_precedence_over_zeroed_ratio(self):
        data = app._parse_kimi_api_quota({
            "usage": {"limit": "100", "used": "80"},
            "usages": {"limit_7d": {"used_ratio": 0}}})
        self.assertEqual(data["windows"][0]["used_percent"], 80)

    def test_wrapped_new_api_response(self):
        data = app._parse_kimi_api_quota({"code": 0, "data": {"kind": "ok", "quota": {
            "usages": {"limit5h": {"usedRatio": 0.3, "resetAt": FUTURE}}}}})
        self.assertEqual(data["windows"][0]["used_percent"], 30)

    def test_unknown_api_payload_is_an_error(self):
        with self.assertRaises(RuntimeError):
            app._parse_kimi_api_quota({"message": "unavailable"})


class KimiSessionTests(unittest.TestCase):
    def setUp(self):
        self.creds = session()
        self.read = patch.object(app, "_read_kimi_web_cred", return_value=self.creds).start()
        self.store = patch.object(app, "ACCOUNT_STORE").start()
        self.store.get.return_value = None
        self.refresh = patch.object(app, "_kimi_web_refresh", return_value=session()).start()
        self.bind = patch.object(app, "_bind_kimi_web", return_value=session()).start()
        self.discard = patch.object(app, "_discard_kimi_web_cred").start()
        self.post = patch.object(app, "_connect_post", return_value=full_quota()).start()
        self.addCleanup(patch.stopall)

    def test_valid_saved_session_does_not_need_browser(self):
        self.assertEqual(len(app._fetch_kimi_by_web()["windows"]), 2)
        self.bind.assert_not_called()
        self.refresh.assert_not_called()

    def test_expired_access_token_renews_independent_session(self):
        self.read.return_value = session(time.time() - 100)
        app._fetch_kimi_by_web(timeout=3)
        self.refresh.assert_called_once_with(self.read.return_value, 3)
        self.bind.assert_not_called()

    def test_rejected_refresh_recovers_from_browser(self):
        self.read.return_value = session(time.time() - 100)
        self.refresh.side_effect = app.KimiAuthError("revoked")
        self.assertEqual(len(app._fetch_kimi_by_web()["windows"]), 2)
        self.discard.assert_called_once()
        self.bind.assert_called_once()

    def test_network_failure_keeps_saved_session(self):
        self.read.return_value = session(time.time() - 100)
        self.refresh.side_effect = RuntimeError("network timeout")
        with self.assertRaisesRegex(RuntimeError, "network timeout"):
            app._fetch_kimi_by_web()
        self.discard.assert_not_called()
        self.bind.assert_not_called()

    def test_newly_bound_independent_session_retries_401_by_refreshing(self):
        self.read.return_value = None
        error = HTTPError("https://example.invalid", 401, "unauthorized", {}, None)
        self.addCleanup(error.close)
        self.post.side_effect = [error, full_quota()]
        app._fetch_kimi_by_web()
        self.bind.assert_called_once()
        self.refresh.assert_called_once()
        self.assertEqual(self.post.call_count, 2)

    def test_repeated_401_is_bounded_and_clears_invalid_session(self):
        error = HTTPError("https://example.invalid", 401, "unauthorized", {}, None)
        self.addCleanup(error.close)
        self.post.side_effect = error
        with self.assertRaises(app.KimiAuthError):
            app._fetch_kimi_by_web()
        self.assertEqual(self.post.call_count, 2)
        self.discard.assert_called_once()

class Canvas:
    def __init__(self):
        self.items = {}

    def itemconfig(self, item, **kwargs):
        self.items.setdefault(item, {}).update(kwargs)

    def coords(self, item, *args):
        self.items.setdefault(item, {})["coords"] = args


class Font:
    def metrics(self, _):
        return 16

    def measure(self, text):
        return len(text) * 5


class Root:
    def geometry(self, _):
        pass

    def after(self, delay, callback):
        pass


class User32:
    def FindWindowW(self, *args):
        return 1

    def FindWindowExW(self, *args):
        return 0

    def GetWindowRect(self, handle, rect):
        rect._obj.left, rect._obj.top = 0, 1032
        rect._obj.right, rect._obj.bottom = 1920, 1080
        return 1


def bare_bar():
    bar = app.TokenDuck.__new__(app.TokenDuck)
    bar.cfg = dict(app.DEFAULT_CONFIG)
    bar.root, bar.canvas = Root(), Canvas()
    bar.data = {"rate_limit": {"primary_window": {
        "used_percent": 0, "limit_window_seconds": 18000, "reset_at": time.time() + 3600}}}
    bar.kimi_data = app._parse_kimi_web_quota(full_quota())
    bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 50}]}
    bar.error = bar.kimi_error = bar.zcode_error = None
    bar.last_success = {name: time.time() - 600 for name in ("codex", "kimi", "zcode")}
    bar.last_refresh = None
    bar.stop_event, bar.fetch_lock = threading.Event(), threading.Lock()
    bar.width, bar.chip = 190, None
    bar.font = bar.font_seg = bar.font_top = bar.font_cd = Font()
    bar.label_w, bar.seg_w, bar.bars_zone = 30, 70, 143
    bar.row_items = [(f"label{i}", f"main{i}", f"timer{i}") for i in range(3)]
    bar.bars = [[(f"bg{i}-{j}", f"fg{i}-{j}") for j in range(2)] for i in range(3)]
    bar.seg_texts = [[f"pct{i}-{j}" for j in range(2)] for i in range(3)]
    bar.seg_timers = [[f"cd{i}-{j}" for j in range(2)] for i in range(3)]
    bar.fg, bar.muted_color = "#ffffff", "#888888"
    bar._safe_lift = lambda: None
    bar._interaction_active = lambda: False
    bar._apply_font_size = lambda: None
    return bar


class DisplayTests(unittest.TestCase):
    def test_glm_full_state_and_weekly_countdown_both_remain_visible(self):
        for mode, expected in (("remaining", "已满"), ("used", "未用")):
            bar = bare_bar()
            bar.cfg["quota_display"] = mode
            bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                          {"tag": "w", "used_percent": 20, "reset_at": time.time()+7200}]}
            with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
                bar.render()
            self.assertEqual(bar.canvas.items["cd2-0"]["text"], expected)
            self.assertEqual(bar.canvas.items["cd2-0"]["state"], "normal")
            self.assertEqual(bar.canvas.items["cd2-1"]["state"], "normal")
            self.assertIn("h", bar.canvas.items["cd2-1"]["text"])

    def test_glm_missing_recovery_shows_rolling_or_stale_state(self):
        for error, expected in ((None, "滚动"), ("offline", "待刷新")):
            bar = bare_bar()
            bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 25}]}
            bar.zcode_error = error
            with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
                bar.render()
            self.assertEqual(bar.canvas.items["cd2-0"]["text"], expected)
            self.assertEqual(bar.canvas.items["cd2-0"]["state"], "normal")
            if error:
                self.assertEqual(bar.canvas.items["cd2-0"]["fill"], bar.muted_color)

    def test_used_mode_changes_visible_number_and_bar_fill_together(self):
        bar = bare_bar()
        bar.cfg["quota_display"] = "used"
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 25}]}
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        self.assertEqual(bar.canvas.items["pct1-0"]["text"], "25%")
        self.assertEqual(bar.canvas.items["label1"]["text"], "kimi 用")
        x0, _, x1, _ = bar.canvas.items["bg1-0"]["coords"]
        fx0, _, fx1, _ = bar.canvas.items["fg1-0"]["coords"]
        self.assertAlmostEqual((fx1-fx0)/(x1-x0), .25, delta=.01)
        self.assertEqual(bar.kimi_data["windows"][0]["used_percent"], 25)

    def test_unused_quota_in_used_mode_is_visible_zero_not_missing(self):
        bar = bare_bar()
        bar.cfg["quota_display"] = "used"
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        self.assertEqual(bar.canvas.items["pct1-0"]["text"], "0%")
        self.assertEqual(bar.canvas.items["pct1-0"]["state"], "normal")
        x0, _, x1, _ = bar.canvas.items["fg1-0"]["coords"]
        self.assertEqual(x0, x1)

    def test_low_remaining_stays_red_in_used_mode(self):
        bar = bare_bar()
        bar.cfg["quota_display"] = "used"
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 98}]}
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        self.assertEqual(bar.canvas.items["pct1-0"]["text"], "98%")
        self.assertEqual(bar.canvas.items["fg1-0"]["fill"], "#e74c3c")

    def test_full_quota_actually_renders_as_100_percent(self):
        bar = bare_bar()
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        self.assertEqual(bar.canvas.items["pct1-0"]["text"], "100%")
        self.assertEqual(bar.canvas.items["pct1-1"]["text"], "100%")
        self.assertEqual(bar.canvas.items["pct1-0"]["state"], "normal")

    def test_failed_refresh_mutes_visible_numbers_timers_and_bars(self):
        bar = bare_bar()
        bar.kimi_error = "network timeout"
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        for item in ("pct1-0", "cd1-0", "fg1-0"):
            self.assertEqual(bar.canvas.items[item]["fill"], bar.muted_color)
        self.assertEqual(bar.canvas.items["label1"]["text"], "kimi 余*")
        self.assertEqual(bar.subscription_sections()[1]["error"], "network timeout")

    def test_missing_percent_does_not_shift_reset_onto_another_window(self):
        bar = bare_bar()
        bar.data = {"rate_limit": {
            "primary_window": {"used_percent": None, "reset_at": 100},
            "secondary_window": {"used_percent": 20, "reset_at": 200, "limit_window_seconds": 604800}}}
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.render()
        self.assertEqual(bar.seg_resets[0], [200])

    def test_failure_preserves_last_success_and_cached_quota(self):
        bar = bare_bar()
        old_data, old_success = bar.kimi_data, dict(bar.last_success)
        with patch.object(app, "fetch_usage", side_effect=RuntimeError("offline")), \
             patch.object(app, "fetch_kimi_quota", side_effect=RuntimeError("offline")), \
             patch.object(app, "fetch_zcode_quota", side_effect=RuntimeError("offline")), \
             patch.object(app, "save_usage_cache") as save:
            bar.fetch_once()
        self.assertIs(bar.kimi_data, old_data)
        self.assertEqual(bar.last_success, old_success)
        self.assertEqual(save.call_args.args[0]["kimi"]["saved_at"], old_success["kimi"])

    def test_rebind_waits_for_active_refresh_without_blocking_ui(self):
        bar = bare_bar()
        old_data = bar.kimi_data
        completed = threading.Event()
        bar.root.after = lambda *args: completed.set()
        bar.fetch_lock.acquire()
        replacement = app._parse_kimi_web_quota(full_quota())
        with patch.object(app.ACCOUNT_STORE, "update") as remove, \
             patch.object(bar, "_save_cache"), \
             patch.object(app, "connect_kimi_account", return_value=replacement):
            try:
                bar.rebind_kimi()
                self.assertIs(bar.kimi_data, old_data)
                remove.assert_not_called()
            finally:
                bar.fetch_lock.release()
            self.assertTrue(completed.wait(2), "rebind worker did not finish")
        self.assertIs(bar.kimi_data, replacement)
        self.assertIsNone(bar.kimi_error)

    def test_rebind_does_not_discard_data_if_credential_delete_fails(self):
        bar = bare_bar()
        old_data, old_success = bar.kimi_data, dict(bar.last_success)
        completed = threading.Event()
        bar.root.after = lambda *args: completed.set()
        with patch.object(app, "connect_kimi_account", side_effect=app.CredentialStoreError("denied")), \
             patch.object(bar, "_save_cache") as save, \
             patch.object(app, "fetch_kimi_quota") as fetch:
            bar.rebind_kimi()
            self.assertTrue(completed.wait(2), "rebind worker did not finish")
        self.assertIs(bar.kimi_data, old_data)
        self.assertEqual(bar.last_success, old_success)
        self.assertIn("重新连接失败", bar.kimi_error)
        save.assert_called_once()
        fetch.assert_not_called()


class CacheAndTimeTests(unittest.TestCase):
    def test_glm_monitor_can_omit_5h_reset_while_reporting_weekly_reset(self):
        reset = time.time()+86400
        monitor = {"code": 200, "data": {"limits": [
            {"unit": 3, "number": 5, "percentage": 0, "usage": 100, "currentValue": 0, "remaining": 100},
            {"unit": 6, "number": 1, "percentage": 20, "nextResetTime": reset*1000}]}}
        with patch.object(app, "_zcode_api_key", return_value=("synthetic", "https://example.invalid")), \
             patch.object(app, "_urlopen", side_effect=[io.StringIO(json.dumps(monitor)), io.StringIO('{"data":[]}' )]):
            windows, _, _, _ = app._fetch_zcode_monitor()
        self.assertIsNone(windows[0]["reset_at"])
        self.assertAlmostEqual(windows[1]["reset_at"], reset)

    def test_quota_display_setting_survives_save_and_reload(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, "DATA_DIR", directory), \
             patch.object(app, "CONFIG_PATH", str(Path(directory) / "config.json")):
            app.save_config(dict(app.DEFAULT_CONFIG, quota_display="used"))
            self.assertEqual(app.load_config()["quota_display"], "used")
            app.save_config(dict(app.DEFAULT_CONFIG, quota_display="remaining"))
            self.assertEqual(app.load_config()["quota_display"], "remaining")

    def test_missing_or_invalid_display_setting_keeps_remaining_as_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for value in (None, True, "unknown", ["used"]):
                with self.subTest(value=value), patch.object(app, "CONFIG_PATH", str(path)):
                    path.write_text(json.dumps({"quota_display": value}), encoding="utf-8")
                    self.assertEqual(app.load_config()["quota_display"], "remaining")
            path.write_text("{}", encoding="utf-8")
            with patch.object(app, "CONFIG_PATH", str(path)):
                self.assertEqual(app.load_config()["quota_display"], "remaining")

    def test_refresh_timeout_is_passed_to_request(self):
        cred = session(time.time() - 100)
        with patch.object(app, "_connect_post", return_value={"accessToken": token(time.time() + 3600)}) as post, \
             patch.object(app, "_save_kimi_web_cred"):
            app._kimi_web_refresh(cred, timeout=2)
        post.assert_called_once_with(app.KIMI_WEB_REFRESH_URL,
                                     {"refresh_token": cred["refresh_token"]}, timeout=2)

    def test_cache_round_trip_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, "DATA_DIR", directory), \
             patch.object(app, "CACHE_PATH", str(Path(directory) / "usage_cache.json")):
            data = app._parse_kimi_web_quota(full_quota())
            data.update({"access_token": "never-save-this", "refresh_token": "never-save-this"})
            app.save_usage_cache({"kimi": {"data": data, "saved_at": time.time() - 10}})
            raw = Path(app.CACHE_PATH).read_text(encoding="utf-8")
            self.assertNotIn("never-save-this", raw)
            self.assertEqual(app.load_usage_cache()["kimi"]["data"]["windows"], data["windows"])

    def test_corrupt_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text("{broken", encoding="utf-8")
            with patch.object(app, "CACHE_PATH", str(path)):
                self.assertEqual(app.load_usage_cache(), {})

    def test_zcode_expiry_is_parsed_as_beijing_time(self):
        monitor = {"code": 0, "data": {"limits": [{"unit": 3, "number": 5, "percentage": 20}]}}
        subs = {"data": [{"status": "VALID", "productName": "test",
                          "valid": "2026-10-13 10:00:00-2026-11-13 10:00:00"}]}
        with patch.object(app, "_zcode_api_key", return_value=("synthetic", "https://example.invalid")), \
             patch.object(app, "_urlopen", side_effect=[
                 io.StringIO(json.dumps(monitor)), io.StringIO(json.dumps(subs))]):
            until = app._fetch_zcode_monitor()[3]
        self.assertEqual(until, datetime(2026, 11, 13, 10,
                                        tzinfo=timezone(timedelta(hours=8))).timestamp())

    def test_nonfinite_usage_does_not_become_a_percentage(self):
        for value in (float("nan"), float("inf"), "NaN", None, True):
            with self.subTest(value=value):
                self.assertIsNone(app._num(value))
                self.assertEqual(app._remain(value), "?")

    def test_invalid_config_values_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"interval_minutes": "bad", "font_size": -1,
                                        "background": "red", "kimi_api_key": 123}), encoding="utf-8")
            with patch.object(app, "CONFIG_PATH", str(path)):
                cfg = app.load_config()
        self.assertEqual(cfg["interval_minutes"], 5)
        self.assertEqual(cfg["font_size"], 9)
        self.assertEqual(cfg["background"], "")
        self.assertNotIn("kimi_api_key", cfg)

    def test_aes_known_vector_and_tampered_tag(self):
        cipher = bytes.fromhex("cea7403d4d606b6e074ec5d3baf39d18")
        tag = bytes.fromhex("d0d1c8a799996bf0265b98b5d48ab919")
        self.assertEqual(app._aes_gcm_decrypt(bytes(32), bytes(12), cipher, tag), bytes(16))
        with self.assertRaises(ValueError):
            app._aes_gcm_decrypt(bytes(32), bytes(12), cipher, bytes(16))


if __name__ == "__main__":
    unittest.main()
