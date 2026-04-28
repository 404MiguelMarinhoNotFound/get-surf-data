import json
import re
import unittest
from pathlib import Path

MANIFEST_PATH = Path(__file__).parent.parent / "public" / "manifest.json"


class ManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_is_valid_json(self):
        self.assertIsInstance(self.manifest, dict)

    def test_required_fields(self):
        for field in ("name", "short_name", "start_url", "display"):
            self.assertIn(field, self.manifest, f"Manifest missing required field: {field}")

    def test_display_standalone(self):
        self.assertEqual(
            self.manifest.get("display"),
            "standalone",
            "display must be 'standalone' for PWA installability",
        )

    def test_theme_color_format(self):
        color = self.manifest.get("theme_color", "")
        self.assertRegex(color, r"^#[0-9a-fA-F]{3,6}$", "theme_color must be a valid hex color")

    def test_start_url_is_root(self):
        self.assertEqual(self.manifest.get("start_url"), "/")

    def test_short_name_length(self):
        short_name = self.manifest.get("short_name", "")
        self.assertLessEqual(
            len(short_name), 12, "short_name should be 12 chars or fewer for home screen display"
        )


if __name__ == "__main__":
    unittest.main()
