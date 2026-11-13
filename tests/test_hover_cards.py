"""Hover model and placement regressions; synthetic data only, no desktop or network."""

import json
import unittest
from unittest.mock import Mock, patch

import tokenduck as app
from hover_cards import fit_popup, reset_caption, supplemental_content


def sample_bar():
    bar = app.TokenDuck.__new__(app.TokenDuck)
    bar.data = bar.kimi_data = bar.zcode_data = None
    bar.error = bar.kimi_error = bar.zcode_error = None
    bar.last_success = {}
    return bar


class HoverModelTests(unittest.TestCase):
    def test_glm_full_capacity_without_reset_has_state_in_both_modes(self):
        win = {"tag": "5h", "used_percent": 0, "reset_at": None, "amount": 100, "amount_left": 100}
        for mode, expected in (("remaining", "已满"), ("used", "未用")):
            short, caption, _ = app.quota_timing("zcode", win, mode, now=1000)
            self.assertEqual(short, expected)
            self.assertIn("消耗 5 小时后恢复", caption)
            self.assertIsNone(win["reset_at"])

    def test_glm_partial_and_rounded_zero_usage_do_not_invent_a_reset(self):
        for percent in (25, 0):
            win = {"tag": "5h", "used_percent": percent, "reset_at": None, "amount": 1000, "amount_left": 999}
            short, caption, _ = app.quota_timing("zcode", win, now=1000)
            self.assertEqual(short, "滚动")
            self.assertIn("暂无精确恢复时间", caption)
            self.assertIsNone(win["reset_at"])

    def test_glm_stale_or_elapsed_recovery_waits_for_refresh(self):
        for stale, reset in ((True, None), (False, 900)):
            short, caption, _ = app.quota_timing("zcode", {"tag": "5h", "used_percent": 0, "reset_at": reset},
                                                 stale=stale, now=1000)
            self.assertEqual(short, "待刷新")
            self.assertIn("等待刷新", caption)

    def test_glm_exact_recovery_time_and_weekly_reset_keep_their_meanings(self):
        win = {"tag": "5h", "used_percent": 25, "reset_at": 4600}
        short, caption, label = app.quota_timing("zcode", win, now=1000)
        self.assertEqual(short, "1h0m")
        self.assertIn("后恢复", caption)
        self.assertEqual(label, "恢复于 ")
        short, caption, label = app.quota_timing("zcode", dict(win, tag="w"), now=1000)
        self.assertEqual(short, "1h0m")
        self.assertIn("后重置", caption)
        self.assertEqual(label, "重置于 ")

    def test_glm_hover_explains_missing_5h_time_without_losing_weekly_time(self):
        bar = sample_bar()
        bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                      {"tag": "w", "used_percent": 20, "reset_at": 4600}]}
        rows = bar.hover_sections(now=1000)[2]["windows"]
        self.assertIn("余量已满", rows[0]["reset"])
        self.assertIn("后重置", rows[1]["reset"])

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

    def test_used_mode_converts_monthly_progress_and_count_values(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.hover_sections(now=1000)[1]
        self.assertEqual(len(kimi["windows"]), 3)
        row = kimi["windows"][2]
        self.assertEqual(row["display_percent"], 15)
        self.assertEqual(row["detail"], "已用 1.5万 / 10万")
        self.assertTrue(row["full_width"])
        bar.kimi_data["windows"] = []
        row = bar.hover_sections(now=1000)[1]["windows"][0]
        self.assertEqual(row["display_percent"], 15)
        self.assertEqual(row["detail"], "已用 1.5万 / 10万")

    def test_left_click_only_dismisses_without_refreshing_or_opening(self):
        bar = sample_bar()
        bar.hide_tip, bar.show_tip, bar.refresh_now, bar._kick_lift = Mock(), Mock(), Mock(), Mock()
        bar.on_left_click(None)
        bar.hide_tip.assert_called_once()
        bar.show_tip.assert_not_called()
        bar.refresh_now.assert_not_called()
        bar._kick_lift.assert_not_called()

    def test_brief_hover_is_cancelled_before_the_tooltip_opens(self):
        bar = sample_bar()
        bar.root = Mock()
        bar.root.after.return_value = "show-job"
        bar._tip = None
        bar.schedule_tip()
        bar.root.after.assert_called_once_with(500, bar.show_tip)
        bar.schedule_tip_hide()
        bar.root.after_cancel.assert_called_with("show-job")
        self.assertEqual(bar.root.after.call_count, 1)

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

    def test_two_primary_windows_show_monthly_balance_as_a_separate_meter(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.hover_sections(now=1000)[1]
        self.assertEqual(len(kimi["windows"]), 3)
        row = kimi["windows"][2]
        self.assertEqual(row["label"], "月总额度")
        self.assertEqual(row["display_percent"], 85)
        self.assertEqual(row["detail"], "剩余 8.5万 / 10万")
        self.assertTrue(row["full_width"])
        self.assertFalse(any("月总额度" in note for note in kimi["notes"]))

    def test_explicit_monthly_window_is_not_duplicated_by_monthly_ratio(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                     {"tag": "月", "used_percent": 15}], "used_ratio": .15}
        windows = bar.hover_sections(now=1000)[1]["windows"]
        self.assertEqual(sum(w["tag"] == "月" for w in windows), 1)

    def test_unknown_monthly_usage_does_not_create_a_full_or_empty_meter(self):
        bar = sample_bar()
        for value in (None, float("nan"), True):
            with self.subTest(value=value):
                bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                             {"tag": "w", "used_percent": 25}], "used_ratio": value}
                self.assertFalse(any(w["tag"] == "月" for w in bar.hover_sections(now=1000)[1]["windows"]))

    def test_code_consumption_is_monthly_attribution_not_an_independent_allowance(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .2, "code_used_ratio": .05}
        for mode, percent in (("remaining", 80), ("used", 20)):
            with self.subTest(mode=mode):
                bar.cfg = dict(app.DEFAULT_CONFIG, quota_display=mode)
                section = bar.hover_sections(now=1000)[1]
                self.assertEqual(len(section["windows"]), 3)
                monthly = next(w for w in section["windows"] if w["tag"] == "月")
                self.assertEqual(monthly["display_percent"], percent)
                self.assertIn("消耗月总额度的 5%", monthly["footnote"])
                self.assertFalse(any("Kimi Code" in note for note in section["notes"]))

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

    def test_leaving_widget_schedules_unconditional_tooltip_dismissal(self):
        bar = sample_bar()
        bar.root = Mock()
        bar.root.after.return_value = "hide-job"
        tip = bar._tip = Mock()
        bar.schedule_tip_hide()
        bar.root.after.assert_called_once_with(120, bar.hide_tip)
        bar.root.after.call_args.args[1]()
        tip.destroy.assert_called_once()
        self.assertIsNone(bar._tip)


