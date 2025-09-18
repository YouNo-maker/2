from fastapi.testclient import TestClient
from app.server import app

client = TestClient(app)


def test_topn_404_when_no_data():
    resp = client.get("/v1/news/topn", params={"market": "SSE", "as_of": "2025-09-10T00:00:00Z"})
    assert resp.status_code == 404
    assert resp.json()["detail"]


def test_plan_latest_404_when_no_data():
    resp = client.get("/v1/plan/latest", params={"trade_date": "2025-09-10", "market": "SSE"})
    assert resp.status_code == 404
    assert resp.json()["detail"]


def test_plan_validate_schema_errors():
    bad = {"trade_date": "2025-09-10", "market": "SSE", "entries": [{"symbol": "600000"}]}
    resp = client.post("/v1/plan/validate", json={"plan": bad})
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    # expect missing fields in entry
    assert any("entries[0].direction" in e for e in data["issues"]) 


def test_topn_happy_path():
    import pytest
    try:
        from app.storage import get_session, NormalizedNews, TopCandidate
    except Exception:
        pytest.skip("storage not available; skipping happy-path DB test")

    with get_session() as session:
        nn = NormalizedNews(
            source_id="test",
            url="https://example.com/news/1",
            title="Example Headline",
            text="Body",
            published_at="2025-09-10T08:00:00Z",
            entities_json='{"symbols": ["600000"], "sectors": ["Banks"]}',
        )
        session.add(nn)
        session.commit()
        session.refresh(nn)

        import json
        tc = TopCandidate(
            trade_date="2025-09-10",
            market="SSE",
            normalized_id=nn.id,
            rank=1,
            total_score=0.91,
            title=nn.title,
            url=nn.url,
            published_at=nn.published_at,
            components_json=json.dumps({"relevance": 0.8, "recency": 0.9}),
        )
        session.add(tc)
        session.commit()

    resp = client.get(
        "/v1/news/topn",
        params={"market": "SSE", "as_of": "2025-09-10T10:00:00Z", "n": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_of"].startswith("2025-09-10")
    assert data["market"] == "SSE"
    assert len(data["topn"]) >= 1
    first = data["topn"][0]
    assert first["aggregate_score"] >= 0.9
    assert "symbol" in first and "code" in first["symbol"]
    # new optional metadata
    assert "sectors" in first and first["sectors"][0] == "Banks"
    assert "source_id" in first
    assert "rank" in first and first["rank"] == 1
    # diversity summary may be None if not configured; allow both
    assert "diversity" in data


def test_topn_group_by_source_and_sector():
    import pytest
    try:
        from app.storage import get_session, NormalizedNews, TopCandidate
    except Exception:
        pytest.skip("storage not available; skipping group_by tests")

    with get_session() as session:
        # clear and insert two items with different sectors and same source
        import json
        n1 = NormalizedNews(
            source_id="srcA",
            url="https://example.com/news/2",
            title="BankA results surge 600001",
            text="Body",
            published_at="2025-09-10T08:10:00Z",
            entities_json=json.dumps({"symbols": ["600001"], "sectors": ["Banks"]}),
        )
        n2 = NormalizedNews(
            source_id="srcA",
            url="https://example.com/news/3",
            title="TechC contract win 600002",
            text="Body",
            published_at="2025-09-10T08:20:00Z",
            entities_json=json.dumps({"symbols": ["600002"], "sectors": ["Tech"]}),
        )
        session.add(n1)
        session.add(n2)
        session.commit()
        session.refresh(n1)
        session.refresh(n2)

        t1 = TopCandidate(
            trade_date="2025-09-10",
            market="SSE",
            normalized_id=n1.id,
            rank=1,
            total_score=0.88,
            title=n1.title,
            url=n1.url,
            published_at=n1.published_at,
            components_json=json.dumps({"relevance": 0.7}),
        )
        t2 = TopCandidate(
            trade_date="2025-09-10",
            market="SSE",
            normalized_id=n2.id,
            rank=2,
            total_score=0.87,
            title=n2.title,
            url=n2.url,
            published_at=n2.published_at,
            components_json=json.dumps({"relevance": 0.6}),
        )
        session.add(t1)
        session.add(t2)
        session.commit()

    # group_by sector
    resp1 = client.get(
        "/v1/news/topn",
        params={"market": "SSE", "as_of": "2025-09-10T10:00:00Z", "n": 2, "group_by": "sector"},
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["topn"][0]["group_key"] in ("Banks", "Tech")

    # group_by source
    resp2 = client.get(
        "/v1/news/topn",
        params={"market": "SSE", "as_of": "2025-09-10T10:00:00Z", "n": 2, "group_by": "source"},
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["topn"][0]["group_key"] == "srcA"


def test_plan_latest_happy_path():
    import pytest
    try:
        from app.storage import get_session, TradePlan
    except Exception:
        pytest.skip("storage not available; skipping happy-path DB test")

    with get_session() as session:
        tp = TradePlan(
            trade_date="2025-09-10",
            market="SSE",
            plan_json={
                "trade_date": "2025-09-10",
                "market": "SSE",
                "entries": [],
            },
            plan_md="# Plan\n",
        )
        session.add(tp)
        session.commit()

    resp = client.get(
        "/v1/plan/latest", params={"trade_date": "2025-09-10", "market": "SSE"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["trade_date"] == "2025-09-10"
    assert data["market"] == "SSE"
    assert data["plan_json"]["trade_date"] == "2025-09-10"
    assert data["plan_json"]["market"] == "SSE"
    assert "generated_at" in data
    assert "validation" in data 


def test_metrics_per_source_endpoint():
    # run a small ingestion via pipeline to populate metrics
    from app.pipeline.components import fetch_from_all_sources, get_last_ingest_by_source
    from unittest.mock import patch

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
        fetch_from_all_sources(cfg, market="SSE", trade_date="2025-09-10")
        stats = get_last_ingest_by_source()

    resp = client.get("/v1/metrics/per-source")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"rss1", "rss2"}
    assert data == stats

    # with summary
    resp2 = client.get("/v1/metrics/per-source?with_summary=true")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "sources" in data2 and "summary" in data2
    assert data2["sources"] == stats
    s = data2["summary"]
    assert s["total_sources"] == 2
    assert set(s["totals"].keys()) == {"attempted", "fetched", "kept"}
    assert "duration_ms" in s and set(s["duration_ms"].keys()) == {"avg", "max"}


def test_metrics_and_health_include_new_metrics_fields():
    # populate last snapshot via record_run path exercised by previous tests
    m = client.get("/v1/metrics").json()
    assert "last_http_cache" in m
    assert "last_diversity" in m
    assert "last_source_diversity" in m

    h = client.get("/v1/health", params={"verbose": 1}).json()
    assert h["status"] == "ok"
    assert "metrics" in h and isinstance(h["metrics"], dict)
    assert "last_http_cache" in h["metrics"]
    assert "last_diversity" in h["metrics"]
    assert "last_source_diversity" in h["metrics"] 