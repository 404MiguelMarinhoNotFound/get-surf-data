"""Tests for the N-source doctrine blend in unified_explainer."""
import unittest
from datetime import datetime, timezone

import unified_explainer as ue


class WeightedGeometricTests(unittest.TestCase):
    def test_two_source_uses_geometric_mean(self):
        # SF=0.25, OM=0.35; only two sources present.
        result = ue._weighted_geometric(8.0, 6.0, None)
        total = ue.SF_WEIGHT + ue.OM_WEIGHT
        sf_w = ue.SF_WEIGHT / total
        om_w = ue.OM_WEIGHT / total
        expected = 10.0 * ((8.0 / 10.0) ** sf_w) * ((6.0 / 10.0) ** om_w)
        self.assertAlmostEqual(result, expected, places=4)

    def test_three_source_blend_renormalizes_current_base_weights(self):
        result = ue._weighted_geometric(8.0, 6.0, 7.0)
        total = ue.SF_WEIGHT + ue.OM_WEIGHT + ue.IBI_WEIGHT
        sf_w = ue.SF_WEIGHT / total
        om_w = ue.OM_WEIGHT / total
        ibi_w = ue.IBI_WEIGHT / total
        expected = 10.0 * ((8.0 / 10.0) ** sf_w) * ((6.0 / 10.0) ** om_w) * ((7.0 / 10.0) ** ibi_w)
        self.assertAlmostEqual(result, expected, places=4)

    def test_four_source_blend(self):
        result = ue._weighted_geometric(8.0, 6.0, 5.0, gfs_score=7.0)
        expected = 10.0 * (
            (0.8 ** ue.SF_WEIGHT)
            * (0.6 ** ue.OM_WEIGHT)
            * (0.7 ** ue.GFS_WEIGHT)
            * (0.5 ** ue.IBI_WEIGHT)
        )
        self.assertAlmostEqual(result, expected, places=4)

    def test_all_none_returns_none(self):
        self.assertIsNone(ue._weighted_geometric(None, None, None))

    def test_single_source_returns_that_score(self):
        result = ue._weighted_geometric(None, None, 7.5)
        self.assertAlmostEqual(result, 7.5, places=4)

    def test_zero_score_uses_epsilon_not_total_collapse(self):
        result = ue._weighted_geometric(8.0, 0.0, 7.0)
        total = ue.SF_WEIGHT + ue.OM_WEIGHT + ue.IBI_WEIGHT
        expected = 10.0 * (
            (0.8 ** (ue.SF_WEIGHT / total))
            * (0.05 ** (ue.OM_WEIGHT / total))
            * (0.7 ** (ue.IBI_WEIGHT / total))
        )
        self.assertAlmostEqual(result, expected, places=4)
        self.assertGreater(result, 0.0)

    def test_renormalization_when_model_sources_missing(self):
        result = ue._weighted_geometric(8.0, None, 6.0)
        total = ue.SF_WEIGHT + ue.IBI_WEIGHT
        sf_w = ue.SF_WEIGHT / total
        ibi_w = ue.IBI_WEIGHT / total
        expected = 10.0 * ((8.0 / 10.0) ** sf_w) * ((6.0 / 10.0) ** ibi_w)
        self.assertAlmostEqual(result, expected, places=4)


class ConsensusScoreTests(unittest.TestCase):
    def test_consensus_does_not_subtract_spread_when_sources_agree(self):
        s = ue._consensus_score(7.0, 7.2, 7.4)
        base = ue._weighted_geometric(7.0, 7.2, 7.4)
        self.assertAlmostEqual(s, base, places=3)

    def test_disagreement_affects_confidence_detail_not_quality_score(self):
        s = ue._consensus_score(2.0, 9.0, 5.0)
        base = ue._weighted_geometric(2.0, 9.0, 5.0)
        detail = ue._confidence_detail(2.0, 9.0, 5.0)
        self.assertAlmostEqual(s, base, places=3)
        self.assertEqual(detail["source_score_spread"], 7.0)
        self.assertLess(detail["confidence_score_0_1"], 0.65)


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
