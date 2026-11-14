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


    def test_menu_grabs_and_native_popups_defer_rendering(self):
        self.bar._menu_active = True
        self.assertTrue(self.bar._interaction_active())
        self.bar._menu_active = False
        self.bar.root.tk.call.return_value = ".selector.popdown"
        self.assertTrue(self.bar._interaction_active())
        self.bar.root.tk.call.return_value = ""
        with patch.object(app, "native_menu_active", return_value=True):
            self.assertTrue(self.bar._interaction_active())

    def test_settings_interaction_ends_when_the_window_closes(self):
        window = Mock(spec=app.tk.Toplevel)
        window.state.return_value = "normal"
        self.bar.root.winfo_children.return_value = [window]
        self.assertTrue(self.bar._interaction_active())
        window.state.return_value = "withdrawn"
        self.assertFalse(self.bar._interaction_active())

    def test_posted_menu_blocks_font_changes_and_canvas_redraws(self):
        self.bar._menu_active = True
        self.bar.canvas = Mock()
        self.bar._apply_font_size = Mock()
        self.bar.render()
        self.bar.anchor()
        self.bar.apply_theme()
        self.assertTrue(self.bar._render_pending)
        self.bar._apply_font_size.assert_not_called()
        self.assertEqual(self.bar.canvas.method_calls, [])
        self.bar.root.geometry.assert_not_called()

    def test_deferred_render_runs_once_when_interaction_ends(self):
        self.bar._render_pending = True
        self.bar.apply_theme = Mock()
        self.bar.render = Mock(side_effect=lambda: setattr(self.bar, "_render_pending", False))
        self.bar._resume_render()
        self.bar._resume_render()
        self.bar.apply_theme.assert_called_once()
        self.bar.render.assert_called_once()


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
