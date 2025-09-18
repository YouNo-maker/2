from unittest.mock import patch
from app.pipeline.components import fetch_from_all_sources, get_last_ingest_by_source
from app.metrics import record_run, snapshot


def test_per_source_ingestion_metrics_and_snapshot():
	cfg = {
		"sources": [
			{"id": "rss1", "type": "rss", "url": "https://feed1"},
			{"id": "rss2", "type": "rss", "url": "https://feed2"},
		]
	}

	def _mock_fetch(url, limit=30, timeout=10, retries=0, qps=None):
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
		stats = get_last_ingest_by_source()
		assert set(stats.keys()) == {"rss1", "rss2"}
		# fetched counts from each, but final kept should be 3 total across sources
		assert stats["rss1"]["fetched"] == 2
		assert stats["rss2"]["fetched"] == 2
		kept_total = int(stats["rss1"].get("kept", 0)) + int(stats["rss2"].get("kept", 0))
		assert kept_total == len(items) == 3
		assert stats["rss1"]["attempted"] == 1 and stats["rss2"]["attempted"] == 1
		assert isinstance(stats["rss1"]["duration_ms"], int) and stats["rss1"]["duration_ms"] >= 0
		assert stats["rss1"]["fallback_used"] is False
		assert stats["rss1"]["error"] in (None, "")

	# Include in run snapshot
	record_run({
		"market": "SSE",
		"trade_date": "2025-09-10",
		"counts": {"ingested": len(items)},
		"dedupe_rate": 0.0,
		"timings_ms": {"ingestion": 1},
		"ingestion_per_source": stats,
	})
	ss = snapshot()
	assert ss.get("last_ingestion_per_source") == stats 