from __future__ import annotations
from typing import Any, Dict, List, Optional
import threading
import time

from .config import get_config
from .metrics import snapshot as metrics_snapshot

# In-memory consecutive failure streaks per source (process lifetime)
_STREAK_LOCK = threading.Lock()
_SOURCE_FAILURE_STREAKS: Dict[str, int] = {}

# In-memory event sink for explicit alert events (e.g., scheduler circuit open)
_EVENTS_LOCK = threading.Lock()
_RECENT_EVENTS: List[Dict[str, Any]] = []
_MAX_EVENTS = 100


def _alerts_config() -> Dict[str, Any]:
	cfg = (get_config() or {}).get("alerts") or {}
	return {
		"error_rate_threshold": float(cfg.get("error_rate_threshold", 0.01)),
		"success_rate_min": float(cfg.get("success_rate_min", 0.99)),
		"latency_ms_p90_max": int(cfg.get("latency_ms_p90_max", 30000)),
		"consecutive_failures_threshold": int(cfg.get("consecutive_failures_threshold", 3)),
		# LLM-specific thresholds
		"llm_failure_rate_max": float(cfg.get("llm_failure_rate_max", 0.10)),
		"llm_latency_ms_p90_max": int(cfg.get("llm_latency_ms_p90_max", 15000)),
		"llm_cache_hit_rate_min": float(cfg.get("llm_cache_hit_rate_min", 0.05)),
	}


def _sum_per_source(per_source: Dict[str, Any], key: str) -> int:
	try:
		return sum(int((per_source[sid] or {}).get(key, 0)) for sid in list(per_source.keys()))
	except Exception:
		return 0


def log_event(key: str, level: str, message: str, **fields: Any) -> None:
	"""Record an explicit alert-like event into a bounded in-memory buffer."""
	evt = {"key": key, "level": level, "message": message, "ts": int(time.time() * 1000)}
	if fields:
		evt.update(fields)
	with _EVENTS_LOCK:
		_RECENT_EVENTS.append(evt)
		# bound size
		if len(_RECENT_EVENTS) > _MAX_EVENTS:
			del _RECENT_EVENTS[: (len(_RECENT_EVENTS) - _MAX_EVENTS)]


def _drain_events() -> List[Dict[str, Any]]:
	with _EVENTS_LOCK:
		return list(_RECENT_EVENTS)


def evaluate() -> Dict[str, Any]:
	"""Evaluate alerts from the latest metrics snapshot and return a structured result.
	Return shape: {"alerts": [...], "summary": {...}}
	"""
	cfg = _alerts_config()
	ss: Dict[str, Any] = metrics_snapshot() or {}
	alerts: List[Dict[str, Any]] = []

	# 1) Overall pipeline error rate (process-level)
	success = int(ss.get("success") or 0)
	failure = int(ss.get("failure") or 0)
	total = success + failure
	if total > 0:
		error_rate = failure / max(total, 1)
		if error_rate > cfg["error_rate_threshold"]:
			alerts.append({
				"key": "overall_error_rate_high",
				"level": "critical",
				"message": f"Overall error rate {error_rate:.3f} exceeds {cfg['error_rate_threshold']:.3f}",
				"value": round(error_rate, 4),
				"threshold": cfg["error_rate_threshold"],
			})

	# 2) Aggregated fetch success rate across sources
	per_source: Dict[str, Any] = ss.get("last_ingestion_per_source") or {}
	attempted = _sum_per_source(per_source, "attempted")
	fetched = _sum_per_source(per_source, "fetched")
	if attempted > 0:
		fetch_rate = fetched / max(attempted, 1)
		if fetch_rate < cfg["success_rate_min"]:
			alerts.append({
				"key": "fetch_success_rate_low",
				"level": "critical",
				"message": f"Fetch success rate {fetch_rate:.3f} below {cfg['success_rate_min']:.3f}",
				"value": round(fetch_rate, 4),
				"threshold": cfg["success_rate_min"],
			})

	# 3) Latency p90 too high (overall pipeline)
	latency = ss.get("latency_ms") or {}
	p90 = int(latency.get("p90") or 0)
	if p90 > cfg["latency_ms_p90_max"]:
		alerts.append({
			"key": "latency_p90_high",
			"level": "warning",
			"message": f"Latency p90 {p90}ms exceeds {cfg['latency_ms_p90_max']}ms",
			"value": p90,
			"threshold": cfg["latency_ms_p90_max"],
		})

	# 4) Per-source consecutive failures (simple circuit-break indicator)
	with _STREAK_LOCK:
		thr = cfg["consecutive_failures_threshold"]
		for sid, stats in (per_source or {}).items():
			is_err = bool((stats or {}).get("error"))
			if is_err:
				_SOURCE_FAILURE_STREAKS[sid] = int(_SOURCE_FAILURE_STREAKS.get(sid, 0)) + 1
			else:
				_SOURCE_FAILURE_STREAKS[sid] = 0
		for sid, streak in list(_SOURCE_FAILURE_STREAKS.items()):
			if streak >= thr:
				alerts.append({
					"key": "source_consecutive_failures",
					"level": "critical",
					"message": f"Source {sid} has {streak} consecutive failures (>= {thr})",
					"source_id": sid,
					"value": streak,
					"threshold": thr,
				})

	# 5) LLM-specific alerts (failure rate, p90 latency, cache hit rate)
	llm = ss.get("llm") or {}
	llm_calls = int(llm.get("calls") or 0)
	llm_success = int(llm.get("success") or 0)
	llm_failure = int(llm.get("failure") or 0)
	if llm_calls > 0:
		llm_err_rate = llm_failure / max(llm_calls, 1)
		if llm_err_rate > cfg["llm_failure_rate_max"]:
			alerts.append({
				"key": "llm_failure_rate_high",
				"level": "critical",
				"message": f"LLM failure rate {llm_err_rate:.3f} exceeds {cfg['llm_failure_rate_max']:.3f}",
				"value": round(llm_err_rate, 4),
				"threshold": cfg["llm_failure_rate_max"],
			})
		# p90 latency
		llm_latency_p90 = int(((llm.get("latency_ms") or {}).get("p90")) or 0)
		if llm_latency_p90 > cfg["llm_latency_ms_p90_max"]:
			alerts.append({
				"key": "llm_latency_p90_high",
				"level": "warning",
				"message": f"LLM latency p90 {llm_latency_p90}ms exceeds {cfg['llm_latency_ms_p90_max']}ms",
				"value": llm_latency_p90,
				"threshold": cfg["llm_latency_ms_p90_max"],
			})
		# cache hit rate
		cache_hits = int(llm.get("cache_hits") or 0)
		cache_rate = (cache_hits / max(llm_calls, 1)) if llm_calls > 0 else 0.0
		if cache_rate < cfg["llm_cache_hit_rate_min"]:
			alerts.append({
				"key": "llm_cache_hit_rate_low",
				"level": "info",
				"message": f"LLM cache hit rate {cache_rate:.3f} below {cfg['llm_cache_hit_rate_min']:.3f}",
				"value": round(cache_rate, 4),
				"threshold": cfg["llm_cache_hit_rate_min"],
			})

	# Include any explicitly logged events (e.g., scheduler circuit open)
	events = _drain_events()
	if events:
		alerts.extend(events)

	return {
		"alerts": alerts,
		"summary": {
			"active": len(alerts),
			"thresholds": cfg,
			"runs": int(ss.get("runs") or 0),
			"last_market": ss.get("last_market"),
			"last_trade_date": ss.get("last_trade_date"),
		},
	} 