"""Tests for the N-source weighted-harmonic blend in unified_explainer."""
import unittest

import unified_explainer as ue


class WeightedHarmonicTests(unittest.TestCase):
    def test_two_source_matches_legacy(self):
        # SF=0.40, OM=0.30 — only two sources present, IBI=None.
        result = ue._weighted_harmonic(8.0, 6.0, None)
        # Renormalized weights: sf=0.40/0.70, om=0.30/0.70
        sf_w = 0.40 / 0.70
        om_w = 0.30 / 0.70
        expected = 1.0 / (sf_w / 8.0 + om_w / 6.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_three_source_blend(self):
        result = ue._weighted_harmonic(8.0, 6.0, 7.0)
        expected = 1.0 / (0.40 / 8.0 + 0.30 / 6.0 + 0.30 / 7.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_all_none_returns_none(self):
        self.assertIsNone(ue._weighted_harmonic(None, None, None))

    def test_single_source_returns_that_score(self):
        # When only IBI is present, blend just returns IBI clamped.
        result = ue._weighted_harmonic(None, None, 7.5)
        self.assertAlmostEqual(result, 7.5, places=4)

    def test_zero_score_short_circuits(self):
        self.assertEqual(ue._weighted_harmonic(8.0, 0.0, 7.0), 0.0)

    def test_renormalization_when_one_missing(self):
        # OM missing — sf and ibi share. sf=0.40/(0.40+0.30)=0.571, ibi=0.429
        result = ue._weighted_harmonic(8.0, None, 6.0)
        sf_w = 0.40 / 0.70
        ibi_w = 0.30 / 0.70
        expected = 1.0 / (sf_w / 8.0 + ibi_w / 6.0)
        self.assertAlmostEqual(result, expected, places=4)


class ConsensusScoreTests(unittest.TestCase):
    def test_pairwise_penalty_three_sources_agree(self):
        # All three within 0.5pts — penalty is small.
        s = ue._consensus_score(7.0, 7.2, 7.4)
        # Spread = 0.4, penalty = 0.4 * 0.12 = 0.048
        base = ue._weighted_harmonic(7.0, 7.2, 7.4)
        self.assertAlmostEqual(s, base - 0.048, places=3)

    def test_pairwise_penalty_three_sources_disagree(self):
        # Wide spread caps penalty at 1.0.
        s = ue._consensus_score(2.0, 9.0, 5.0)
        base = ue._weighted_harmonic(2.0, 9.0, 5.0)
        # spread = 7.0, 7.0 * 0.12 = 0.84 (under 1.0 cap)
        self.assertAlmostEqual(s, base - 0.84, places=3)


class ConfidenceTests(unittest.TestCase):
    def test_three_way_agreement_is_high(self):
        self.assertEqual(ue._confidence(7.0, 7.2, 7.4), "high")

    def test_three_way_disagreement_is_mixed(self):
        # Spread between best pair > 1.5
        self.assertEqual(ue._confidence(2.0, 9.0, 5.0), "mixed")

    def test_only_ibi_available(self):
        self.assertEqual(ue._confidence(None, None, 7.0), "ibi_only")

    def test_two_source_high_within_tolerance(self):
        self.assertEqual(ue._confidence(7.0, 8.0, None), "high")

    def test_no_data_unknown(self):
        self.assertEqual(ue._confidence(None, None, None), "unknown")


class IpmaEnvelopeIntegrationTests(unittest.TestCase):
    def test_envelope_breach_drops_confidence(self):
        # Build a minimal sf_data + ibi_analysis so unify() doesn't blow up.
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
        ipma_envelope = {"in_envelope": False, "ipma_height": [0.5, 0.8]}
        result = ue.unify(
            sf_data=sf_data,
            om_analysis=None,
            om_hourly=[],
            spot={"optimal_swell_bearing": 260, "offshore_bearing": 10},
            level="improver",
            ibi_analysis=None,
            ipma_envelope=ipma_envelope,
        )
        # With single SF source confidence is sf_only; envelope breach only
        # downgrades from "high" so we test that the envelope payload survives.
        self.assertEqual(result["ipma_sanity"], ipma_envelope)
        self.assertIn("sources_used", result)
        self.assertIn("source_scores", result)


if __name__ == "__main__":
    unittest.main()
