"""演示启动先绑定端口，再打开浏览器；不依赖Flask/MySQL。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/backend"))
from demo_server import URL, run_demo


class DemoServerTests(unittest.TestCase):
    def test_occupied_port_never_opens_browser(self):
        for error in (OSError("address in use"), SystemExit(1)):
            with (
                self.subTest(error=type(error)),
                patch("demo_server.threading.Timer") as timer,
                patch("builtins.print"),
            ):
                factory = MagicMock(side_effect=error)
                self.assertEqual(
                    run_demo(object(), open_browser=True, server_factory=factory), 1
                )
                timer.assert_not_called()

    def test_browser_scheduled_only_after_successful_bind(self):
        server = MagicMock()
        app = object()
        events = []

        def bind(*args, **kwargs):
            events.append("bind")
            return server

        with patch("demo_server.threading.Timer") as timer, patch("builtins.print"):
            timer.return_value.start.side_effect = lambda: events.append("browser")
            server.serve_forever.side_effect = lambda: events.append("serve")
            self.assertEqual(run_demo(app, open_browser=True, server_factory=bind), 0)
            self.assertEqual(events, ["bind", "browser", "serve"])
            self.assertEqual(timer.call_args.kwargs["args"], (URL,))
            timer.return_value.cancel.assert_called_once()
            server.server_close.assert_called_once()

    def test_manual_start_and_interrupt_close_server_without_browser(self):
        server = MagicMock()
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch("demo_server.threading.Timer") as timer, patch("builtins.print"):
            self.assertEqual(
                run_demo(object(), server_factory=MagicMock(return_value=server)), 0
            )
            timer.assert_not_called()
            server.server_close.assert_called_once()
