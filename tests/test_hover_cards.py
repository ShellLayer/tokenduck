"""Hover model and placement regressions; synthetic data only, no desktop or network."""

import json
import unittest
from unittest.mock import Mock, patch

import tokenduck as app
from hover_cards import fit_popup, reset_caption


def sample_bar():
    bar = app.TokenDuck.__new__(app.TokenDuck)
    bar.data = bar.kimi_data = bar.zcode_data = None
    bar.error = bar.kimi_error = bar.zcode_error = None
    bar.last_success = {}
    return bar


class HoverModelTests(unittest.TestCase):
    def test_right_click_explicitly_activates_the_native_wrapper_for_menu_input(self):
        bar = sample_bar()
        bar.root = Mock()
        bar.root.winfo_id.return_value = 12
        bar.hide_tip, bar._kick_lift = Mock(), Mock()
        bar.autostart_var, bar.menu = Mock(), Mock()
        bar.autostart_enabled = Mock(return_value=False)
        native = Mock()
        with patch.object(app, "make_passive_window", return_value=(native, 4096)):
            bar.show_menu(Mock(x_root=100, y_root=200))
        native.SetForegroundWindow.assert_called_once_with(4096)
        bar.menu.tk_popup.assert_called_once_with(100, 200)

    def test_used_mode_changes_all_provider_percentages_without_altering_health(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.data = {"rate_limit": {"primary_window": {"used_percent": 20, "limit_window_seconds": 18000}}}
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}]}
        bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 95}]}
        sections = bar.hover_sections(now=1000)
        self.assertEqual([s["windows"][0]["display_percent"] for s in sections], [20, 0, 95])
        self.assertEqual([s["windows"][0]["remaining"] for s in sections], [80, 100, 5])
        self.assertTrue(all(s["display_mode"] == "used" for s in sections))

    def test_used_mode_converts_monthly_summary_and_count_values(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.hover_sections(now=1000)[1]
        self.assertIn("月总额度已用 15%", kimi["notes"][0])
        self.assertIn("1.5万 / 10万", kimi["notes"][0])
        bar.kimi_data["windows"] = []
        row = bar.hover_sections(now=1000)[1]["windows"][0]
        self.assertEqual(row["display_percent"], 15)
        self.assertEqual(row["detail"], "已用 1.5万 / 10万")

    def test_left_click_pins_existing_hover_without_refresh_or_repeated_lifting(self):
        bar = sample_bar()
        bar._tip = Mock()
        bar._tip_pinned = False
        bar.show_tip, bar.hide_tip = Mock(), Mock()
        bar.refresh_now, bar._kick_lift = Mock(), Mock()
        bar.on_left_click(None)
        self.assertTrue(bar._tip_pinned)
        bar._tip.set_pinned.assert_called_once_with(True)
        bar.on_left_click(None)
        bar.hide_tip.assert_called_once()
        bar.refresh_now.assert_not_called()
        bar._kick_lift.assert_not_called()

    def test_pinned_hover_remains_open_when_pointer_moves_outside(self):
        bar = sample_bar()
        bar._tip_pinned = True
        bar._pointer_in_hover = Mock(return_value=False)
        bar.hide_tip = Mock()
        bar._close_tip_if_outside()
        bar.hide_tip.assert_not_called()

    def test_provider_limit_flag_is_preserved_even_without_a_zero_percent_window(self):
        bar = sample_bar()
        bar.data = {"rate_limit": {"limit_reached": True, "primary_window": {
            "used_percent": 75, "limit_window_seconds": 18000}}}
        codex = bar.hover_sections(now=1000)[0]
        self.assertTrue(codex["limited"])
        self.assertIn("当前已达到速率上限", codex["notes"])

    def test_full_quota_is_100_and_unknown_window_is_omitted(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                      {"tag": "w", "used_percent": None}]}
        sections = bar.hover_sections(now=1000)
        self.assertEqual(sections[1]["windows"][0]["remaining"], 100)
        self.assertEqual(len(sections[1]["windows"]), 1)
        self.assertEqual(sections[0]["windows"], [])

    def test_two_primary_windows_keep_monthly_balance_in_summary(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.hover_sections(now=1000)[1]
        self.assertEqual(len(kimi["windows"]), 2)
        self.assertIn("月总额度剩余 85%", kimi["notes"][0])
        self.assertIn("8.5万 / 10万", kimi["notes"][0])

    def test_monthly_only_quota_has_its_own_progress_and_amount(self):
        bar = sample_bar()
        bar.kimi_data = {"used_ratio": 0, "amount": 100000, "amount_left": 100000}
        row = bar.hover_sections(now=1000)[1]["windows"][0]
        self.assertEqual(row["label"], "月总额度")
        self.assertEqual(row["remaining"], 100)
        self.assertEqual(row["detail"], "剩余 10万 / 10万")

    def test_failed_refresh_keeps_old_reading_and_last_success(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 20, "reset_at": 900}]}
        bar.kimi_error = "timeout"
        bar.last_success["kimi"] = 800
        kimi = bar.hover_sections(now=1000)[1]
        self.assertEqual(kimi["error"], "timeout")
        self.assertEqual(kimi["windows"][0]["remaining"], 80)
        self.assertIn("等待刷新", kimi["windows"][0]["reset"])
        self.assertIn("最后成功更新", kimi["updated"])

    def test_display_model_does_not_copy_credentials_or_account_identifiers(self):
        bar = sample_bar()
        bar.kimi_data = {"access_token": "synthetic-secret", "refresh_token": "synthetic-secret",
                         "account_id": "synthetic-account", "used_ratio": 0}
        encoded = json.dumps(bar.hover_sections(now=1000))
        self.assertNotIn("synthetic-secret", encoded)
        self.assertNotIn("synthetic-account", encoded)

    def test_moving_from_widget_into_popup_does_not_close_it(self):
        bar = sample_bar()
        bar._pointer_in_hover = Mock(return_value=True)
        bar.hide_tip = Mock()
        bar._close_tip_if_outside()
        bar.hide_tip.assert_not_called()
        bar._pointer_in_hover.return_value = False
        bar._close_tip_if_outside()
        bar.hide_tip.assert_called_once()


