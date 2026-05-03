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
        total = ue.SF_WEIGHT + ue.OM_WEIGHT + ue.GFS_WEIGHT + ue.IBI_WEIGHT
        expected = 10.0 * (
            (0.8 ** (ue.SF_WEIGHT / total))
            * (0.6 ** (ue.OM_WEIGHT / total))
            * (0.7 ** (ue.GFS_WEIGHT / total))
            * (0.5 ** (ue.IBI_WEIGHT / total))
        )
        self.assertAlmostEqual(result, expected, places=4)

    def test_base_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(ue.BASE_WEIGHTS.values()), 1.0, places=6)

    def test_om_is_highest_weight_and_windguru_is_lowest(self):
        self.assertGreater(ue.BASE_WEIGHTS["om"], ue.BASE_WEIGHTS["sf"])
        self.assertGreater(ue.BASE_WEIGHTS["sf"], ue.BASE_WEIGHTS["surfline"])
        self.assertGreater(ue.BASE_WEIGHTS["surfline"], ue.BASE_WEIGHTS["windguru"])

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
    def test_unify_om_gfs_ibi_surfline_windguru_sources_and_weights(self):
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
        surfline = {
            "wave_height": 1.1,
            "wave_period": 11,
            "swell_height": 1.0,
            "swell_period": 11,
            "swell_direction": 260,
            "wind_wave_height": 0.1,
            "wind_speed_kmh": 8,
            "wind_direction_deg": 10,
        }
        windguru = {
            "wave_height": 1.1,
            "wave_period": 11,
            "swell_height": 1.0,
            "swell_period": 11,
            "swell_direction": 260,
            "wind_wave_height": 0.1,
            "wind_speed_kmh": 8,
            "wind_direction_deg": 10,
        }

        result = ue.unify(
            sf_data=sf_data,
            om_analysis=om,
            om_hourly=[],
            spot={"optimal_swell_bearing": 260, "offshore_bearing": 10},
            level="improver",
            ibi_analysis=ibi,
            gfs_analysis=gfs,
            surfline_analysis=surfline,
            windguru_analysis=windguru,
        )

        self.assertEqual(result["sources_used"], ["gfs", "ibi", "om", "sf", "surfline", "windguru"])
        self.assertEqual(set(result["source_scores"]), {"sf", "surfline", "windguru", "om", "gfs", "ibi"})
        self.assertGreater(result["weights"]["om"], result["weights"]["sf"])
        self.assertGreater(result["weights"]["sf"], result["weights"]["surfline"])
        self.assertGreater(result["weights"]["surfline"], result["weights"]["windguru"])
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


class SurflineCurationTierTests(unittest.TestCase):
    def test_optimal_score_5_gives_fair_plus_model(self):
        tier, source = ue._surfline_curation_tier({"surfline_optimal_score": 5})
        self.assertEqual(tier, "fair_plus")
        self.assertEqual(source, "model")

    def test_optimal_score_3_gives_fair_model(self):
        tier, source = ue._surfline_curation_tier({"surfline_optimal_score": 3})
        self.assertEqual(tier, "fair")
        self.assertEqual(source, "model")

    def test_optimal_score_1_gives_poor_model(self):
        tier, source = ue._surfline_curation_tier({"surfline_optimal_score": 1})
        self.assertEqual(tier, "poor")
        self.assertEqual(source, "model")

    def test_good_forecaster_gives_good_forecaster(self):
        row = {"condition_rating": "GOOD", "surfline_rating_source": "forecaster"}
        tier, source = ue._surfline_curation_tier(row)
        self.assertEqual(tier, "good")
        self.assertEqual(source, "forecaster")

    def test_epic_forecaster_gives_epic_forecaster(self):
        row = {"condition_rating": "EPIC", "surfline_rating_source": "forecaster"}
        tier, source = ue._surfline_curation_tier(row)
        self.assertEqual(tier, "epic")
        self.assertEqual(source, "forecaster")

    def test_fair_to_good_label_gives_fair_plus(self):
        row = {"condition_rating": "FAIR TO GOOD", "surfline_rating_source": "model"}
        tier, source = ue._surfline_curation_tier(row)
        self.assertEqual(tier, "fair_plus")

    def test_none_row_returns_none_none(self):
        tier, source = ue._surfline_curation_tier(None)
        self.assertIsNone(tier)
        self.assertIsNone(source)


