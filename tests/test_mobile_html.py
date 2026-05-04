import re
import unittest
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "public" / "index.html"


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
            "predictor.scrollIntoView",
        ):
            self.assertIn(required, self.html)


if __name__ == "__main__":
    unittest.main()
