import os
import json
from unittest.mock import patch
from urllib.error import HTTPError

from app.sources import rss as rss_mod


def test_rss_persistent_cache_roundtrip(tmp_path):
	cache_file = tmp_path / "http_cache.json"
	os.environ["APP_CACHE_PATH"] = str(cache_file)

	feed_url = "https://feed.persist/rss"
	etag = '"tag-1"'
	last_modified = "Wed, 10 Sep 2025 07:30:00 GMT"

	# Ensure clean caches in module
	rss_mod._etag_cache.clear()
	rss_mod._last_modified_cache.clear()

	class _Resp:
		def __init__(self, data: bytes):
			self._data = data
			self.headers = {"ETag": etag, "Last-Modified": last_modified}
		def read(self):
			return self._data
		def __enter__(self):
			return self
		def __exit__(self, et, ev, tb):
			return False

	xml = b"""
	<rss version=\"2.0\"><channel>
	<item><title>X</title><link>https://x/a</link><pubDate>Wed, 10 Sep 2025 07:30:00 GMT</pubDate></item>
	</channel></rss>
	"""

	# First call writes cache
	with patch.object(rss_mod, "urlopen", return_value=_Resp(xml)):
		items = rss_mod.fetch_rss(feed_url)
		assert len(items) == 1

	# Verify file exists and content persisted
	assert cache_file.exists()
	data = json.loads(cache_file.read_text("utf-8"))
	assert data.get("etag", {}).get(feed_url) == etag
	assert data.get("last_modified", {}).get(feed_url) == last_modified

	# Simulate fresh process by clearing in-memory caches and reloading from file
	rss_mod._etag_cache.clear()
	rss_mod._last_modified_cache.clear()
	rss_mod._load_cache()
	assert rss_mod._etag_cache.get(feed_url) == etag
	assert rss_mod._last_modified_cache.get(feed_url) == last_modified

	captured = {}
	def _cap_request(url, headers=None):
		captured["headers"] = headers or {}
		return rss_mod.Request(url, headers=headers)

	# Now a 304 should return [] and send conditional headers from persisted cache
	with patch.object(rss_mod, "Request", side_effect=_cap_request):
		def _raise_304(req, timeout=10):
			raise HTTPError(feed_url, 304, "Not Modified", {}, None)
		with patch.object(rss_mod, "urlopen", side_effect=_raise_304):
			items2 = rss_mod.fetch_rss(feed_url)
			assert items2 == []
			assert captured["headers"].get("If-None-Match") == etag
			assert captured["headers"].get("If-Modified-Since") == last_modified 