class SurflineCurvePickerTests(unittest.TestCase):
    def test_plain_no_surfline_uses_plain_curve(self):
        score = ue._sf_quality_score(3, is_gold_star=False)
        self.assertEqual(score, ue._SF_QUALITY_CURVE[3])

    def test_gold_no_surfline_uses_gold_curve(self):
        score = ue._sf_quality_score(3, is_gold_star=True)
        self.assertEqual(score, ue._SF_QUALITY_CURVE_GOLD[3])

    def test_plain_good_forecaster_uses_gold_curve(self):
        score = ue._sf_quality_score(3, is_gold_star=False, surfline_tier="good", surfline_source="forecaster")
        self.assertEqual(score, ue._SF_QUALITY_CURVE_GOLD[3])

    def test_gold_good_forecaster_uses_super_curve(self):
        score = ue._sf_quality_score(3, is_gold_star=True, surfline_tier="good", surfline_source="forecaster")
        self.assertEqual(score, ue._SF_QUALITY_CURVE_SUPER[3])

    def test_gold_epic_forecaster_uses_super_curve(self):
        score = ue._sf_quality_score(5, is_gold_star=True, surfline_tier="epic", surfline_source="forecaster")
        self.assertEqual(score, ue._SF_QUALITY_CURVE_SUPER[5])

    def test_plain_poor_uses_dampened_curve(self):
        score = ue._sf_quality_score(4, is_gold_star=False, surfline_tier="poor", surfline_source="forecaster")
        self.assertEqual(score, ue._SF_QUALITY_CURVE_DAMPENED[4])

    def test_gold_poor_uses_plain_curve(self):
        score = ue._sf_quality_score(4, is_gold_star=True, surfline_tier="poor", surfline_source="forecaster")
        self.assertEqual(score, ue._SF_QUALITY_CURVE[4])

    def test_model_good_downshifts_to_fair_plus_and_uses_plain(self):
        # model GOOD → downshifted to fair_plus; plain+fair_plus → plain curve
        score = ue._sf_quality_score(3, is_gold_star=False, surfline_tier="good", surfline_source="model")
        self.assertEqual(score, ue._SF_QUALITY_CURVE[3])

    def test_model_good_with_gold_sf_downshifts_to_fair_plus_and_uses_gold(self):
        # model GOOD → fair_plus; gold+fair_plus → gold curve
        score = ue._sf_quality_score(3, is_gold_star=True, surfline_tier="good", surfline_source="model")
        self.assertEqual(score, ue._SF_QUALITY_CURVE_GOLD[3])

    def test_forecaster_good_scores_higher_than_model_good(self):
        forecaster = ue._sf_quality_score(4, is_gold_star=False, surfline_tier="good", surfline_source="forecaster")
        model = ue._sf_quality_score(4, is_gold_star=False, surfline_tier="good", surfline_source="model")
        self.assertGreater(forecaster, model)

    def test_poor_surfline_plain_sf_scores_lower_than_no_surfline(self):
        with_poor = ue._sf_quality_score(4, is_gold_star=False, surfline_tier="poor", surfline_source="forecaster")
        without = ue._sf_quality_score(4, is_gold_star=False)
        self.assertLess(with_poor, without)


class ModelDownshiftTests(unittest.TestCase):
    def test_model_epic_downshifts_to_good(self):
        self.assertEqual(ue._apply_surfline_downshift("epic", "model"), "good")

    def test_model_good_downshifts_to_fair_plus(self):
        self.assertEqual(ue._apply_surfline_downshift("good", "model"), "fair_plus")

    def test_forecaster_good_no_downshift(self):
        self.assertEqual(ue._apply_surfline_downshift("good", "forecaster"), "good")

    def test_model_poor_stays_poor(self):
        self.assertEqual(ue._apply_surfline_downshift("poor", "model"), "poor")

    def test_none_tier_stays_none(self):
        self.assertIsNone(ue._apply_surfline_downshift(None, "model"))


if __name__ == "__main__":
    unittest.main()
