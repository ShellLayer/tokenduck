"""Menu/dialog interaction must not compete with taskbar placement."""

import unittest
from unittest.mock import Mock, patch

import tokenduck as app
from test_tokenduck import bare_bar, User32


class WindowInteractionTests(unittest.TestCase):
    def setUp(self):
        self.bar = app.TokenDuck.__new__(app.TokenDuck)
        self.bar._menu_active = False
        self.bar.root = Mock()
        self.bar.root.tk.call.return_value = ""
        self.bar.root.winfo_children.return_value = []
        self.native = patch.object(app, "native_menu_active", return_value=False)
        self.native.start()
        self.addCleanup(self.native.stop)

    def test_posting_menu_suppresses_all_periodic_lifts(self):
        self.bar._menu_active = True
        for _ in range(4):
            self.bar._safe_lift()
        self.bar.root.lift.assert_not_called()

    def test_settings_and_child_dialogs_suppress_lifts_until_closed(self):
        window = Mock(spec=app.tk.Toplevel)
        window.state.return_value = "normal"
        self.bar.root.winfo_children.return_value = [window]
        self.bar._safe_lift()
        self.bar.root.lift.assert_not_called()
        window.state.return_value = "withdrawn"
        self.bar._safe_lift()
        self.bar.root.lift.assert_called_once()

    def test_tk_popdown_grab_suppresses_lifts(self):
        self.bar.root.tk.call.return_value = ".settings.selector.popdown"
        self.bar._safe_lift()
        self.bar.root.lift.assert_not_called()

    def test_native_menu_suppresses_lifts_even_after_popup_call_returns(self):
        with patch.object(app, "native_menu_active", return_value=True):
            self.bar._safe_lift()
        self.bar.root.lift.assert_not_called()

    def test_popup_guard_resets_after_error_and_prevents_reentry(self):
        self.bar._show_menu = Mock(side_effect=app.tk.TclError("closed"))
        with self.assertRaises(app.tk.TclError):
            self.bar.show_menu(Mock())
        self.assertFalse(self.bar._menu_active)
        self.bar._show_menu.reset_mock()
        self.bar._menu_active = True
        self.bar.show_menu(Mock())
        self.bar._show_menu.assert_not_called()

    def test_unchanged_taskbar_geometry_is_not_reapplied_each_second(self):
        bar = bare_bar()
        bar.root.geometry = Mock()
        bar._interaction_active = lambda: False
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            for _ in range(5):
                bar.anchor()
        bar.root.geometry.assert_called_once()

    def test_geometry_changes_wait_until_menu_or_dialog_closes(self):
        bar = bare_bar()
        bar.root.geometry = Mock()
        bar._interaction_active = lambda: True
        with patch.object(app.ctypes, "windll", type("DLL", (), {"user32": User32()})()):
            bar.anchor()
            bar.root.geometry.assert_not_called()
            bar._interaction_active = lambda: False
            bar.anchor()
        bar.root.geometry.assert_called_once()


if __name__ == "__main__":
    unittest.main()
