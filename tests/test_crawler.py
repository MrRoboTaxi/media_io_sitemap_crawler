import unittest
from unittest.mock import patch

from media_io_sitemap_crawler import discover_root_sitemaps, normalize_target, parse_sitemap


class CrawlerTest(unittest.TestCase):
    def test_english_sitemap_only(self):
        robots = b"Sitemap: https://www.media.io/sitemap.xml\nSitemap: https://www.media.io/fr/sitemap.xml\n"
        with patch("media_io_sitemap_crawler.fetch", return_value=(robots, "text/plain")):
            self.assertEqual(discover_root_sitemaps(), ["https://www.media.io/sitemap.xml"])

    def test_normalize_url(self):
        self.assertEqual(normalize_target("https://www.media.io/ai/example/?campaign=x#top"), "https://www.media.io/ai/example")
        self.assertIsNone(normalize_target("https://www.media.io.evil.com/ai/example"))
        self.assertIsNone(normalize_target("http://www.media.io/ai/example"))

    def test_invalid_sitemap_fails_instead_of_replacing_baseline(self):
        with patch("media_io_sitemap_crawler.fetch", return_value=(b"<html>", "text/html")):
            with self.assertRaises(RuntimeError):
                parse_sitemap("https://www.media.io/sitemap.xml", set())


if __name__ == "__main__":
    unittest.main()
