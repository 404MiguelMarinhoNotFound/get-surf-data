"""Tests for SF gold-star scraping + dual quality curves + softened gate."""

import unittest

from scraper import classify_star_fill, parse_rating_star_states
from unified_explainer import (
    _SF_QUALITY_CURVE,
    _SF_QUALITY_CURVE_GOLD,
    _sf_quality_score,
)


GOLD_FILL_BRIGHT = "hsl(53.3, 100%, 73.5%)"
GOLD_FILL_DEEP = "hsl(48, 95%, 55%)"
WHITE_FILL = "hsl(0, 0%, 100%)"


class ClassifyStarFillTests(unittest.TestCase):
    def test_gold_bright(self):
        self.assertEqual(classify_star_fill(GOLD_FILL_BRIGHT, 3), "gold")

    def test_gold_deep(self):
        self.assertEqual(classify_star_fill(GOLD_FILL_DEEP, 7), "gold")

    def test_white(self):
        self.assertEqual(classify_star_fill(WHITE_FILL, 4), "white")

    def test_zero_rating_short_circuits(self):
        # A zero rating is "zero" regardless of fill (SF still renders a star shape).
        self.assertEqual(classify_star_fill(GOLD_FILL_BRIGHT, 0), "zero")
        self.assertEqual(classify_star_fill(WHITE_FILL, 0), "zero")

    def test_unknown_when_fill_missing(self):
        self.assertEqual(classify_star_fill(None, 5), "unknown")

    def test_unknown_when_hsl_unparseable(self):
        self.assertEqual(classify_star_fill("rgb(255,255,0)", 5), "unknown")


class ParseRatingStarStatesTests(unittest.TestCase):
    def _row(self, *cells_html):
        return (
            '<tr class="forecast-table__row" data-row="rating">'
            + "".join(cells_html)
            + "</tr>"
        )

    def _cell(self, fill, rating):
        return (
            f'<td><div class="star-rating">'
            f'<svg><use fill="{fill}"></use></svg>'
            f'<div class="star-rating__rating star-rating__rating--{rating}">{rating}</div>'
            f"</div></div></td>"
        )

    def test_parses_mixed_row(self):
        html = self._row(
            self._cell(GOLD_FILL_BRIGHT, 3),
            self._cell(WHITE_FILL, 1),
            self._cell(GOLD_FILL_DEEP, 7),
        )
        out = parse_rating_star_states(html)
        self.assertEqual([c["state"] for c in out], ["gold", "white", "gold"])
        self.assertEqual([c["rating"] for c in out], [3, 1, 7])

    def test_returns_empty_when_row_missing(self):
        self.assertEqual(parse_rating_star_states("<html></html>"), [])


class SfQualityScoreTests(unittest.TestCase):
    def test_plain_curve_unchanged(self):
        self.assertAlmostEqual(_sf_quality_score(3), _SF_QUALITY_CURVE[3])
        self.assertAlmostEqual(_sf_quality_score(5), _SF_QUALITY_CURVE[5])

    def test_gold_lifts_low_ratings(self):
        self.assertAlmostEqual(_sf_quality_score(3, is_gold_star=True), _SF_QUALITY_CURVE_GOLD[3])
        self.assertGreater(
            _sf_quality_score(3, is_gold_star=True),
            _sf_quality_score(3, is_gold_star=False),
        )

    def test_gold_and_plain_match_at_endpoints(self):
        self.assertEqual(_sf_quality_score(0, is_gold_star=True), 0.0)
        self.assertEqual(_sf_quality_score(10, is_gold_star=True), 10.0)

    def test_interpolation_between_integers(self):
        # 2.5 plain: midpoint of 3.5 and 4.8 -> 4.15
        self.assertAlmostEqual(_sf_quality_score(2.5), (3.5 + 4.8) / 2)
        # 2.5 gold: midpoint of 5.5 and 6.8 -> 6.15
        self.assertAlmostEqual(_sf_quality_score(2.5, is_gold_star=True), (5.5 + 6.8) / 2)

    def test_none_rating_returns_none(self):
        self.assertIsNone(_sf_quality_score(None))
        self.assertIsNone(_sf_quality_score(None, is_gold_star=True))


class SfLowRatingGateTests(unittest.TestCase):
    """Truth table for the softened sf_low_rating gate.

    Reproduces the boolean expression in unified_explainer._score_hour:

        sf_low_rating = (
            require_sf
            and sf_raw is not None
            and sf_raw <= 2
            and not sf_is_gold
            and (om_score is None or om_score < 5.5)
        )
    """

    @staticmethod
    def _gate(require_sf, sf_raw, sf_is_gold, om_score):
        return (
            require_sf
            and sf_raw is not None
            and sf_raw <= 2
            and not sf_is_gold
            and (om_score is None or om_score < 5.5)
        )

    def test_plain_low_with_low_om_blocks(self):
        self.assertTrue(self._gate(True, 2, False, 4.0))

    def test_plain_low_with_high_om_passes(self):
        self.assertFalse(self._gate(True, 2, False, 7.0))

    def test_gold_low_passes_regardless_of_om(self):
        self.assertFalse(self._gate(True, 2, True, 3.0))
        self.assertFalse(self._gate(True, 2, True, None))

    def test_high_sf_never_blocks(self):
        self.assertFalse(self._gate(True, 5, False, 3.0))

    def test_no_require_sf_never_blocks(self):
        self.assertFalse(self._gate(False, 1, False, 3.0))

    def test_missing_om_with_plain_low_blocks(self):
        self.assertTrue(self._gate(True, 1, False, None))


if __name__ == "__main__":
    unittest.main()
