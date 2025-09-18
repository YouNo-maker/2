import time
import types

import pytest

from app import tagger
from app.llm_cache import cache_set, cache_clear
from app.metrics import snapshot, reset as metrics_reset


@pytest.fixture(autouse=True)
def _clean_state():
	metrics_reset()
	cache_clear()
	yield
	metrics_reset()
	cache_clear()


def _cfg(enabled=True):
	return {
		"llm": {
			"tagger_enabled": enabled,
			"prompt_version": "test",
			"cache_ttl_minutes": 1,
			"api_key": "dummy",
			"base_url": "https://example.com",
			"timeout_ms": 100,
		}
	}


def test_cache_hit_records_llm_metrics():
	key_title = "ACME beats earnings expectations"
	# Preload cache with computed values
	cache_set(f"tagger:{tagger._content_hash(key_title)}:test", {"event_weight": 0.7, "sentiment_strength": 0.65}, ttl_seconds=60)
	evt, sent, meta = tagger.tag_with_fallback(key_title, _cfg(True))
	ss = snapshot()
	assert meta.get("from_cache") is True
	assert ss.get("llm", {}).get("calls") == 1
	assert ss.get("llm", {}).get("cache_hits") == 1
	assert ss.get("llm", {}).get("success") == 1


def test_llm_success_records_metrics(monkeypatch):
	calls = {"n": 0}
	def fake_call(prompt, timeout_ms, base_url, api_key):
		calls["n"] += 1
		return {"event_weight": 0.8, "sentiment_strength": 0.6}
	monkeypatch.setattr(tagger, "_call_deepseek_json", fake_call)
	evt, sent, meta = tagger.tag_with_fallback("Earnings beat and contract win", _cfg(True))
	ss = snapshot()
	assert meta.get("from_cache") is False
	assert ss.get("llm", {}).get("calls") == 1
	assert ss.get("llm", {}).get("success") == 1
	assert ss.get("llm", {}).get("cache_hits") == 0
	assert calls["n"] == 1


def test_llm_failure_records_metrics(monkeypatch):
	def fake_call(prompt, timeout_ms, base_url, api_key):
		return None
	monkeypatch.setattr(tagger, "_call_deepseek_json", fake_call)
	evt, sent, meta = tagger.tag_with_fallback("random title", _cfg(True))
	ss = snapshot()
	assert meta.get("degraded") is True
	assert ss.get("llm", {}).get("calls") == 1
	assert ss.get("llm", {}).get("failure") == 1
	assert ss.get("llm", {}).get("cache_hits") == 0 