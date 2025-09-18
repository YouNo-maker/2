from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import threading
import hashlib
import json
import time

# Simple in-memory cache for LLM answers
# Keyed by a stable fingerprint of (provider, model, temperature, max_tokens, messages)

_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_STATS = {
	"puts": 0,
	"hits": 0,
	"misses": 0,
	"size": 0,
}


def make_cache_key(provider: str, model: Optional[str], temperature: Optional[float], max_tokens: Optional[int], messages: Any) -> str:
	try:
		payload = {
			"provider": provider or "unknown",
			"model": model or "unknown",
			"temperature": float(temperature) if temperature is not None else None,
			"max_tokens": int(max_tokens) if max_tokens is not None else None,
			"messages": messages,
		}
		blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
		return hashlib.sha256(blob.encode("utf-8")).hexdigest()
	except Exception:
		# Fallback to string repr
		return hashlib.sha256(str(messages).encode("utf-8", errors="ignore")).hexdigest()


def cache_get(key: str) -> Optional[Any]:
	with _LOCK:
		entry = _CACHE.get(key)
		if entry is None:
			_STATS["misses"] = int(_STATS.get("misses", 0)) + 1
			return None
		# TTL check (optional)
		ttl = entry.get("ttl")
		if isinstance(ttl, (int, float)) and ttl > 0:
			try:
				if (time.time() - float(entry.get("ts", 0))) > float(ttl):
					# expired
					_CACHE.pop(key, None)
					_STATS["misses"] = int(_STATS.get("misses", 0)) + 1
					_STATS["size"] = len(_CACHE)
					return None
			except Exception:
				pass
		_STATS["hits"] = int(_STATS.get("hits", 0)) + 1
		# Return generic value if present
		if "value" in entry:
			return entry.get("value")
		# Otherwise return chat tuple (answer, model, usage) if present
		if "answer" in entry:
			return entry.get("answer"), entry.get("model"), entry.get("usage")
		return None


def cache_put(key: str, answer: str, model: Optional[str], usage: Optional[Dict[str, Any]]) -> None:
	with _LOCK:
		_CACHE[key] = {
			"answer": answer,
			"model": model,
			"usage": usage,
			"ts": time.time(),
		}
		_STATS["puts"] = int(_STATS.get("puts", 0)) + 1
		_STATS["size"] = len(_CACHE)


def cache_set(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
	"""Generic setter used by tagger and other components.
	Stores arbitrary JSON-serializable value with optional TTL.
	"""
	with _LOCK:
		_CACHE[key] = {
			"value": value,
			"ts": time.time(),
			"ttl": int(ttl_seconds) if ttl_seconds else None,
		}
		_STATS["puts"] = int(_STATS.get("puts", 0)) + 1
		_STATS["size"] = len(_CACHE)


def cache_stats() -> Dict[str, int]:
	with _LOCK:
		return {
			"puts": int(_STATS.get("puts", 0)),
			"hits": int(_STATS.get("hits", 0)),
			"misses": int(_STATS.get("misses", 0)),
			"size": int(_STATS.get("size", 0)),
		}


def cache_clear() -> None:
	with _LOCK:
		_CACHE.clear()
		_STATS["puts"] = 0
		_STATS["hits"] = 0
		_STATS["misses"] = 0
		_STATS["size"] = 0 