class HoverPlacementTests(unittest.TestCase):
    def test_popup_is_above_a_bottom_taskbar(self):
        x, y, w, h = fit_popup((1500, 1032, 1800, 1080), (380, 650), (0, 0, 1920, 1032))
        self.assertLess(y + h, 1032)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + w, 1920)

    def test_negative_monitor_coordinates_are_preserved(self):
        x, y, w, h = fit_popup((-1800, 1032, -1600, 1080), (380, 650), (-1920, 0, 0, 1032))
        self.assertLess(x, 0)
        self.assertGreaterEqual(x, -1920)
        self.assertLessEqual(x + w, 0)

    def test_small_workarea_caps_oversized_cards_and_fits_below_top_anchor(self):
        x, y, w, h = fit_popup((40, 0, 120, 30), (800, 1000), (0, 0, 320, 480))
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 320)
        self.assertLessEqual(y + h, 480)
        _, below, _, _ = fit_popup((40, 0, 120, 30), (200, 100), (0, 0, 320, 480))
        self.assertGreater(below, 30)

    def test_invalid_or_past_reset_time_is_not_a_fresh_countdown(self):
        self.assertEqual(reset_caption(float("nan"), 1000), "重置时间暂未提供")
        self.assertEqual(reset_caption(0, 1000), "重置时间暂未提供")
        self.assertEqual(reset_caption(900, 1000), "重置时间已到 · 等待刷新")
        self.assertIn("1分钟后重置", reset_caption(1001, 1000))


if __name__ == "__main__":
    unittest.main()
