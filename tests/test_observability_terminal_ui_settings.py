import os
import tempfile
import unittest


class TestObservabilityTerminalUiSettings(unittest.TestCase):
    def test_update_and_read_terminal_ui_font_settings(self) -> None:
        old_home = os.environ.get("CCCC_HOME")
        with tempfile.TemporaryDirectory() as td:
            os.environ["CCCC_HOME"] = td
            try:
                from cccc.kernel.settings import get_observability_settings, update_observability_settings

                updated = update_observability_settings(
                    {
                        "terminal_ui": {
                            "scrollback_lines": 12000,
                            "font_family": 'ui-monospace, "SF Mono", monospace',
                            "font_size": 15,
                            "line_height": 1.1,
                            "letter_spacing": 1,
                        }
                    }
                )
                reloaded = get_observability_settings()

                for obs in (updated, reloaded):
                    tui = dict(obs.get("terminal_ui") or {})
                    self.assertEqual(int(tui.get("scrollback_lines") or 0), 12000)
                    self.assertEqual(str(tui.get("font_family") or ""), 'ui-monospace, "SF Mono", monospace')
                    self.assertEqual(int(tui.get("font_size") or 0), 15)
                    self.assertAlmostEqual(float(tui.get("line_height") or 0), 1.1, places=3)
                    self.assertEqual(int(tui.get("letter_spacing") or 0), 1)
            finally:
                if old_home is None:
                    os.environ.pop("CCCC_HOME", None)
                else:
                    os.environ["CCCC_HOME"] = old_home
