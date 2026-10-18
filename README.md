# Media.io sitemap crawler

Monitors new English pages in the public `https://www.media.io/sitemap.xml`. Media.io lists eleven translated sitemaps separately in `robots.txt`; those are excluded to avoid duplicate alerts for localized versions of the same page.

The durable baseline is `state/known_urls.txt`. Each later run writes new URL details to `reports/<UTC timestamp>/` and sends one Bark notification grouped as `media-io-sitemap`. A failed sitemap fetch or Bark push fails the run before the baseline is updated, so the next run can retry.

## Local use

From the repository root:

```bash
python3 media_io_sitemap_crawler/media_io_sitemap_crawler.py --bootstrap
python3 media_io_sitemap_crawler/media_io_sitemap_crawler.py
python3 -m unittest discover -s media_io_sitemap_crawler/tests
```

`--bootstrap` is for the first run only; it records existing URLs without alerting.

## Deployment

`.github/workflows/monitor-media-io.yml` runs every six hours, offset from the Dreamina workflow. It uses the repository's existing `BARK_DEVICE_KEY` and optional `BARK_SERVER_URL` secrets. The Action commits its state and reports to the repository. No third-party Python packages are required.
