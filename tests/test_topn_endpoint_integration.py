from __future__ import annotations

import sys
import types
from fastapi.testclient import TestClient

import app.server as s


class _TopCandidateStub:
	# class-level attributes to satisfy attribute access in query building
	trade_date = object()
	market = object()
	rank = object()
	def __init__(self) -> None:
		self.normalized_id = 123
		self.rank = 1
		self.total_score = 0.87
		self.components = {"momentum": 0.5, "volume": 0.37}
		self.market = "CN"
		self.trade_date = "2025-09-10"
		self.title = "placeholder"


class _NormalizedNewsStub:
	def __init__(self, title: str) -> None:
		self.title = title
		self.entities_json = None


class _FakeSession:
	def __init__(self, row: _TopCandidateStub, norm: _NormalizedNewsStub) -> None:
		self._row = row
		self._norm = norm

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	class _ExecResult:
		def __init__(self, rows):
			self._rows = rows

		def all(self):
			return self._rows

		def first(self):
			return self._rows[0] if self._rows else None

	def exec(self, _stmt):
		return self._ExecResult([self._row])

	def get(self, _model, _id):
		return self._norm


class _Select:
	def __init__(self, _model):
		self._model = _model
	def where(self, *args, **kwargs):
		return self
	def order_by(self, *args, **kwargs):
		return self
	def limit(self, _n):
		return self


def test_topn_endpoint_returns_evidence_sentiment_dict(monkeypatch) -> None:
	# Stub sqlmodel.select to avoid dependency
	fake_sqlmodel = types.ModuleType("sqlmodel")
	setattr(fake_sqlmodel, "select", lambda model: _Select(model))
	monkeypatch.setitem(sys.modules, "sqlmodel", fake_sqlmodel)

	# Stub storage bindings in server
	row = _TopCandidateStub()
	norm = _NormalizedNewsStub("Kweichow Moutai 600519 surges on earnings")
	monkeypatch.setattr(s, "TopCandidate", _TopCandidateStub, raising=True)
	monkeypatch.setattr(s, "NormalizedNews", _NormalizedNewsStub, raising=True)
	monkeypatch.setattr(s, "get_session", lambda: _FakeSession(row, norm), raising=True)

	client = TestClient(s.app)
	r = client.get("/v1/news/topn", params={"market": "CN", "as_of": "2025-09-10T09:00:00Z", "n": 1})
	assert r.status_code == 200, r.text
	data = r.json()
	assert data["market"] == "CN"
	item = data["topn"][0]
	assert item["symbol"]["exchange"] == "CN"
	# code inferred from title numeric code
	assert item["symbol"]["code"] == "600519"
	assert item["evidence"]["sentiment"]["overall"] in {"positive", "neutral", "negative"}
	assert "earnings" in item["evidence"]["events"] 