from __future__ import annotations

import json
from fastapi.testclient import TestClient

import app.server as s


def test_topn_evidence_sentiment_shape(monkeypatch) -> None:
	client = TestClient(s.app)
	# We don't have a real DB during unit tests (storage is optional). Endpoint should 404.
	# So we validate the Evidence model directly by constructing a TopNResponse sample.
	from app.models import Evidence
	sample = Evidence(news_ids=["1"], events=["earnings"], sentiment={"overall": "positive"})
	assert isinstance(sample.sentiment, dict)
	assert sample.sentiment.get("overall") == "positive" 