"""Tests for the N-source weighted-harmonic blend in unified_explainer."""
import unittest
from datetime import datetime, timezone

import unified_explainer as ue


class WeightedHarmonicTests(unittest.TestCase):
    def test_two_source_matches_legacy(self):
        # SF=0.40, OM=0.30; only two sources present.
        result = ue._weighted_harmonic(8.0, 6.0, None)
        sf_w = 0.40 / 0.70
        om_w = 0.30 / 0.70
        expected = 1.0 / (sf_w / 8.0 + om_w / 6.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_three_source_blend_renormalizes_current_base_weights(self):
        result = ue._weighted_harmonic(8.0, 6.0, 7.0)
        sf_w = 0.40 / 0.80
        om_w = 0.30 / 0.80
        ibi_w = 0.10 / 0.80
        expected = 1.0 / (sf_w / 8.0 + om_w / 6.0 + ibi_w / 7.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_four_source_blend(self):
        result = ue._weighted_harmonic(8.0, 6.0, 5.0, gfs_score=7.0)
        expected = 1.0 / (0.40 / 8.0 + 0.30 / 6.0 + 0.20 / 7.0 + 0.10 / 5.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_all_none_returns_none(self):
        self.assertIsNone(ue._weighted_harmonic(None, None, None))

    def test_single_source_returns_that_score(self):
        result = ue._weighted_harmonic(None, None, 7.5)
        self.assertAlmostEqual(result, 7.5, places=4)

    def test_zero_score_short_circuits(self):
        self.assertEqual(ue._weighted_harmonic(8.0, 0.0, 7.0), 0.0)

    def test_renormalization_when_model_sources_missing(self):
        result = ue._weighted_harmonic(8.0, None, 6.0)
        sf_w = 0.40 / 0.50
        ibi_w = 0.10 / 0.50
        expected = 1.0 / (sf_w / 8.0 + ibi_w / 6.0)
        self.assertAlmostEqual(result, expected, places=4)


class ConsensusScoreTests(unittest.TestCase):
    def test_pairwise_penalty_three_sources_agree(self):
        s = ue._consensus_score(7.0, 7.2, 7.4)
        base = ue._weighted_harmonic(7.0, 7.2, 7.4)
        self.assertAlmostEqual(s, base - 0.048, places=3)

    def test_pairwise_penalty_three_sources_disagree(self):
        s = ue._consensus_score(2.0, 9.0, 5.0)
        base = ue._weighted_harmonic(2.0, 9.0, 5.0)
        self.assertAlmostEqual(s, base - 0.84, places=3)


class ConfidenceTests(unittest.TestCase):
    def test_three_way_agreement_is_high(self):
        self.assertEqual(ue._confidence(7.0, 7.2, 7.4), "high")

    def test_three_way_disagreement_is_mixed(self):
        self.assertEqual(ue._confidence(2.0, 9.0, 5.0), "mixed")

    def test_only_ibi_available(self):
        self.assertEqual(ue._confidence(None, None, 7.0), "ibi_only")

    def test_two_source_high_within_tolerance(self):
        self.assertEqual(ue._confidence(7.0, 8.0, None), "high")

    def test_no_data_unknown(self):
        self.assertEqual(ue._confidence(None, None, None), "unknown")


class AdaptiveBlendIntegrationTests(unittest.TestCase):
    def test_unify_om_gfs_ibi_sources_and_weights(self):
        sf_data = {
            "rating": 6,
            "verdict": "go",
            "details": [],
            "rating_timeline": [],
            "now_utc": "2026-04-29T10:00:00+00:00",
            "tide": None,
            "height_m": 1.2,
            "period_s": 11,
        }
        om = {
            "wave_height": 1.1,
            "wave_period": 11,
            "swell_height": 1.0,
            "swell_period": 11,
            "swell_direction_deg": 260,
            "wind_wave_height": 0.1,
            "wind_speed_kmh": 8,
            "wind_direction_deg": 10,
            "wind_gusts_kmh": 12,
            "om_details": [],
        }
        gfs = {
            "wave_height": 1.0,
            "wave_period": 11,
            "swell_height": 0.9,
            "swell_period": 11,
            "swell_direction_deg": 260,
            "wind_wave_height": 0.1,
            "wind_speed_kmh": 9,
            "wind_direction_deg": 15,
            "gfs_details": [],
        }
        ibi = {
            "wave_height": 1.2,
            "wave_period": 11,
            "swell_height": 1.1,
            "swell_period": 11,
            "swell_direction_deg": 260,
            "wind_wave_height": 0.1,
            "ibi_details": [],
        }

        result = ue.unify(
            sf_data=sf_data,
            om_analysis=om,
            om_hourly=[],
            spot={"optimal_swell_bearing": 260, "offshore_bearing": 10},
            level="improver",
            ibi_analysis=ibi,
            gfs_analysis=gfs,
        )

        self.assertEqual(result["sources_used"], ["gfs", "ibi", "om", "sf"])
        self.assertEqual(set(result["source_scores"]), {"sf", "om", "gfs", "ibi"})
        self.assertAlmostEqual(sum(result["weights"].values()), 1.0, places=4)

    def test_ibi_uses_om_wind_for_onshore_penalty(self):
        spot = {"optimal_swell_bearing": 260, "offshore_bearing": 10}
        ibi = {
            "timestamp_utc": datetime(2026, 4, 29, 10, tzinfo=timezone.utc).isoformat(),
            "wave_height": 1.2,
            "wave_period": 12,
            "swell_height": 1.1,
            "swell_period": 12,
            "swell_direction": 260,
            "wind_wave_height": 0.05,
        }
        offshore_om = {"wind_speed": 8, "wind_direction": 10}
        onshore_om = {"wind_speed": 8, "wind_direction": 190}

        clean = ue._score_ibi_hour_with_om_wind(ibi, offshore_om, spot)
        blown = ue._score_ibi_hour_with_om_wind(ibi, onshore_om, spot)

        self.assertLess(blown, clean)


if __name__ == "__main__":
    unittest.main()
