from __future__ import annotations
from typing import Any, Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json
import time
import random
import os
import threading


def _compute_backoff_seconds(attempt_index: int) -> float:
	base = 0.5
	max_cap = 8.0
	backoff = min(max_cap, base * (2 ** attempt_index))
	return random.uniform(0.0, backoff)


# Simple in-memory conditional caches (shared via file persistence)
_ETAG_CACHE: Dict[str, str] = {}
_LAST_MODIFIED_CACHE: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_ENV = "APP_CACHE_PATH"
_DEFAULT_CACHE_PATH = os.path.join("data", "http_cache.json")

# HTTP cache stats (best-effort)
_STATS: Dict[str, int] = {"conditional_requests_sent": 0, "not_modified": 0, "ok_200": 0}


def cache_stats() -> Dict[str, Any]:
	with _CACHE_LOCK:
		sent = int(_STATS.get("conditional_requests_sent", 0))
		nm = int(_STATS.get("not_modified", 0))
		ok = int(_STATS.get("ok_200", 0))
		hit_rate = (float(nm) / float(sent)) if sent > 0 else 0.0
		return {"sent": sent, "not_modified": nm, "ok": ok, "hit_rate": round(hit_rate, 4)}


def _cache_path() -> str:
	return os.environ.get(_CACHE_ENV) or _DEFAULT_CACHE_PATH


def _load_cache() -> None:
	path = _cache_path()
	try:
		if not os.path.exists(path):
			return
		with _CACHE_LOCK:
			with open(path, "r", encoding="utf-8") as f:
				data = json.load(f)
				if isinstance(data, dict):
					etag = data.get("etag") or {}
					lm = data.get("last_modified") or {}
					if isinstance(etag, dict):
						_ETAG_CACHE.update({str(k): str(v) for k, v in etag.items() if isinstance(k, str)})
					if isinstance(lm, dict):
						_LAST_MODIFIED_CACHE.update({str(k): str(v) for k, v in lm.items() if isinstance(k, str)})
	except Exception:
		return


def _save_cache() -> None:
	path = _cache_path()
	try:
		dirname = os.path.dirname(path)
		if dirname and not os.path.exists(dirname):
			os.makedirs(dirname, exist_ok=True)
		with _CACHE_LOCK:
			data = {"etag": _ETAG_CACHE, "last_modified": _LAST_MODIFIED_CACHE}
			with open(path, "w", encoding="utf-8") as f:
				json.dump(data, f, ensure_ascii=False)
	except Exception:
		return


# Load cache on import
_load_cache()


def _retry_after_seconds(e: HTTPError) -> float | None:  # pragma: no cover - header parsing varies
	try:
		h = getattr(e, "headers", None)
		if not h:
			return None
		ra = h.get("Retry-After")
		if not ra:
			return None
		return float(ra)
	except Exception:
		return None


def _extract_items(payload: Any, item_path: str) -> List[Dict[str, Any]]:
	# item_path supports dot.notation to traverse dicts; final value must be list
	if not item_path:
		return payload if isinstance(payload, list) else []
	cur = payload
	for part in str(item_path).split("."):
		if isinstance(cur, dict):
			cur = cur.get(part)
		else:
			return []
	return cur if isinstance(cur, list) else []


def fetch_rest(
	url: str,
	method: str = "GET",
	headers: Optional[Dict[str, str]] = None,
	params: Optional[Dict[str, Any]] = None,
	timeout: int = 10,
	retries: int = 0,
	qps: Optional[float] = None,
	item_path: str = "items",
	title_field: str = "title",
	url_field: str = "url",
	published_at_field: str = "published_at",
) -> List[Dict[str, Any]]:
	attempts = max(int(retries), 0) + 1
	last_error: Exception | None = None
	for attempt in range(attempts):
		try:
			if qps and qps > 0:
				time.sleep(1.0 / float(qps))
			final_url = url
			final_headers = dict(headers or {})
			# Conditional request headers
			sent_conditional = False
			if url in _ETAG_CACHE:
				final_headers["If-None-Match"] = _ETAG_CACHE[url]
				sent_conditional = True
			if url in _LAST_MODIFIED_CACHE:
				final_headers["If-Modified-Since"] = _LAST_MODIFIED_CACHE[url]
				sent_conditional = True
			if sent_conditional:
				with _CACHE_LOCK:
					_STATS["conditional_requests_sent"] = int(_STATS.get("conditional_requests_sent", 0)) + 1
			if params and method.upper() == "GET":
				from urllib.parse import urlencode
				qs = urlencode(params, doseq=True)
				sep = "&" if ("?" in final_url) else "?"
				final_url = f"{final_url}{sep}{qs}"
			req = Request(final_url, headers=final_headers, method=method.upper())
			# For non-GET, attach JSON body
			if method.upper() != "GET" and params:
				data = json.dumps(params).encode("utf-8")
				req.data = data  # type: ignore[attr-defined]
			with urlopen(req, timeout=timeout) as resp:
				# Capture conditional response headers on 200
				try:
					etag = resp.headers.get("ETag")
					if etag:
						_ETAG_CACHE[url] = etag
				except Exception:
					pass
				try:
					lm = resp.headers.get("Last-Modified")
					if lm:
						_LAST_MODIFIED_CACHE[url] = lm
				except Exception:
					pass
				try:
					_save_cache()
				except Exception:
					pass
				with _CACHE_LOCK:
					_STATS["ok_200"] = int(_STATS.get("ok_200", 0)) + 1
				raw = resp.read()
				payload = json.loads(raw.decode("utf-8", errors="ignore"))
			items = _extract_items(payload, item_path)
			out: List[Dict[str, Any]] = []
			for it in items:
				if not isinstance(it, dict):
					continue
				out.append(
					{
						"title": it.get(title_field),
						"url": it.get(url_field),
						"published_at": it.get(published_at_field),
					}
				)
			return out
		except HTTPError as e:
			# Treat 304 Not Modified as empty result
			try:
				if getattr(e, "code", None) == 304:
					with _CACHE_LOCK:
						_STATS["not_modified"] = int(_STATS.get("not_modified", 0)) + 1
					return []
				if getattr(e, "code", None) in (429, 503):
					delay = _retry_after_seconds(e)
					if delay is not None:
						time.sleep(max(0.0, float(delay)))
						if attempt < attempts - 1:
							continue
			except Exception:
				pass
			last_error = e
			if attempt < attempts - 1:
				time.sleep(_compute_backoff_seconds(attempt))
				continue
			return []
		except URLError as e:
			last_error = e
			if attempt < attempts - 1:
				time.sleep(_compute_backoff_seconds(attempt))
				continue
			return []
		except Exception as e:
			last_error = e
			return []
	# Fallback
	return [] 