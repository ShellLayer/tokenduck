"""Subscription details and context-menu regressions; synthetic data only, no desktop or network."""

import json
import unittest
from unittest.mock import Mock, patch

import tokenduck as app
from subscription_menu import reset_caption, subscription_menu_rows


def sample_bar():
    bar = app.TokenDuck.__new__(app.TokenDuck)
    bar.data = bar.kimi_data = bar.zcode_data = None
    bar.error = bar.kimi_error = bar.zcode_error = None
    bar.last_success = {}
    return bar


class SubscriptionModelTests(unittest.TestCase):
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

    def test_glm_details_explain_missing_5h_time_without_losing_weekly_time(self):
        bar = sample_bar()
        bar.zcode_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                      {"tag": "w", "used_percent": 20, "reset_at": 4600}]}
        rows = bar.subscription_sections(now=1000)[2]["windows"]
        self.assertIn("余量已满", rows[0]["reset"])
        self.assertIn("后重置", rows[1]["reset"])

    def test_right_click_explicitly_activates_the_native_wrapper_for_menu_input(self):
        bar = sample_bar()
        bar.root = Mock()
        bar.root.winfo_id.return_value = 12
        bar.update_menu_details, bar._kick_lift = Mock(), Mock()
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
        sections = bar.subscription_sections(now=1000)
        self.assertEqual([s["windows"][0]["display_percent"] for s in sections], [20, 0, 95])
        self.assertEqual([s["windows"][0]["remaining"] for s in sections], [80, 100, 5])
        self.assertTrue(all(s["display_mode"] == "used" for s in sections))

    def test_used_mode_converts_monthly_progress_and_count_values(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.subscription_sections(now=1000)[1]
        self.assertEqual(len(kimi["windows"]), 3)
        row = kimi["windows"][2]
        self.assertEqual(row["display_percent"], 15)
        self.assertEqual(row["detail"], "已用 1.5万 / 10万")
        self.assertTrue(row["full_width"])
        bar.kimi_data["windows"] = []
        row = bar.subscription_sections(now=1000)[1]["windows"][0]
        self.assertEqual(row["display_percent"], 15)
        self.assertEqual(row["detail"], "已用 1.5万 / 10万")


    def test_provider_limit_flag_is_preserved_even_without_a_zero_percent_window(self):
        bar = sample_bar()
        bar.data = {"rate_limit": {"limit_reached": True, "primary_window": {
            "used_percent": 75, "limit_window_seconds": 18000}}}
        codex = bar.subscription_sections(now=1000)[0]
        self.assertTrue(codex["limited"])
        self.assertIn("当前已达到速率上限", codex["notes"])

    def test_full_quota_is_100_and_unknown_window_is_omitted(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                      {"tag": "w", "used_percent": None}]}
        sections = bar.subscription_sections(now=1000)
        self.assertEqual(sections[1]["windows"][0]["remaining"], 100)
        self.assertEqual(len(sections[1]["windows"]), 1)
        self.assertEqual(sections[0]["windows"], [])

    def test_two_primary_windows_show_monthly_balance_as_a_separate_meter(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000}
        kimi = bar.subscription_sections(now=1000)[1]
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
        windows = bar.subscription_sections(now=1000)[1]["windows"]
        self.assertEqual(sum(w["tag"] == "月" for w in windows), 1)

    def test_unknown_monthly_usage_does_not_create_a_full_or_empty_meter(self):
        bar = sample_bar()
        for value in (None, float("nan"), True):
            with self.subTest(value=value):
                bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0},
                                             {"tag": "w", "used_percent": 25}], "used_ratio": value}
                self.assertFalse(any(w["tag"] == "月" for w in bar.subscription_sections(now=1000)[1]["windows"]))

    def test_code_consumption_is_monthly_attribution_not_an_independent_allowance(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .2, "code_used_ratio": .05}
        for mode, percent in (("remaining", 80), ("used", 20)):
            with self.subTest(mode=mode):
                bar.cfg = dict(app.DEFAULT_CONFIG, quota_display=mode)
                section = bar.subscription_sections(now=1000)[1]
                self.assertEqual(len(section["windows"]), 3)
                monthly = next(w for w in section["windows"] if w["tag"] == "月")
                self.assertEqual(monthly["display_percent"], percent)
                self.assertIn("消耗月总额度的 5%", monthly["footnote"])
                self.assertFalse(any("Kimi Code" in note for note in section["notes"]))

    def test_monthly_only_quota_has_its_own_progress_and_amount(self):
        bar = sample_bar()
        bar.kimi_data = {"used_ratio": 0, "amount": 100000, "amount_left": 100000}
        row = bar.subscription_sections(now=1000)[1]["windows"][0]
        self.assertEqual(row["label"], "月总额度")
        self.assertEqual(row["remaining"], 100)
        self.assertEqual(row["detail"], "剩余 10万 / 10万")

    def test_failed_refresh_keeps_old_reading_and_last_success(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 20, "reset_at": 900}]}
        bar.kimi_error = "timeout"
        bar.last_success["kimi"] = 800
        kimi = bar.subscription_sections(now=1000)[1]
        self.assertEqual(kimi["error"], "timeout")
        self.assertEqual(kimi["windows"][0]["remaining"], 80)
        self.assertIn("等待刷新", kimi["windows"][0]["reset"])
        self.assertIn("最后成功更新", kimi["updated"])

    def test_display_model_does_not_copy_credentials_or_account_identifiers(self):
        bar = sample_bar()
        bar.kimi_data = {"access_token": "synthetic-secret", "refresh_token": "synthetic-secret",
                         "account_id": "synthetic-account", "used_ratio": 0}
        encoded = json.dumps(bar.subscription_sections(now=1000))
        self.assertNotIn("synthetic-secret", encoded)
        self.assertNotIn("synthetic-account", encoded)


