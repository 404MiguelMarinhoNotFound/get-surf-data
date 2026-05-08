import unittest

import forecast_sync


class WindguruEcmwfValidationTests(unittest.TestCase):
    def _complete_row(self):
        return {
            "timestamp_utc": "2026-05-07T06:00:00+00:00",
            "wave_height": 0.7,
            "wave_period": 6.0,
            "wave_direction": 311.0,
            "swell_height": 0.6,
            "swell_period": 5.0,
            "swell_direction": 308.0,
            "swell2_height": 0.1,
            "swell2_period": 13.0,
            "swell2_direction": 268.0,
            "wind_wave_height": 0.3,
            "wind_wave_period": 2.0,
            "wind_wave_direction": 336.0,
            "wind_speed_kmh": 12.96,
            "wind_direction_deg": 333.0,
            "wind_gusts_kmh": 20.37,
        }

    def test_windguru_ecmwf_validation_accepts_complete_rows(self):
        payload = {"hourly": [self._complete_row()]}

        self.assertIs(forecast_sync._validate_windguru_ecmwf_payload(payload), payload)

    def test_windguru_ecmwf_validation_rejects_empty_rows(self):
        with self.assertRaisesRegex(ValueError, "no hourly rows"):
            forecast_sync._validate_windguru_ecmwf_payload({"hourly": []})

    def test_windguru_ecmwf_validation_rejects_incomplete_rows(self):
        row = self._complete_row()
        row.pop("wave_height")

        with self.assertRaisesRegex(ValueError, "no complete ifs/ifsw"):
            forecast_sync._validate_windguru_ecmwf_payload({"hourly": [row]})


if __name__ == "__main__":
    unittest.main()
