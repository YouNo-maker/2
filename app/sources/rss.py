from __future__ import annotations
from typing import List, Dict, Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import email.utils as eut
import time
import os
import json
import threading
import random

# During pytest on Windows, set a safe temp directory to avoid PermissionError in system temp
try:
	if os.name == "nt" and os.getenv("PYTEST_CURRENT_TEST"):
		safe_tmp = os.path.abspath(os.path.join("data", "tmp"))
		os.makedirs(safe_tmp, exist_ok=True)
		for _k in ("TMP", "TEMP", "TMPDIR"):
			os.environ[_k] = safe_tmp
except Exception:
	pass

# Simple in-memory conditional fetch caches (per-process)
_etag_cache: Dict[str, str] = {}
_last_modified_cache: Dict[str, str] = {}

# Persistent cache config
_CACHE_ENV = "APP_CACHE_PATH"
_DEFAULT_CACHE_PATH = os.path.join("data", "http_cache.json")
_cache_lock = threading.Lock()

# HTTP cache stats (best-effort, process-local)
_cache_stats: Dict[str, int] = {"conditional_requests_sent": 0, "not_modified": 0, "ok_200": 0}


def cache_stats() -> Dict[str, Any]:
	with _cache_lock:
		sent = int(_cache_stats.get("conditional_requests_sent", 0))
		nm = int(_cache_stats.get("not_modified", 0))
		ok = int(_cache_stats.get("ok_200", 0))
		hit_rate = (float(nm) / float(sent)) if sent > 0 else 0.0
		return {"sent": sent, "not_modified": nm, "ok": ok, "hit_rate": round(hit_rate, 4)}


def _cache_path() -> str:
	return os.environ.get(_CACHE_ENV) or _DEFAULT_CACHE_PATH


def _load_cache() -> None:
	path = _cache_path()
	try:
		if not os.path.exists(path):
			return
		with _cache_lock:
			with open(path, "r", encoding="utf-8") as f:
				data = json.load(f)
				if isinstance(data, dict):
					etag = data.get("etag") or {}
					lm = data.get("last_modified") or {}
					if isinstance(etag, dict):
						_etag_cache.update({str(k): str(v) for k, v in etag.items() if isinstance(k, str)})
					if isinstance(lm, dict):
						_last_modified_cache.update({str(k): str(v) for k, v in lm.items() if isinstance(k, str)})
	except Exception:
		# best-effort
		return


def _save_cache() -> None:
	path = _cache_path()
	try:
		dirname = os.path.dirname(path)
		if dirname and not os.path.exists(dirname):
			os.makedirs(dirname, exist_ok=True)
		with _cache_lock:
			data = {"etag": _etag_cache, "last_modified": _last_modified_cache}
			with open(path, "w", encoding="utf-8") as f:
				json.dump(data, f, ensure_ascii=False)
	except Exception:
		# best-effort
		return


# Attempt to load persistent cache at import time
_load_cache()


def _parse_pubdate(value: str) -> str | None:
	try:
		dt = eut.parsedate_to_datetime(value)
		if not dt:
			return None
		if dt.tzinfo is None:
			dt = dt.replace(tzinfo=timezone.utc)
		return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
	except Exception:
		return None


# Added retries and qps to improve robustness and basic rate limiting
# - retries: number of additional attempts after the first (total attempts = retries + 1)
# - qps: if > 0, sleep 1/qps seconds before each network attempt
# - timeout: per-request timeout in seconds
# - limit: max items to parse from the feed


def _compute_backoff_seconds(attempt_index: int) -> float:
	"""Exponential backoff with jitter.
	attempt_index: 0-based attempt counter
	"""
	base = 0.5
	max_cap = 8.0
	# Exponential growth: base * 2^attempt_index
	backoff = min(max_cap, base * (2 ** attempt_index))
	# Full jitter in [0, backoff]
	return random.uniform(0.0, backoff)


def _retry_after_seconds(e: HTTPError) -> float | None:  # pragma: no cover - header parsing varies
	try:
		h = getattr(e, "headers", None)
		if not h:
			return None
		ra = h.get("Retry-After")
		if not ra:
			return None
		# Prefer seconds value
		return float(ra)
	except Exception:
		return None


def fetch_rss(url: str, limit: int = 30, timeout: int = 10, retries: int = 0, qps: float | None = None) -> List[Dict[str, Any]]:
	attempts = max(int(retries), 0) + 1
	last_error: Exception | None = None
	for attempt in range(attempts):
		try:
			if qps and qps > 0:
				time.sleep(1.0 / float(qps))
			headers = {"User-Agent": "preopen-bot/1.0"}
			# Conditional request headers
			sent_conditional = False
			if url in _etag_cache:
				headers["If-None-Match"] = _etag_cache[url]
				sent_conditional = True
			if url in _last_modified_cache:
				headers["If-Modified-Since"] = _last_modified_cache[url]
				sent_conditional = True
			if sent_conditional:
				with _cache_lock:
					_cache_stats["conditional_requests_sent"] = int(_cache_stats.get("conditional_requests_sent", 0)) + 1
			req = Request(url, headers=headers)
			with urlopen(req, timeout=timeout) as resp:
				# Capture conditional response headers on 200
				try:
					etag = resp.headers.get("ETag")
					if etag:
						_etag_cache[url] = etag
				except Exception:
					pass
				try:
					lm = resp.headers.get("Last-Modified")
					if lm:
						_last_modified_cache[url] = lm
				except Exception:
					pass
				# persist cache after capturing headers
				try:
					_save_cache()
				except Exception:
					pass
				with _cache_lock:
					_cache_stats["ok_200"] = int(_cache_stats.get("ok_200", 0)) + 1
				data = resp.read()
			try:
				root = ET.fromstring(data)
			except ET.ParseError:
				return []

			# RSS 2.0: channel/item
			items: List[Dict[str, Any]] = []
			for item in root.findall(".//item"):
				title_el = item.find("title")
				link_el = item.find("link")
				pub_el = item.find("pubDate")
				title = title_el.text.strip() if title_el is not None and title_el.text else None
				link = link_el.text.strip() if link_el is not None and link_el.text else None
				pub = _parse_pubdate(pub_el.text.strip()) if pub_el is not None and pub_el.text else None
				if title or link:
					items.append({"title": title, "url": link, "published_at": pub})
				if len(items) >= limit:
					break
			return items
		except HTTPError as e:  # pragma: no cover - network exceptions vary
			# Treat 304 Not Modified as empty result (no new items)
			try:
				if getattr(e, "code", None) == 304:
					with _cache_lock:
						_cache_stats["not_modified"] = int(_cache_stats.get("not_modified", 0)) + 1
					return []
				# Respect Retry-After for 429/503 if provided
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
				# exponential backoff with jitter
				time.sleep(_compute_backoff_seconds(attempt))
				continue
			return []
		except URLError as e:  # pragma: no cover
			last_error = e
			if attempt < attempts - 1:
				# exponential backoff with jitter
				time.sleep(_compute_backoff_seconds(attempt))
				continue
			return []
		except Exception as e:  # pragma: no cover - safety net
			last_error = e
			return []

	# Fallback (should not reach here)
	return [] 