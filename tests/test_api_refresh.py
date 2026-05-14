import os
import unittest

import api.refresh as api_refresh


class _DummyRefreshHandler:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.sent = None

    def _send_json(self, data, status=200):
        self.sent = {"data": data, "status": status}


class RefreshAuthTests(unittest.TestCase):
    def setUp(self):
        self.original_secret = os.environ.get("CRON_SECRET")

    def tearDown(self):
        if self.original_secret is None:
            os.environ.pop("CRON_SECRET", None)
        else:
            os.environ["CRON_SECRET"] = self.original_secret

    def test_blank_cron_secret_reports_refresh_auth_not_configured(self):
        os.environ["CRON_SECRET"] = ""

        allowed, payload, status = api_refresh.refresh_auth_result({})

        self.assertFalse(allowed)
        self.assertEqual(status, 503)
        self.assertEqual(payload["code"], "refresh_auth_not_configured")

    def test_wrong_authorization_reports_refresh_auth_invalid(self):
        os.environ["CRON_SECRET"] = "expected"

        allowed, payload, status = api_refresh.refresh_auth_result(
            {"Authorization": "Bearer wrong"}
        )

        self.assertFalse(allowed)
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], "refresh_auth_invalid")

    def test_correct_authorization_runs_refresh(self):
        os.environ["CRON_SECRET"] = "expected"
        original_refresh_cache = api_refresh.forecast_cache.refresh_cache
        calls = []
        api_refresh.forecast_cache.refresh_cache = lambda force=False: calls.append(force) or {
            "status": "success"
        }
        dummy = _DummyRefreshHandler({"Authorization": "Bearer expected"})
        try:
            api_refresh.handler._handle_refresh(dummy, force=True)
        finally:
            api_refresh.forecast_cache.refresh_cache = original_refresh_cache

        self.assertEqual(calls, [True])
        self.assertEqual(dummy.sent["status"], 200)
        self.assertEqual(dummy.sent["data"]["status"], "success")


if __name__ == "__main__":
    unittest.main()
