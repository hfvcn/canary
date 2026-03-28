import logging
import unittest


class TestWebAccessLogging(unittest.TestCase):
    def test_filter_suppresses_ui_304_records(self) -> None:
        from cccc.ports.web.access_log import WebAccessLogFilter

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "GET", "/ui/assets/app.js", "1.1", 304),
            exc_info=None,
        )

        self.assertFalse(WebAccessLogFilter().filter(record))

    def test_filter_sanitizes_path_and_keeps_api_logs(self) -> None:
        from cccc.ports.web.access_log import WebAccessLogFilter

        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1:1", "GET", "/api/v1/groups\x1b]11;rgb:2885/2a19/353a\x1b\\", "1.1", 200),
            exc_info=None,
        )

        self.assertTrue(WebAccessLogFilter().filter(record))
        self.assertEqual(record.args[2], "/api/v1/groups]11;rgb:2885/2a19/353a\\")

    def test_build_web_log_config_attaches_filter_to_access_handler(self) -> None:
        from cccc.ports.web.access_log import WEB_ACCESS_LOG_FILTER_NAME, build_web_log_config

        config = build_web_log_config()

        self.assertEqual(
            config["filters"][WEB_ACCESS_LOG_FILTER_NAME]["()"],
            "cccc.ports.web.access_log.WebAccessLogFilter",
        )
        self.assertIn(WEB_ACCESS_LOG_FILTER_NAME, config["handlers"]["access"]["filters"])


if __name__ == "__main__":
    unittest.main()
