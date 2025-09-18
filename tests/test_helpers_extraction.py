from __future__ import annotations

import json
import types
import sys

import app.server as s


class _Norm:
	def __init__(self, title: str = "", entities_json: str | None = None) -> None:
		self.title = title
		self.entities_json = entities_json


def test_extract_events_and_sentiment_positive_multiple_events():
	title = "MegaCorp soars after earnings beat and big contract award"
	events, sentiment = s._extract_events_and_sentiment(title)
	assert set(events) >= {"earnings", "contract"}
	assert sentiment == "positive"


def test_extract_events_and_sentiment_negative_and_guidance():
	title = "StartUp plunges after weak guidance and results miss"
	events, sentiment = s._extract_events_and_sentiment(title)
	assert "guidance" in events
	assert "earnings" in events
	assert sentiment in {"negative", "neutral"}


def test_extract_events_and_sentiment_neutral_default():
	events, sentiment = s._extract_events_and_sentiment("Company announces update")
	assert events == []
	assert sentiment == "neutral"


def test_infer_symbol_code_prefers_entities_json_first_symbol():
	entities = json.dumps({"symbols": ["AAPL", "MSFT"]})
	norm = _Norm(title="Apple posts strong results", entities_json=entities)
	assert s._infer_symbol_code(norm) == "AAPL"


def test_infer_symbol_code_from_six_digit_code_in_title():
	norm = _Norm(title="Kweichow Moutai 600519 surges on earnings")
	assert s._infer_symbol_code(norm) == "600519"


def test_infer_symbol_code_from_uppercase_ticker_when_no_code():
	norm = _Norm(title="Apple Inc AAPL wins major contract")
	assert s._infer_symbol_code(norm) == "AAPL" 