class SubscriptionMenuTests(unittest.TestCase):
    def menu_text(self, bar):
        rows = subscription_menu_rows(bar.subscription_sections(now=1000))
        return "\n".join(row[0] for row in rows if row is not None)

    def test_monthly_total_amount_and_reset_are_available_without_primary_quota_duplicates(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}, {"tag": "w", "used_percent": 25}],
                         "used_ratio": .15, "amount": 100000, "amount_left": 85000, "reset_at": 4600}
        text = self.menu_text(bar)
        self.assertIn("月总额度：剩余 85% · 8.5万 / 10万", text)
        self.assertIn("后重置", text)
        self.assertNotIn("5 小时额度", text)
        self.assertNotIn("每周额度", text)

    def test_taskbar_percentage_changes_do_not_change_supplementary_details(self):
        bar = sample_bar()
        bar.data = {"plan_type": "plus", "rate_limit": {"primary_window": {"used_percent": 20, "limit_window_seconds": 18000}}}
        before = self.menu_text(bar)
        bar.data["rate_limit"]["primary_window"]["used_percent"] = 40
        self.assertEqual(self.menu_text(bar), before)

    def test_unknown_monthly_quota_does_not_become_full_or_empty(self):
        bar = sample_bar()
        bar.kimi_data = {"windows": [{"tag": "5h", "used_percent": 0}]}
        text = self.menu_text(bar)
        self.assertIn("月总额度：暂无数据", text)
        self.assertNotIn("月总额度：剩余 100%", text)
        self.assertNotIn("月总额度：剩余 0%", text)

    def test_connection_error_and_last_success_remain_available(self):
        bar = sample_bar()
        bar.kimi_data = {"used_ratio": .15}
        bar.kimi_error = "synthetic connection failure"
        bar.last_success = {"kimi": 900}
        text = self.menu_text(bar)
        self.assertIn("旧读数", text)
        self.assertIn("读取失败：synthetic connection failure", text)
        self.assertIn("最后成功更新", text)

    def test_used_mode_count_and_monthly_attribution_keep_their_meaning(self):
        bar = sample_bar()
        bar.cfg = dict(app.DEFAULT_CONFIG, quota_display="used")
        bar.kimi_data = {"used_ratio": .15, "amount": 100000, "amount_left": 85000, "code_used_ratio": .05}
        text = self.menu_text(bar)
        self.assertIn("月总额度：已用 15% · 1.5万 / 10万", text)
        self.assertIn("消耗月总额度的 5%", text)

    def test_plans_credits_and_expiry_are_all_preserved(self):
        bar = sample_bar()
        bar.data = {"plan_type": "plus", "credits": {"has_credits": True, "balance": 100}}
        bar.kimi_data = {"level": "Kimi Moderato", "used_ratio": 0}
        bar.zcode_data = {"plan_name": "GLM Coding Plan · Pro", "until": 86400}
        text = self.menu_text(bar)
        for expected in ("Codex · Plus", "额外点数余额：100", "Kimi · Moderato", "GLM / ZCode · Pro", "订阅到期："):
            self.assertIn(expected, text)

    def test_menu_content_does_not_copy_credentials_or_account_identifiers(self):
        bar = sample_bar()
        bar.kimi_data = {"access_token": "synthetic-secret", "refresh_token": "synthetic-secret",
                         "account_id": "synthetic-account", "used_ratio": 0}
        text = self.menu_text(bar)
        self.assertNotIn("synthetic-secret", text)
        self.assertNotIn("synthetic-account", text)


class ResetCaptionTests(unittest.TestCase):
    def test_invalid_or_past_reset_time_is_not_a_fresh_countdown(self):
        self.assertEqual(reset_caption(float("nan"), 1000), "重置时间暂未提供")
        self.assertEqual(reset_caption(0, 1000), "重置时间暂未提供")
        self.assertEqual(reset_caption(900, 1000), "重置时间已到 · 等待刷新")
        self.assertIn("1分钟后重置", reset_caption(1001, 1000))


if __name__ == "__main__":
    unittest.main()
