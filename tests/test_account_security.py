"""凭证和连接边界测试；所有账号、key 与登录文件均为合成数据。"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import tokenduck as app
import secure_store
from secure_store import CredentialStore, CredentialStoreError


def token(user="user-a", seconds=3600):
    claims = json.dumps({"sub": user, "exp": time.time() + seconds}).encode()
    return "eyJhbGciOiJub25lIn0." + base64.urlsafe_b64encode(claims).decode().rstrip("=") + ".synthetic"


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "accounts.dat"
        self.store = CredentialStore(self.path)

    def test_current_user_round_trip_never_writes_plaintext(self):
        marker = "synthetic-secret-that-must-not-be-readable"
        self.store.update({"test": marker})
        self.assertEqual(self.store.get("test"), marker)
        self.assertNotIn(marker.encode(), self.path.read_bytes())
        self.assertTrue(self.path.read_bytes().startswith(secure_store.MAGIC))

    def test_corrupt_store_is_not_overwritten(self):
        self.store.update({"test": "synthetic-secret"})
        data = bytearray(self.path.read_bytes())
        data[-1] ^= 0x80
        self.path.write_bytes(data)
        with self.assertRaises(CredentialStoreError):
            self.store.update({"test": "replacement"})
        self.assertEqual(self.path.read_bytes(), data)

    def test_legacy_file_removed_only_after_verified_migration(self):
        old = Path(self.directory.name) / "legacy.json"
        cred = {"access_token": "synthetic-secret", "refresh_token": "synthetic-renewal"}
        old.write_text(json.dumps(cred), encoding="utf-8")
        self.assertTrue(self.store.migrate_json(old, "kimi_web", {"kimi_account_id": "a"}))
        self.assertFalse(old.exists())
        self.assertEqual(self.store.get("kimi_web"), cred)
        self.assertNotIn(b"synthetic-secret", self.path.read_bytes())

    def test_failed_encryption_preserves_legacy_file(self):
        old = Path(self.directory.name) / "legacy.json"
        old.write_text('{"access_token":"synthetic-secret"}', encoding="utf-8")
        with patch.object(secure_store, "protect_bytes", side_effect=CredentialStoreError("unavailable")):
            with self.assertRaises(CredentialStoreError):
                self.store.migrate_json(old, "kimi_web")
        self.assertTrue(old.exists())
        self.assertFalse(self.path.exists())

    def test_migration_conflict_preserves_both_accounts(self):
        self.store.update({"kimi_web": {"access_token": "account-a"}})
        old = Path(self.directory.name) / "legacy.json"
        old.write_text('{"access_token":"account-b"}', encoding="utf-8")
        with self.assertRaises(CredentialStoreError):
            self.store.migrate_json(old, "kimi_web")
        self.assertTrue(old.exists())
        self.assertEqual(self.store.get("kimi_web")["access_token"], "account-a")

    def test_concurrent_process_updates_do_not_lose_fields(self):
        code = ("from secure_store import CredentialStore; import sys; "
                "s=CredentialStore(sys.argv[1]); "
                "[s.update({sys.argv[2]+str(i):i}) for i in range(8)]")
        processes = [subprocess.Popen([sys.executable, "-B", "-c", code, str(self.path), prefix],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                     for prefix in ("a", "b")]
        for process in processes:
            _, error = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, error.decode(errors="replace"))
        for prefix in ("a", "b"):
            for i in range(8):
                self.assertEqual(self.store.get(prefix + str(i)), i)

    def test_discarding_expired_session_keeps_account_pin(self):
        self.store.update({"kimi_web": {"access_token": "synthetic"}, "kimi_account_id": "a"})
        with patch.object(app, "ACCOUNT_STORE", self.store):
            app._discard_kimi_web_cred()
        self.assertIsNone(self.store.get("kimi_web"))
        self.assertEqual(self.store.get("kimi_account_id"), "a")

    def test_legacy_config_key_is_encrypted_and_removed_from_public_json(self):
        source = Path(self.directory.name) / "config.json"
        config = {"interval_minutes": 7, "kimi_api_key": "synthetic-configuration-key"}
        source.write_text(json.dumps(config), encoding="utf-8")
        with patch.object(app, "ACCOUNT_STORE", self.store):
            app._migrate_config_key(config, str(source))
        self.assertEqual(self.store.get("kimi_api_key"), "synthetic-configuration-key")
        self.assertNotIn("synthetic-configuration-key", source.read_text())
        self.assertNotIn("kimi_api_key", config)
        self.assertEqual(json.loads(source.read_text())["interval_minutes"], 7)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.desktop = patch.object(app, "_KIMI_DESKTOP_DIR", str(self.base)).start()
        self.addCleanup(patch.stopall)

    def write_desktop(self, user="user-a", seconds=3600, share=None):
        share = share or self.base / "daimon-share"
        path = share / "daimon" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"credentials": {"kimiWeb": {
            "accessToken": token(user, seconds), "refreshToken": "desktop-owned-renewal", "userId": user}}}), encoding="utf-8")
        return path

    def test_desktop_import_never_copies_refresh_token(self):
        path = self.write_desktop()
        original = path.read_bytes()
        cred = app.import_kimi_web_from_desktop()
        self.assertEqual(cred["_user"], "user-a")
        self.assertEqual(cred["refresh_token"], "")
        self.assertEqual(path.read_bytes(), original)

    def test_moved_desktop_storage_is_resolved(self):
        share = self.base / "relocated"
        self.write_desktop(share=share)
        (self.base / "daimon-storage.json").write_text(json.dumps({"shareDir": str(share)}), encoding="utf-8")
        self.assertIsNotNone(app.import_kimi_web_from_desktop("user-a"))

    def test_account_change_does_not_import_other_account(self):
        self.write_desktop("user-b")
        self.assertIsNone(app.import_kimi_web_from_desktop("user-a"))

    def test_expired_desktop_access_does_not_consume_its_refresh(self):
        self.write_desktop(seconds=-100)
        with patch.object(app, "_connect_post") as post:
            self.assertIsNone(app.import_kimi_web_from_desktop())
        post.assert_not_called()

    def test_browser_is_not_scanned_without_opt_in(self):
        with patch.object(app, "ACCOUNT_STORE") as store, \
             patch.object(app, "load_config", return_value={}), \
             patch.object(app, "import_kimi_web_from_browser") as browser:
            store.get.return_value = None
            with self.assertRaises(app.KimiAuthError):
                app._bind_kimi_web()
        browser.assert_not_called()

    def test_borrowed_refresh_never_saved_when_bootstrap_unavailable(self):
        with patch.object(app, "ACCOUNT_STORE") as store, \
             patch.object(app, "import_kimi_web_from_desktop", return_value={
                 "_来源": "desktop", "_user": "user-a", "access_token": token(), "refresh_token": "do-not-consume"}), \
             patch.object(app, "_kimi_web_bootstrap", return_value=None), \
             patch.object(app, "_save_kimi_web_cred") as save, \
             patch.object(app, "_connect_post") as post:
            store.get.return_value = None
            app._bind_kimi_web()
        self.assertEqual(save.call_args.args[0]["refresh_token"], "")
        post.assert_not_called()

    def test_binding_rejects_mismatched_independent_session(self):
        self.write_desktop("user-a")
        with patch.object(app, "ACCOUNT_STORE") as store, \
             patch.object(app, "_kimi_web_bootstrap", return_value={
                 "_来源": "独立会话", "access_token": token("user-b"), "refresh_token": "synthetic"}), \
             patch.object(app, "_save_kimi_web_cred") as save:
            store.get.return_value = None
            with self.assertRaises(app.KimiAuthError):
                app._bind_kimi_web()
        save.assert_not_called()

    def test_refresh_rejects_another_accounts_tokens_before_saving(self):
        cred = {"_来源": "独立会话", "access_token": token("user-a"), "refresh_token": "synthetic"}
        with patch.object(app, "_connect_post", return_value={"accessToken": token("user-b")}), \
             patch.object(app, "_save_kimi_web_cred") as save:
            with self.assertRaises(RuntimeError):
                app._kimi_web_refresh(cred)
        save.assert_not_called()

    def test_failed_new_connection_does_not_replace_existing_binding(self):
        candidate = {"_来源": "独立会话", "access_token": token("user-b")}
        with patch.object(app, "_bind_kimi_web", return_value=candidate) as bind, \
             patch.object(app, "_connect_post", side_effect=RuntimeError("offline")), \
             patch.object(app, "_save_kimi_web_cred") as save:
            with self.assertRaises(RuntimeError):
                app.connect_kimi_account(False)
        bind.assert_called_once_with(15, replace_account=True, persist=False, allow_browser=False)
        save.assert_not_called()

    def test_new_connection_is_committed_only_after_quota_validation(self):
        events = []
        candidate = {"_来源": "独立会话", "access_token": token("user-b")}
        def quota(*args):
            events.append("validate")
            return {"ratelimitCode5h": {"enabled": True, "ratio": 0}}
        def save(*args):
            events.append("commit")
        with patch.object(app, "_bind_kimi_web", return_value=candidate), \
             patch.object(app, "_connect_post", side_effect=quota), \
             patch.object(app, "_save_kimi_web_cred", side_effect=save):
            app.connect_kimi_account(False)
        self.assertEqual(events, ["validate", "commit"])

    def test_explicit_web_mode_does_not_use_other_accounts_saved_key(self):
        values = {"kimi_api_key": "synthetic-key", "kimi_auth_mode": "web"}
        with patch.object(app, "ACCOUNT_STORE") as store, \
             patch.object(app, "_fetch_kimi_by_web", return_value={"source": "web"}) as web, \
             patch.object(app, "_fetch_kimi_by_api_key") as api:
            store.get.side_effect = values.get
            self.assertEqual(app.fetch_kimi_quota()["source"], "web")
        api.assert_not_called()

    def test_key_failure_does_not_silently_fall_back_to_another_login(self):
        values = {"kimi_api_key": "synthetic-key", "kimi_auth_mode": "key"}
        with patch.object(app, "ACCOUNT_STORE") as store, \
             patch.object(app, "_fetch_kimi_by_web") as web, \
             patch.object(app, "_fetch_kimi_by_api_key", side_effect=RuntimeError("invalid key")):
            store.get.side_effect = values.get
            with self.assertRaises(RuntimeError):
                app.fetch_kimi_quota()
        web.assert_not_called()

    def test_browser_origin_filter_rejects_lookalike_domains(self):
        suffix = b"\x00\x01access_token"
        self.assertIsNotNone(app._LS_KEY_RE.search(b"_https://www.kimi.com" + suffix))
        for domain in (b"notkimi.com", b"kimi.com.evil.invalid", b"kimi-fake.com"):
            self.assertIsNone(app._LS_KEY_RE.search(b"_https://" + domain + suffix))


class RenameCompatibilityTests(unittest.TestCase):
    def test_fresh_install_uses_tokenduck_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(app.select_data_directory(directory), str(Path(directory) / "tokenduck"))

    def test_existing_encrypted_store_is_reused_without_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "codexbar"
            legacy.mkdir()
            original = b"synthetic encrypted content"
            (legacy / "accounts.dat").write_bytes(original)
            selected = app.select_data_directory(directory)
            self.assertEqual(selected, str(legacy))
            self.assertEqual((legacy / "accounts.dat").read_bytes(), original)
            self.assertFalse((Path(directory) / "tokenduck").exists())

    def test_self_check_output_does_not_hide_existing_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "tokenduck"
            legacy = Path(directory) / "codexbar"
            current.mkdir()
            legacy.mkdir()
            (current / "self_check.json").write_text("{}", encoding="utf-8")
            (legacy / "accounts.dat").write_bytes(b"synthetic")
            self.assertEqual(app.select_data_directory(directory), str(legacy))

    def test_configured_new_install_keeps_its_selected_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("tokenduck", "codexbar"):
                path = Path(directory) / name
                path.mkdir()
                (path / "accounts.dat").write_bytes(b"synthetic")
            self.assertEqual(app.select_data_directory(directory), str(Path(directory) / "tokenduck"))

    def test_existing_startup_entry_is_updated_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            startup = Path(app.select_startup_path(directory))
            self.assertEqual(startup.name, "tokenduck.vbs")
            startup.parent.mkdir(parents=True)
            legacy = startup.with_name("codexbar.vbs")
            legacy.write_text("synthetic old startup", encoding="utf-16")
            self.assertEqual(app.select_startup_path(directory), str(legacy))
            with patch.object(app, "STARTUP_VBS", str(legacy)), \
                 patch.object(app, "startup_command", return_value=[r"C:\TokenDuck\TokenDuck.exe"]):
                app.write_autostart()
            self.assertIn("TokenDuck.exe", legacy.read_text(encoding="utf-16"))
            self.assertFalse(startup.exists())


class NetworkAndPackagingTests(unittest.TestCase):
    def test_foreign_or_downgrade_redirect_is_blocked_before_forwarding_auth(self):
        request = urllib.request.Request(app.USAGE_URL, headers={"Authorization": "Bearer synthetic"})
        for url in ("https://example.invalid/", "http://chatgpt.com/", "https://chatgpt.com.evil.invalid/"):
            with self.subTest(url=url), self.assertRaises(urllib.error.HTTPError) as caught:
                app._SameOriginRedirect().redirect_request(request, None, 302, "redirect", {}, url)
            caught.exception.close()

    def test_nonofficial_initial_destination_is_blocked(self):
        with patch.object(app.urllib.request, "build_opener") as opener:
            for url in ("https://example.invalid/", "http://www.kimi.com/", "https://www.kimi.com@evil.invalid/", "https://api.z.ai:8443/"):
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    app._urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer synthetic"}))
        opener.assert_not_called()

    def test_same_origin_https_redirect_is_allowed(self):
        request = urllib.request.Request(app.USAGE_URL, headers={"Authorization": "Bearer synthetic"})
        result = app._SameOriginRedirect().redirect_request(request, None, 302, "redirect", {}, "https://chatgpt.com/same-host")
        self.assertEqual(result.get_header("Authorization"), "Bearer synthetic")

    def test_exe_autostart_does_not_reference_python_or_temporary_script(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, "STARTUP_VBS", str(Path(directory) / "startup.vbs")), \
             patch.object(app.sys, "frozen", True, create=True), \
             patch.object(app.sys, "executable", "C:\\Program Files\\TokenDuck\\TokenDuck.exe"):
            app.write_autostart()
            content = Path(app.STARTUP_VBS).read_text(encoding="utf-16")
        self.assertIn('""C:\\Program Files\\TokenDuck\\TokenDuck.exe""', content)
        self.assertNotIn("python", content)
        self.assertNotIn(".py", content)
        self.assertIn('""--background""', content)

    def test_unknown_zcode_destination_does_not_receive_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "ACCOUNT_STORE") as store:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"provider": {"bigmodel-coding-plan": {"options": {
                "apiKey": "synthetic", "baseURL": "https://example.invalid/coding"}}}}), encoding="utf-8")
            store.get.return_value = None
            with patch.object(app, "ZCODE_CFG_PATH", str(path)), self.assertRaises(RuntimeError):
                app._zcode_api_key()


if __name__ == "__main__":
    unittest.main()