class SupplementalContentTests(unittest.TestCase):
    def test_primary_quotas_are_omitted_and_monthly_quota_is_kept(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        content = supplemental_content(bar.hover_sections(now=1000))
        self.assertEqual([t["window"]["tag"] for t in content["totals"]], ["月"])
        self.assertEqual(content["totals"][0]["window"]["display_percent"], 85)

    def test_taskbar_percentage_changes_do_not_change_supplementary_content(self):
        bar = sample_bar()
        bar.data = {"plan_type": "plus", "rate_limit": {"primary_window": {"used_percent": 20, "limit_window_seconds": 18000}}}
        before = supplemental_content(bar.hover_sections(now=1000))
        bar.data["rate_limit"]["primary_window"]["used_percent"] = 40
        self.assertEqual(supplemental_content(bar.hover_sections(now=1000)), before)

    def test_unknown_monthly_quota_does_not_become_a_fake_meter(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}]}
        content = supplemental_content(bar.hover_sections(now=1000))
        self.assertEqual(content["totals"], [])
        self.assertIn("暂无月总额度信息", content["facts"][0]["lines"])

    def test_connection_error_and_last_success_remain_available(self):
        bar = sample_bar()
        bar.kimi_data = {"used_ratio": .15}
        bar.kimi_error = "synthetic connection failure"
        bar.last_success = {"kimi": 900}
        content = supplemental_content(bar.hover_sections(now=1000))
        fact = next(f for f in content["facts"] if f["id"] == "kimi")
        self.assertTrue(fact["error"])
        self.assertTrue(any("读取失败" in text for text in fact["lines"]))
        self.assertTrue(any("最后成功更新" in text for text in fact["lines"]))

    def test_used_mode_count_and_monthly_attribution_survive_projection(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.kimi_data = {"used_ratio": .15, "amount": 100000, "amount_left": 85000, "code_used_ratio": .05}
        content = supplemental_content(bar.hover_sections(now=1000))
        window = content["totals"][0]["window"]
        self.assertEqual(window["display_percent"], 15)
        self.assertEqual(window["detail"], "已用 1.5万 / 10万")
        self.assertIn("消耗月总额度的 5%", window["footnote"])


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
