from unittest.mock import patch
from app.sources import rss as rss_mod
from app.pipeline.components import fetch_from_all_sources, RawItem


SAMPLE_RSS = b"""
<rss version="2.0">
  <channel>
    <title>Demo Feed</title>
    <item>
      <title>Alpha earnings beat</title>
      <link>https://example.com/a</link>
      <pubDate>Wed, 10 Sep 2025 07:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Beta contract win</title>
      <link>https://example.com/b</link>
      <pubDate>Wed, 10 Sep 2025 07:35:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class DummyResp:
	def __init__(self, data: bytes):
		self._data = data
	def read(self):
		return self._data
	def __enter__(self):
		return self
	def __exit__(self, exc_type, exc, tb):
		return False


def test_fetch_rss_parser():
	with patch("app.sources.rss.urlopen", return_value=DummyResp(SAMPLE_RSS)):
		items = rss_mod.fetch_rss("https://feed")
		assert len(items) == 2
		assert items[0]["title"] == "Alpha earnings beat"
		assert items[0]["url"] == "https://example.com/a"
		assert items[0]["published_at"].endswith("Z")


def test_fetch_from_all_sources_aggregation_and_dedup():
	cfg = {
		"sources": [
			{"id": "rss1", "type": "rss", "url": "https://feed1"},
			{"id": "rss2", "type": "rss", "url": "https://feed2"},
		]
	}
	def _mock_fetch(url, limit=30, timeout=10):
		if url.endswith("feed1"):
			return [
				{"title": "A", "url": "https://x/a", "published_at": "2025-09-10T07:30:00Z"},
				{"title": "B", "url": "https://x/b", "published_at": "2025-09-10T07:31:00Z"},
			]
		return [
			{"title": "B", "url": "https://x/b", "published_at": "2025-09-10T07:31:00Z"},
			{"title": "C", "url": "https://x/c", "published_at": "2025-09-10T07:32:00Z"},
		]
	with patch("app.sources.rss.fetch_rss", side_effect=_mock_fetch):
		items = fetch_from_all_sources(cfg, market="SSE", trade_date="2025-09-10")
		urls = [i.url for i in items]
		assert urls == ["https://x/a", "https://x/b", "https://x/c"]
		assert all(isinstance(i, RawItem) for i in items) 