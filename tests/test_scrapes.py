import unittest
from unittest.mock import patch

from src.scrape_web import browse_allowed_sources, get_supported_domains, validate_domain


class TestScrapeWeb(unittest.TestCase):
    def test_validate_domain(self):
        self.assertTrue(validate_domain("wikipedia.org"))
        self.assertFalse(validate_domain("example.com"))

    def test_get_supported_domains_contains_wikipedia(self):
        self.assertIn("wikipedia.org", get_supported_domains())

    @patch("src.scrape_web.fetch_clean_text", return_value="Sample extracted content")
    def test_browse_allowed_sources_formats_source(self, mocked_fetch):
        result = browse_allowed_sources(query="physics", forced_domain="wikipedia.org")
        self.assertTrue(result.startswith("[SOURCE: wikipedia.org]"))
        self.assertIn("Sample extracted content", result)
        mocked_fetch.assert_called_once()

    def test_browse_allowed_sources_rejects_invalid_domain(self):
        result = browse_allowed_sources(query="physics", forced_domain="invalid.example")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
