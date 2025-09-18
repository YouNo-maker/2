from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import hashlib
import json
import time

from .llm_cache import cache_get, cache_set


def _simple_rules(title: str) -> Tuple[float, float]:
	t = (title or "").lower()
	event_weight = 0.8 if any(k in t for k in ("earnings", "contract", "merger", "m&a")) else 0.5
	if any(k in t for k in ("up", "surge", "beat", "win")):
		sentiment_strength = 0.6
	elif any(k in t for k in ("down", "fall", "miss", "loss")):
		sentiment_strength = 0.4
	else:
		sentiment_strength = 0.5
	return event_weight, sentiment_strength


def _content_hash(text: str) -> str:
	data = (text or "").encode("utf-8", errors="ignore")
	return hashlib.sha256(data).hexdigest()


def _call_deepseek_json(prompt: str, timeout_ms: int, base_url: str, api_key: Optional[str]) -> Optional[Dict[str, Any]]:
	# Minimal JSON function-call style prompt; return a dict or None on failure
	if not api_key:
		return None
	try:
		import httpx
		payload = {
			"model": "deepseek-chat",
			"temperature": 0.3,
			"messages": [
				{"role": "system", "content": "Extract event_weight (0..1) and sentiment_strength (0..1) from the title. Reply JSON only."},
				{"role": "user", "content": prompt},
			],
		}
		headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
		with httpx.Client(base_url=base_url, timeout=max(1.0, timeout_ms / 1000.0)) as cli:
			resp = cli.post("/chat/completions", headers=headers, json=payload)
			resp.raise_for_status()
			data = resp.json()
			# Best-effort parse: try to locate JSON in assistant content
			try:
				content = (((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content")
				if isinstance(content, str) and content.strip():
					return json.loads(content)
			except Exception:
				pass
			return None
	except Exception:
		return None


def tag_with_fallback(title: str, cfg: Dict[str, Any]) -> Tuple[float, float, Dict[str, Any]]:
	start = time.time()
	llm_cfg = (cfg.get("llm") or {}) if isinstance(cfg.get("llm"), dict) else {}
	prompt_version = str(llm_cfg.get("prompt_version") or "v1")
	enabled = bool(llm_cfg.get("tagger_enabled", False))
	cache_ttl_minutes = int(llm_cfg.get("cache_ttl_minutes") or 1440)
	cache_ttl_seconds = max(60, cache_ttl_minutes * 60)
	meta: Dict[str, Any] = {"degraded": False, "from_cache": False, "prompt_version": prompt_version}

	if not enabled:
		# rules only
		evt, sent = _simple_rules(title)
		meta["degraded"] = True
		return evt, sent, meta

	key = f"tagger:{_content_hash(title)}:{prompt_version}"
	cached = cache_get(key)
	if cached is not None:
		try:
			data = dict(cached)
			evt = float(data.get("event_weight", 0.5))
			sent = float(data.get("sentiment_strength", 0.5))
			meta["from_cache"] = True
			# metrics: count as success with cache_hit
			try:
				from .metrics import record_llm_call
				record_llm_call(outcome="success", duration_ms=int((time.time() - start) * 1000), cache_hit=True)
			except Exception:
				pass
			return evt, sent, meta
		except Exception:
			pass

	# Call LLM, fallback to rules on failure
	api_key = llm_cfg.get("api_key")
	base_url = llm_cfg.get("base_url") or "https://api.deepseek.com"
	timeout_ms = int(llm_cfg.get("timeout_ms") or 12000)
	resp = _call_deepseek_json(title, timeout_ms=timeout_ms, base_url=base_url, api_key=api_key)
	if isinstance(resp, dict):
		try:
			evt = float(resp.get("event_weight", 0.5))
			sent = float(resp.get("sentiment_strength", 0.5))
			# cache
			cache_set(key, {"event_weight": evt, "sentiment_strength": sent}, ttl_seconds=cache_ttl_seconds)
			# metrics
			try:
				from .metrics import record_llm_call
				record_llm_call(outcome="success", duration_ms=int((time.time() - start) * 1000), cache_hit=False)
			except Exception:
				pass
			return evt, sent, meta
		except Exception:
			pass

	# Fallback
	evt, sent = _simple_rules(title)
	meta["degraded"] = True
	try:
		from .metrics import record_llm_call
		record_llm_call(outcome="failure", duration_ms=int((time.time() - start) * 1000), cache_hit=False)
	except Exception:
		pass
	return evt, sent, meta 