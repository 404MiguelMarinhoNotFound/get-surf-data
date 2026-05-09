import re
import unittest
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "public" / "index.html"
LEGACY_HTML_PATH = (
    Path(__file__).parent.parent
    / "docs"
    / "legacy"
    / "public-index-before-selected-window-technical-details.html"
)


class MobileHTMLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_viewport_meta(self):
        self.assertIn(
            'content="width=device-width, initial-scale=1.0"',
            self.html,
            "Viewport meta tag must be correctly configured",
        )

    def test_manifest_link(self):
        self.assertIn(
            'rel="manifest"',
            self.html,
            "manifest.json link must be present in <head>",
        )
        self.assertIn('href="/manifest.json"', self.html)

    def test_favicon_uses_lineup_png(self):
        self.assertIn(
            '<link rel="icon" type="image/png" href="/faviconlineup.png">',
            self.html,
        )
        self.assertIn(
            '<link rel="shortcut icon" type="image/png" href="/faviconlineup.png">',
            self.html,
        )

    def test_theme_color_meta(self):
        self.assertIn(
            'name="theme-color"',
            self.html,
            "theme-color meta tag required for browser chrome tinting",
        )

    def test_apple_mobile_capable(self):
        self.assertIn(
            'name="apple-mobile-web-app-capable"',
            self.html,
            "Apple PWA meta tag must be present",
        )

    def test_media_query_360(self):
        self.assertIn(
            "@media (max-width: 360px)",
            self.html,
            "360px breakpoint required for very small phones",
        )

    def test_media_query_hover_none(self):
        self.assertIn(
            "@media (hover: none)",
            self.html,
            "hover:none query required to disable sticky hover transforms on touch",
        )

    def test_media_query_tablet(self):
        self.assertIn(
            "@media (min-width: 601px) and (max-width: 900px)",
            self.html,
            "Tablet 2-column breakpoint must be present",
        )

    def test_sw_registration(self):
        self.assertIn(
            "serviceWorker.register('/sw.js')",
            self.html,
            "Service worker registration script must be present",
        )

    def test_no_inline_fixed_widths(self):
        # Inline style= attributes should not lock layout to 300px+ fixed widths
        inline_fixed = re.findall(r'style="[^"]*width:\s*[3-9]\d{2}px', self.html)
        self.assertEqual(
            inline_fixed,
            [],
            f"Found inline fixed widths that could break mobile: {inline_fixed}",
        )

    def test_hero_carousel_remains_present(self):
        self.assertIn(
            "function renderHeroWindowCarousel",
            self.html,
            "Existing best-window carousel renderer must remain present",
        )
        self.assertIn(
            "class=\"hero-window-slot\"",
            self.html,
            "Hero must still render the primary best-window slot",
        )

    def test_forecast_cards_show_data_status(self):
        for required in (
            "function renderDataStatus",
            "class=\"card-meta\"",
            "class=\"data-status ${data.cache_stale ? 'is-stale' : 'is-found'}\"",
            "data found - ${topCount} top - ${predictorCount} predictor",
            "cache_status",
            "cache_stale",
            "live source",
            "${renderDataStatus(data)}",
        ):
            self.assertIn(required, self.html)

    def test_predictor_ribbon_markup_and_handlers(self):
        for required in (
            "function renderPredictorRibbon",
            "function renderPredictorBar",
            "class=\"hero-predictor-slot\"",
            "class=\"hero-predictor-bar\"",
            "aria-label=\"${escapeHtml(predictorAriaLabel(win))}\"",
            "data-predictor-index",
            "function _predictorStep",
            "closest('.hero-predictor-bar')",
            "heroCard.dataset.predictorFocusPending = '1'",
            "html { overflow-x: hidden;",
            ".hero-predictor-track {",
            "function scrollPredictorBarIntoTrack",
            "track.scrollLeft",
            "function windowStartKey",
            "function findWindowIndexByStart",
            "data-selected-window-start",
            "Next best 3-hour surf windows",
            "card.setAttribute('data-selected-window-start'",
            "card.dataset.heroFocusPending = '1';\n  card.dataset.predictorFocusPending = '0';",
        ):
            self.assertIn(required, self.html)
        self.assertNotIn("inline: 'center'", self.html)
        self.assertNotIn('inline: "center"', self.html)

    def test_selected_window_practical_renderer_replaces_diagnostic_chips(self):
        for required in (
            "function renderWindowPracticalDetail",
            "class=\"window-practical-detail\"",
            "class=\"window-practical-card\"",
            "class=\"window-practical-meter\"",
            "data-tone=\"${escapeHtml(ind.tone || 'unknown')}\"",
            "aria-live=\"polite\"",
            "renderWindowPracticalDetail(windows[safeIdx])",
        ):
            self.assertIn(required, self.html)

        match = re.search(
            r"function renderWindowPracticalDetail\(win\) \{(?P<body>.*?)\n\}",
            self.html,
            re.S,
        )
        self.assertIsNotNone(match, "Selected-window practical renderer must exist")
        body = match.group("body")
        self.assertNotIn("predictorSourceChips", body)
        self.assertNotIn("predictorFactorChips", body)
        self.assertNotIn("confidence_detail", body)
        self.assertNotIn("missing_sources", body)

    def test_selected_window_technical_details_replace_old_card_drawer(self):
        for required in (
            "function renderWindowTechnicalDetail",
            "function renderTechnicalIndicator",
            "function renderTechnicalHourTable",
            "function compassLabelFromDegrees",
            "function technicalDirectionText",
            "class=\"window-technical-detail\"",
            "class=\"window-technical-card\"",
            "class=\"window-technical-table\"",
            "class=\"hero-technical-slot\"",
            "renderWindowTechnicalDetail(windows[safeIdx]",
            "heroCard.dataset.technicalExpanded",
            "closest('.hero-toggle-details')",
            "wind_direction_deg', 'wind dir', 'deg'",
            "compassLabelFromDegrees(numeric)",
            "Show technical details",
            "Hide technical details",
            "aria-expanded",
        ):
            self.assertIn(required, self.html)

        self.assertNotIn("card.querySelector('.card-details')", self.html)
        self.assertNotIn("details.hidden = !expanded;", self.html)

        match = re.search(
            r"function renderCard\(spot, data\) \{(?P<body>.*?)\n\}\n\nfunction friendlyError",
            self.html,
            re.S,
        )
        self.assertIsNotNone(match, "renderCard body must be present")
        body = match.group("body")
        self.assertNotIn("class=\"card-details\"", body)
        self.assertNotIn("renderSourcesLine(data)", body)
        self.assertNotIn("renderOmPanel(data)", body)
        self.assertNotIn("renderGfsPanel(data)", body)
        self.assertNotIn("renderIbiPanel(data)", body)

    def test_old_card_details_drawer_is_preserved_in_legacy_copy(self):
        self.assertTrue(LEGACY_HTML_PATH.exists())
        legacy_html = LEGACY_HTML_PATH.read_text(encoding="utf-8")

        for required in (
            "class=\"card-details\"",
            "renderSourcesLine(data)",
            "renderOmPanel(data)",
            "renderGfsPanel(data)",
            "renderIbiPanel(data)",
            "details.hidden = !expanded;",
        ):
            self.assertIn(required, legacy_html)


if __name__ == "__main__":
    unittest.main()
