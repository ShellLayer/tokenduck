"""Layer recovery is passive, conditional, and independent of quota fetching."""

import unittest
from unittest.mock import Mock, call, patch

import taskbar_window as window


class LayerGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.root.winfo_id.return_value = 123
        self.api = Mock()
        self.widget, self.shell = 0x100001234, 0x100005678
        self.api.GetAncestor.return_value = self.widget
        self.api.FindWindowW.return_value = self.shell
        self.api.IsWindowVisible.return_value = True
        self.api.GetWindow.side_effect = lambda hwnd, _kind: self.shell if hwnd == self.widget else None
        self.api.SetWindowPos.return_value = True
        self.api.GetWindowRect.side_effect = self.rect
        self.allowed = Mock(return_value=True)
        with patch.object(window, "_windows_api", return_value=self.api):
            self.guard = window.TaskbarLayerGuard(self.root, self.allowed)
        self.guard._closed = False

    def rect(self, hwnd, pointer):
        r = pointer._obj
        r.left, r.top, r.right, r.bottom = (20, 100, 200, 140) if hwnd == self.widget else (0, 100, 400, 140)
        return True

    def test_obscured_widget_is_restacked_without_activation_or_geometry_change(self):
        self.assertTrue(self.guard.restore_if_needed())
        self.api.SetWindowPos.assert_called_once_with(self.widget, -1, 0, 0, 0, 0, 0x0213)
        self.assertEqual(self.root.method_calls, [call.winfo_id()])

    def test_unobscured_widget_does_no_restoration_work(self):
        self.api.GetWindow.return_value = None
        self.api.GetWindow.side_effect = None
        self.assertFalse(self.guard.restore_if_needed())
        self.api.SetWindowPos.assert_not_called()
        self.allowed.assert_not_called()

    def test_menu_or_dialog_interaction_blocks_restacking(self):
        self.allowed.return_value = False
        self.assertFalse(self.guard.restore_if_needed())
        self.api.SetWindowPos.assert_not_called()

    def test_hidden_windows_or_nonoverlapping_taskbar_do_not_restore(self):
        self.api.IsWindowVisible.return_value = False
        self.assertFalse(self.guard.restore_if_needed())
        self.api.IsWindowVisible.return_value = True

        def elsewhere(hwnd, pointer):
            self.rect(hwnd, pointer)
            if hwnd == self.widget:
                pointer._obj.top, pointer._obj.bottom = 10, 50
            return True

        self.api.GetWindowRect.side_effect = elsewhere
        self.assertFalse(self.guard.restore_if_needed())
        self.api.SetWindowPos.assert_not_called()

    def test_foreground_events_are_coalesced_without_rendering(self):
        for _ in range(3):
            self.guard._on_event(None, 3, 456, 0, 0, 0, 0)
        self.root.after.assert_called_once_with(0, self.guard._event_check)
        self.api.SetWindowPos.assert_not_called()

    def test_polling_fallback_is_fast_and_stops_cleanly(self):
        self.guard._closed = True
        self.api.SetWinEventHook.side_effect = [101, 102]
        self.guard.start()
        self.root.after.assert_called_once_with(50, self.guard._poll)
        self.guard.close()
        self.api.UnhookWinEvent.assert_has_calls([call(101), call(102)])
        self.root.after_cancel.assert_called_once()
        self.api.SetWindowPos.reset_mock()
        self.guard._event_check()
        self.api.SetWindowPos.assert_not_called()

    def test_failed_event_hooks_still_leave_the_fallback_running(self):
        self.guard._closed = True
        self.api.SetWinEventHook.return_value = None
        self.guard.start()
        self.root.after.assert_called_once_with(50, self.guard._poll)
        self.assertFalse(self.guard._closed)
        self.guard.close()


if __name__ == "__main__":
    unittest.main()
