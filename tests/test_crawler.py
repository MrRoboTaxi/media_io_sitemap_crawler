import json
import os
import unittest
from unittest.mock import patch

from media_io_sitemap_crawler import discover_root_sitemaps, normalize_target, parse_sitemap, send_bark


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

    def test_bark_sends_all_twenty_five_urls_in_three_messages(self):
        urls = [f"https://www.media.io/item-{index:02d}" for index in range(25)]
        sent = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        def urlopen(request, timeout):
            sent.append(json.loads(request.data))
            return Response()

        with patch.dict(os.environ, {"BARK_DEVICE_KEY": "test-key"}), patch("urllib.request.urlopen", side_effect=urlopen):
            send_bark(urls, require_notification=True)
        self.assertEqual([len(item["body"].splitlines()) for item in sent], [12, 12, 1])
        self.assertEqual("\n".join(item["body"] for item in sent).splitlines(), [f"item-{index:02d}" for index in range(25)])
        self.assertTrue(sent[-1]["title"].endswith("（3/3）"))


if __name__ == "__main__":
    unittest.main()
