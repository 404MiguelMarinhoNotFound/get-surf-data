import unittest

import open_meteo_explainer as om
import unified_explainer as unified


SPOT = {"optimal_swell_bearing": 260, "offshore_bearing": 10}


def _row(**overrides):
    row = {
        "wave_height": 1.2,
        "wave_period": 12.0,
        "swell_height": 1.2,
        "swell_period": 12.0,
        "swell_direction": 260.0,
        "wind_wave_height": 0.05,
        "wind_speed": 8.0,
        "wind_direction": 10.0,
    }
    row.update(overrides)
    return row


class DoctrineSuitabilityScoringTests(unittest.TestCase):
    def test_beginner_long_period_high_power_is_not_universally_excellent(self):
        clean_beginner = om._hour_score(
            _row(swell_height=1.0, wave_height=1.0, swell_period=12.0, wave_period=12.0),
            260,
            10,
            level="beginner",
        )
        powerful_beginner = om._hour_score(
            _row(swell_height=1.5, wave_height=1.5, swell_period=18.0, wave_period=18.0),
            260,
            10,
            level="beginner",
        )

        self.assertGreater(clean_beginner, powerful_beginner)
        self.assertLess(powerful_beginner, 7.5)

    def test_advanced_larger_period_swell_can_score_well_but_extreme_power_gates(self):
        advanced_score = om._hour_score(
            _row(swell_height=3.0, wave_height=3.0, swell_period=17.0, wave_period=17.0),
            260,
            10,
            level="advanced",
        )
        extreme_gate = unified._model_severe_hard_gate(
            _row(swell_height=5.0, wave_height=5.0, swell_period=20.0, wave_period=20.0),
            SPOT,
            "om",
            level="advanced",
        )

        self.assertGreater(advanced_score, 7.0)
        self.assertTrue(extreme_gate["blocked"])
        self.assertEqual(extreme_gate["source"], "om_power")

    def test_light_onshore_wind_lowers_score_without_hard_gate(self):
        offshore = _row(wind_speed=8.0, wind_direction=10.0, wind_wave_height=0.05)
        light_onshore = _row(wind_speed=8.0, wind_direction=190.0, wind_wave_height=0.20)

        offshore_score = om._hour_score(offshore, 260, 10, level="improver")
        onshore_score = om._hour_score(light_onshore, 260, 10, level="improver")
        gate = unified._om_hour_hard_gate(light_onshore, SPOT, "om")

        self.assertLess(onshore_score, offshore_score)
        self.assertFalse(gate["blocked"])

    def test_severe_onshore_wind_with_windsea_ratio_hard_gates(self):
        gate = unified._om_hour_hard_gate(
            _row(wind_speed=16.0, wind_direction=190.0, wind_wave_height=0.70),
            SPOT,
            "om",
        )

        self.assertTrue(gate["blocked"])
        self.assertEqual(gate["source"], "om_wind")

    def test_secondary_crossed_swell_lowers_numeric_score(self):
        clean = _row()
        crossed = _row(
            swell2_height=0.7,
            swell2_period=10.0,
            swell2_direction=120.0,
        )

        clean_score = om._hour_score(clean, 260, 10, level="improver")
        crossed_score = om._hour_score(crossed, 260, 10, level="improver")

        self.assertLess(crossed_score, clean_score)


if __name__ == "__main__":
    unittest.main()
