import unittest

import ipma


class EnvelopeCheckTests(unittest.TestCase):
    def test_in_envelope_true_when_within_range(self):
        today = {
            "wave_height_min_m": 1.0,
            "wave_height_max_m": 1.6,
            "wave_period_min_s": 9,
            "wave_period_max_s": 12,
        }
        env = ipma.envelope_check(today, blended_height_m=1.3, blended_period_s=10)
        self.assertTrue(env["in_envelope"])
        self.assertTrue(env["height_in_range"])
        self.assertTrue(env["period_in_range"])

    def test_out_of_envelope_when_height_too_high(self):
        today = {
            "wave_height_min_m": 0.5,
            "wave_height_max_m": 0.8,
            "wave_period_min_s": 6,
            "wave_period_max_s": 9,
        }
        env = ipma.envelope_check(today, blended_height_m=2.5, blended_period_s=7)
        self.assertFalse(env["in_envelope"])
        self.assertFalse(env["height_in_range"])

    def test_tolerance_widens_window(self):
        # Range 0.5-0.8, with 30% tolerance becomes 0.35-1.04. 1.0 is inside.
        today = {"wave_height_min_m": 0.5, "wave_height_max_m": 0.8}
        env = ipma.envelope_check(today, blended_height_m=1.0, blended_period_s=None)
        self.assertTrue(env["height_in_range"])

    def test_returns_none_when_no_today_data(self):
        self.assertIsNone(ipma.envelope_check(None, 1.0, 10))

    def test_pick_local_filters_by_id(self):
        payload = {
            "data": [
                {"globalIdLocal": 1110600, "wavePowerMin": 1.0, "wavePowerMax": 1.5},
                {"globalIdLocal": 1151200, "wavePowerMin": 0.5, "wavePowerMax": 0.9},
            ]
        }
        row = ipma._pick_local(payload, 1110600)
        self.assertEqual(row["wavePowerMin"], 1.0)
        self.assertEqual(row["wavePowerMax"], 1.5)

    def test_pick_local_returns_none_when_missing(self):
        self.assertIsNone(ipma._pick_local({"data": []}, 9999))


if __name__ == "__main__":
    unittest.main()
