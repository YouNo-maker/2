from __future__ import annotations

import json
import types

import pytest

from app.server import _extract_events_and_sentiment, _infer_symbol_code


class _NormStub:
	def __init__(self, *, entities_json: str | None = None, title: str | None = None) -> None:
		self.entities_json = entities_json
		self.title = title


def test_extract_events_and_sentiment_positive_keywords() -> None:
	events, sent = _extract_events_and_sentiment("Company wins big contract and earnings beat expectations")
	assert "contract" in events
	assert "earnings" in events
	assert sent == "positive"


def test_extract_events_and_sentiment_negative_keywords() -> None:
	events, sent = _extract_events_and_sentiment("Company issues weak guidance; shares fall")
	assert "guidance" in events
	assert sent == "negative"


def test_extract_events_and_sentiment_neutral() -> None:
	events, sent = _extract_events_and_sentiment("Company announces new product line")
	assert isinstance(events, list)
	assert sent == "neutral"


def test_infer_symbol_code_from_entities_json() -> None:
	payload = {"symbols": ["600519", "XYZ"]}
	norm = _NormStub(entities_json=json.dumps(payload), title=None)
	code = _infer_symbol_code(norm)
	assert code == "600519"


def test_infer_symbol_code_from_title_numeric() -> None:
	norm = _NormStub(entities_json=None, title="Kweichow Moutai 600519 surges on earnings")
	code = _infer_symbol_code(norm)
	assert code == "600519"


def test_infer_symbol_code_from_title_ticker() -> None:
	norm = _NormStub(entities_json=None, title="AAPL rises on strong iPhone sales")
	code = _infer_symbol_code(norm)
	assert code == "AAPL" 