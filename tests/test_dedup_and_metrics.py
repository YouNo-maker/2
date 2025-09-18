from unittest.mock import patch
from urllib.error import HTTPError
from io import BytesIO

from app.pipeline.components import canonicalize_url, make_dedup_key
from app.sources import rss as rss_mod
from app.metrics import record_run, snapshot


def test_canonicalize_url_and_make_dedup_key():
	u1 = "https://Example.com/Path?a=1&utm_source=xx&b=2#frag"
	u2 = "https://example.com:443/Path?b=2&a=1&utm_medium=foo"
	u3 = "https://example.com/Path?a=1&b=2"
	k1 = canonicalize_url(u1)
	k2 = canonicalize_url(u2)
	k3 = canonicalize_url(u3)
	assert k1 == k2 == k3
	# make_dedup_key prefers URL, falls back to normalized title
	assert make_dedup_key(u1, None) == k1
	assert make_dedup_key(None, "  Hello\nWorld  ") == "hello world"


class _CaptureReq:
	def __init__(self, url, headers=None):
		self.url = url
		self.headers = headers or {}


def test_rss_conditional_requests_and_304_behavior():
	feed_url = "https://feed.test/rss"
	etag = '"abc123"'
	last_modified = "Wed, 10 Sep 2025 07:30:00 GMT"

	# First call: returns items and captures caching headers
	first_resp_xml = b"""
	<rss version=\"2.0\"><channel>
	<item><title>T1</title><link>https://x/a</link><pubDate>Wed, 10 Sep 2025 07:30:00 GMT</pubDate></item>
	</channel></rss>
	"""

	with patch.object(rss_mod, "Request", _CaptureReq):
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

		with patch.object(rss_mod, "urlopen", return_value=_Resp(first_resp_xml)) as uo:
			items = rss_mod.fetch_rss(feed_url)
			assert len(items) == 1
			# caches should be populated
			assert rss_mod._etag_cache.get(feed_url) == etag
			assert rss_mod._last_modified_cache.get(feed_url) == last_modified

		# Second call: ensure conditional headers are sent and 304 returns []
		captured_req = {}
		def _cap_request(url, headers=None):
			captured_req["url"] = url
			captured_req["headers"] = headers or {}
			return _CaptureReq(url, headers)

		with patch.object(rss_mod, "Request", side_effect=_cap_request):
			def _raise_304(req, timeout=10):
				raise HTTPError(feed_url, 304, "Not Modified", {}, None)
			with patch.object(rss_mod, "urlopen", side_effect=_raise_304):
				items2 = rss_mod.fetch_rss(feed_url)
				assert items2 == []
				# Verify conditional headers used
				assert captured_req["headers"].get("If-None-Match") == etag
				assert captured_req["headers"].get("If-Modified-Since") == last_modified


def test_metrics_runs_counter_increments():
	before = snapshot().get("runs", 0)
	record_run({"market": "SSE", "trade_date": "2025-09-10", "counts": {}, "dedupe_rate": 0.0, "timings_ms": {}})
	record_run({"market": "SSE", "trade_date": "2025-09-11", "counts": {}, "dedupe_rate": 0.0, "timings_ms": {}})
	after = snapshot().get("runs", 0)
	assert after >= before + 2


def test_snapshot_carries_http_cache_and_diversity_fields():
	div = {"pre": {"A": 5}, "post": {"A": 3}, "sector_cap_pct": 50}
	src_div = {"pre": {"rss1": 5}, "post": {"rss1": 3}}
	http_cache = {"rss": {"sent": 2, "not_modified": 1, "ok": 1, "hit_rate": 0.5}, "rest": {"sent": 0, "not_modified": 0, "ok": 0, "hit_rate": 0.0}, "total": {"sent": 2, "not_modified": 1, "ok": 1, "hit_rate": 0.5}}
	record_run({
		"market": "SSE",
		"trade_date": "2025-09-12",
		"counts": {"ingested": 3, "normalized": 3, "topn": 2},
		"dedupe_rate": 0.25,
		"dedupe": {"link": 0.1, "content": 0.2},
		"timings_ms": {"ingestion": 10, "normalize": 20, "score": 5, "select": 5},
		"ingestion_per_source": {"rss1": {"attempted": 1, "fetched": 2, "kept": 2, "duration_ms": 10, "fallback_used": False, "error": None}},
		"diversity": div,
		"source_diversity": src_div,
		"http_cache": http_cache,
	})
	ss = snapshot()
	assert ss.get("last_diversity") == div
	assert ss.get("last_source_diversity") == src_div
	assert ss.get("last_http_cache") == http_cache 