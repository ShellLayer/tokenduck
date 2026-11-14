"""Native rendering model, safe HWND handling, and UI-thread dispatch."""

import os
import queue
import threading
import unittest
from unittest.mock import Mock, patch

import native_taskbar as native
import tokenduck as app


class NativeCanvasTests(unittest.TestCase):
    def setUp(self):
        self.root, self.u, self.g, self.k = Mock(), Mock(), Mock(), Mock()
        self.root.tk.call.return_value = 96/72
        self.k.GetModuleHandleW.return_value = 1
        self.u.RegisterClassW.return_value = 1
        self.u.DefWindowProcW.return_value = 0
        self.u.SetThreadDpiAwarenessContext.return_value = None
        self.u.FindWindowW.return_value = 800
        self.u.CreateWindowExW.return_value = 0x100001234
        self.u.IsWindow.return_value = True
        self.u.GetAncestor.return_value = 800
        self.u.GetWindowThreadProcessId.side_effect = lambda _h, p: setattr(p._obj, "value", os.getpid())
        self.u.GetClientRect.side_effect = self.client_rect
        self.g.CreateFontW.return_value = 1234
        self.g.SelectObject.return_value = 77
        with patch.object(native, "windows_api", return_value=(self.u, self.g, self.k)):
            self.canvas = native.TaskbarCanvas(self.root, "#202020", hidden=True)
        self.addCleanup(self.canvas.close)

    def client_rect(self, _handle, pointer):
        pointer._obj.left, pointer._obj.top = 0, 0
        pointer._obj.right, pointer._obj.bottom = 1920, 48
        return True

    def font(self):
        font = Mock()
        font.actual.return_value = {"family": "Microsoft YaHei UI", "size": 8, "weight": "bold",
                                    "slant": "roman", "underline": False, "overstrike": False}
        font.metrics.return_value = 16
        font.measure.side_effect = lambda text: len(text)*6
        return font

    def test_text_state_coordinates_and_bounding_box_are_preserved(self):
        index = self.canvas.create_text(10, 8, text="100%", font=self.font(), anchor="w", fill="#ffffff", state="hidden")
        self.assertEqual(self.canvas.itemcget(index, "state"), "hidden")
        self.canvas.itemconfig(index, state="normal")
        self.assertEqual(self.canvas.bbox(index), (9, 0, 35, 16))
        self.canvas.coords(index, 30, 8)
        self.assertEqual(self.canvas.coords(index), [30, 8])

    def test_native_window_is_created_as_a_layered_child_of_the_taskbar(self):
        self.canvas.set_geometry(220, 48, 1200, 1032)
        args = self.u.CreateWindowExW.call_args.args
        self.assertTrue(args[0] & 0x80000)
        self.assertTrue(args[3] & 0x40000000)
        self.assertFalse(args[3] & 0x80000000)
        self.assertEqual(args[8], 800)
        self.canvas.set_geometry(220, 48, 1200, 1032)
        self.u.SetWindowPos.assert_called_once()

    def test_paint_snapshot_contains_gdi_fonts_and_never_calls_tcl(self):
        self.canvas.create_text(10, 8, text="85%", font=self.font(), anchor="w", fill="#ffffff")
        self.canvas.commit()
        self.canvas.commit()
        self.g.CreateFontW.assert_called_once()
        self.assertEqual(self.canvas._snapshot[0]["font"], 1234)
        self.root.tk.reset_mock()
        self.canvas._draw(55)
        self.root.tk.call.assert_not_called()
        self.u.DrawTextW.assert_called_once()

    def test_context_and_reopen_messages_only_enqueue_until_ui_dispatch(self):
        context, reopen = Mock(), Mock()
        self.canvas.bind("<ButtonRelease-3>", context)
        self.canvas.bind("<<OpenSettings>>", reopen)
        self.canvas._window_proc(123, 0x205, 0, (8 << 16) | 12)
        self.canvas._window_proc(123, native.OPEN_SETTINGS, 0, 0)
        context.assert_not_called()
        self.root.after.assert_not_called()
        self.canvas.poll_events()
        context.assert_called_once()
        reopen.assert_called_once()

    def test_destroyed_child_can_recreate_without_destroying_the_tk_engine(self):
        self.canvas.set_geometry(220, 48, 1200, 1032)
        self.canvas._window_proc(self.canvas.hwnd, 0x82, 0, 0)
        self.assertIsNone(self.canvas.hwnd)
        self.root.destroy.assert_not_called()
        self.assertTrue(self.canvas.ensure_window(force=True))
        self.assertEqual(self.u.CreateWindowExW.call_count, 2)

    def test_reused_foreign_handle_is_never_destroyed(self):
        self.canvas.hwnd = 99
        self.canvas._geometry = (220, 48, 1200, 1032)
        self.u.GetWindowThreadProcessId.side_effect = lambda _h, p: setattr(p._obj, "value", 987654)
        self.canvas.ensure_window(force=True)
        self.u.DestroyWindow.assert_not_called()


class UiQueueTests(unittest.TestCase):
    def test_worker_does_not_call_tk_and_callback_runs_on_main_thread(self):
        bar = app.TokenDuck.__new__(app.TokenDuck)
        bar.stop_event, bar._ui_queue = threading.Event(), queue.SimpleQueue()
        bar.root, bar.canvas = Mock(), Mock()
        recorded = []
        worker = threading.Thread(target=lambda: bar._post_ui(lambda: recorded.append(threading.get_ident())))
        worker.start()
        worker.join()
        bar.root.after.assert_not_called()
        self.assertEqual(recorded, [])
        bar._native_tick()
        self.assertEqual(recorded, [threading.get_ident()])

    def test_callbacks_after_stop_are_discarded(self):
        bar = app.TokenDuck.__new__(app.TokenDuck)
        bar.stop_event, bar._ui_queue = threading.Event(), queue.SimpleQueue()
        bar.stop_event.set()
        bar._post_ui(Mock())
        self.assertTrue(bar._ui_queue.empty())


if __name__ == "__main__":
    unittest.main()
