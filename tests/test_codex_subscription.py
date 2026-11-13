"""Subscription snapshots: synthetic JWTs only; no real auth files or requests."""

import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import tokenduck as app


def jwt(claims):
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return "test."+payload+".test"


def auth_tokens(**changes):
    claims = {"chatgpt_account_id": "test-account", "chatgpt_user_id": "test-user", "chatgpt_plan_type": "plus"}
    identity = dict(claims, chatgpt_subscription_active_until="2099-11-13T10:00:00Z")
    identity.update(changes)
    return {"account_id": "test-account", "access_token": jwt({"https://api.openai.com/auth": claims}),
            "id_token": jwt({"https://api.openai.com/auth": identity, "exp": 9999999999})}


class CodexSubscriptionTests(unittest.TestCase):
    def test_matching_subscription_date_is_read_from_id_token(self):
        self.assertEqual(app._codex_subscription_until(auth_tokens(), "plus"),
                         app._timestamp("2099-11-13T10:00:00Z"))

    def test_other_account_user_or_plan_cannot_supply_the_date(self):
        for key, value in (("chatgpt_account_id", "other-account"), ("chatgpt_user_id", "other-user"),
                           ("chatgpt_plan_type", "pro")):
            with self.subTest(key=key):
                self.assertIsNone(app._codex_subscription_until(auth_tokens(**{key: value}), "plus"))
        tokens = auth_tokens()
        tokens["account_id"] = "other-account"
        self.assertIsNone(app._codex_subscription_until(tokens, "plus"))

    def test_missing_or_invalid_subscription_date_does_not_use_login_expiry(self):
        for value in (None, True, "invalid", float("nan"), [], -1):
            with self.subTest(value=value):
                self.assertIsNone(app._codex_subscription_until(auth_tokens(chatgpt_subscription_active_until=value), "plus"))

    def test_fetch_adds_only_the_date_without_returning_auth_fields(self):
        tokens = auth_tokens()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"auth.json"
            path.write_text(json.dumps({"tokens": tokens}), encoding="utf-8")
            with patch.object(app, "AUTH_PATH", str(path)), patch.object(app, "_urlopen", return_value=io.StringIO('{"plan_type":"plus"}')):
                result = app.fetch_usage()
        self.assertEqual(result["subscription_until"], app._timestamp("2099-11-13T10:00:00Z"))
        self.assertEqual(set(result), {"plan_type", "subscription_until"})
        self.assertNotIn(tokens["id_token"], json.dumps(result))

    def test_cache_keeps_date_but_excludes_tokens(self):
        until = time.time()+86400
        data = {"plan_type": "plus", "subscription_until": until, "tokens": auth_tokens(),
                "rate_limit": {"primary_window": {"used_percent": 10, "limit_window_seconds": 18000}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DATA_DIR", directory), \
                patch.object(app, "CACHE_PATH", str(Path(directory)/"usage_cache.json")):
            app.save_usage_cache({"codex": {"data": data, "saved_at": time.time()}})
            loaded = app.load_usage_cache()["codex"]["data"]
        self.assertEqual(loaded["subscription_until"], until)
        self.assertNotIn("tokens", loaded)

    def test_menu_distinguishes_known_past_and_unknown_snapshots(self):
        bar = app.TokenDuck.__new__(app.TokenDuck)
        bar.data = {"plan_type": "plus"}
        bar.kimi_data = bar.zcode_data = None
        bar.error = bar.kimi_error = bar.zcode_error = None
        bar.last_success = {}
        for until, expected in ((2000, "订阅到期（登录记录）："), (900, "待更新"), (None, "暂未提供")):
            with self.subTest(until=until):
                bar.data["subscription_until"] = until
                notes = bar.subscription_sections(now=1000)[0]["notes"]
                self.assertTrue(any(expected in line for line in notes))


if __name__ == "__main__":
    unittest.main()
