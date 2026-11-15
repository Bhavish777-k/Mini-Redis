"""Validate the dashboard's section and navigation order."""

from html.parser import HTMLParser
from pathlib import Path
import unittest

PAGE = Path(__file__).resolve().parents[1] / "dashboard/static/index.html"
EXPECTED = ("overview", "telemetry", "nodes", "configure", "console", "keys", "logs", "backups")


class DashboardSections(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = []
        self.navigation = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "section" and values.get("id") in EXPECTED:
            self.sections.append(values["id"])
        if tag == "a" and values.get("data-nav") in EXPECTED:
            self.navigation.append(values["data-nav"])


class DashboardLayoutTests(unittest.TestCase):
    def test_sections_and_navigation_are_ordered(self):
        markup = PAGE.read_text(encoding="utf-8")
        page = DashboardSections()
        page.feed(markup)
        self.assertEqual(tuple(page.sections), EXPECTED)
        self.assertEqual(tuple(page.navigation), EXPECTED)
        self.assertNotIn("v0.1.0", markup)

    def test_each_javascript_target_exists(self):
        markup = PAGE.read_text(encoding="utf-8")
        for identifier in ("start-form", "key-form", "browser-save-form", "logs-btn", "backup-create"):
            with self.subTest(identifier=identifier):
                self.assertIn(f'id="{identifier}"', markup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
