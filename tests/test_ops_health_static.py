import unittest
from pathlib import Path


HTML_PATH = Path(__file__).parent.parent / "public" / "index.html"


class OpsHealthStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_ops_health_normalizes_diagnostic_field_names(self):
        for required in (
            "row_count: rowCount",
            "current_at: currentAt",
            "horizon_at: latestTimestamp(hourly)",
            "missing_fields: missing",
            "status",
            "error",
        ):
            self.assertIn(required, self.html)

    def test_ops_report_explains_stale_or_missing_hourly_payloads(self):
        for required in (
            "function staleHealthHints",
            "cache_stale",
            "refresh_status",
            "refresh_last_error",
            "Last refresh",
            "Hourly arrays missing for active model sources",
            "Restart the local Python server",
            "stale/source health",
        ):
            self.assertIn(required, self.html)

    def test_ops_health_warns_on_stale_source_current_timestamps(self):
        for required in (
            "SOURCE_CURRENT_STALE_HOURS",
            "function isStaleSourceCurrent",
            "currentStale",
            "label = 'stale'",
            "Source current timestamps are stale",
        ):
            self.assertIn(required, self.html)

    def test_ops_health_accepts_open_meteo_wind_aliases(self):
        for required in (
            "fieldAliases",
            "wind_speed_kmh: ['wind_speed_kmh', 'wind_speed']",
            "wind_direction_deg: ['wind_direction_deg', 'wind_direction']",
            "function hasFieldValue",
        ):
            self.assertIn(required, self.html)

    def test_localhost_disables_service_worker_shell_cache(self):
        for required in (
            "async function resetLocalServiceWorker",
            "navigator.serviceWorker.getRegistrations",
            "registration.unregister()",
            "caches.keys()",
            "caches.delete(key)",
            "if (LOCAL_SERVER) {",
            "resetLocalServiceWorker();",
            "navigator.serviceWorker.register('/sw.js')",
        ):
            self.assertIn(required, self.html)


if __name__ == "__main__":
    unittest.main()
