from __future__ import annotations
from typing import Any, Dict, List, Optional
from collections import deque
import threading

# Keep last N runs for quick health snapshot
_MAX = 10
_lock = threading.Lock()
_recent: deque[Dict[str, Any]] = deque(maxlen=_MAX)
_totals: Dict[str, Any] = {
	"runs": 0,
	"last": None,
	"success": 0,
	"failure": 0,
	"llm": {"calls": 0, "success": 0, "failure": 0, "cache_hits": 0, "latencies_ms": [], "ttft_ms": []},
}


def record_run(run_metrics: Dict[str, Any]) -> None:
	with _lock:
		_recent.append(run_metrics)
		_totals["runs"] = int(_totals.get("runs", 0)) + 1
		_totals["last"] = run_metrics
		if run_metrics.get("error"):
			_totals["failure"] = int(_totals.get("failure", 0)) + 1
		else:
			_totals["success"] = int(_totals.get("success", 0)) + 1


def record_llm_call(outcome: str, duration_ms: int, cache_hit: bool, ttft_ms: Optional[int] = None) -> None:
	with _lock:
		m = _totals.get("llm") or {}
		m["calls"] = int(m.get("calls", 0)) + 1
		if cache_hit:
			m["cache_hits"] = int(m.get("cache_hits", 0)) + 1
		if outcome == "success":
			m["success"] = int(m.get("success", 0)) + 1
		else:
			m["failure"] = int(m.get("failure", 0)) + 1
		arr = m.get("latencies_ms") or []
		try:
			arr.append(int(duration_ms))
		except Exception:
			pass
		m["latencies_ms"] = arr
		if ttft_ms is not None:
			tt = m.get("ttft_ms") or []
			try:
				tt.append(int(ttft_ms))
			except Exception:
				pass
			m["ttft_ms"] = tt
		_totals["llm"] = m


def _latency_percentiles(values: List[int]) -> Dict[str, int]:
	if not values:
		return {"p50": 0, "p90": 0, "p99": 0}
	vals = sorted(int(v) for v in values if v is not None)
	if not vals:
		return {"p50": 0, "p90": 0, "p99": 0}
	import math
	def _pct(p: float) -> int:
		idx = max(0, min(len(vals) - 1, int(math.ceil(p * len(vals)) - 1)))
		return int(vals[idx])
	return {"p50": _pct(0.5), "p90": _pct(0.9), "p99": _pct(0.99)}


def snapshot() -> Dict[str, Any]:
	with _lock:
		last = _totals.get("last") or {}
		counts = last.get("counts") if isinstance(last, dict) else {}
		# compute simple latency percentiles from recent runs (plan stage total if available)
		latencies: List[int] = []
		for r in list(_recent):
			t = r.get("timings_ms") if isinstance(r, dict) else None
			if isinstance(t, dict):
				# sum stage timings if provided; else skip
				try:
					lat = int(sum(int(v) for v in t.values() if v is not None))
					latencies.append(lat)
				except Exception:
					pass
		# llm latency percentiles
		llm_tot = _totals.get("llm") or {}
		llm_p = _latency_percentiles([int(v) for v in (llm_tot.get("latencies_ms") or []) if v is not None])
		llm_ttft_p = _latency_percentiles([int(v) for v in (llm_tot.get("ttft_ms") or []) if v is not None])
		# cache stats (best-effort)
		cache_stats: Dict[str, int] = {}
		try:
			from .llm_cache import cache_stats as _cache_stats
			cache_stats = _cache_stats()
		except Exception:
			cache_stats = {}
		return {
			"runs": _totals.get("runs", 0),
			"last_market": last.get("market"),
			"last_trade_date": last.get("trade_date"),
			"last_counts": counts or {},
			"last_dedupe_rate": last.get("dedupe_rate"),
			"last_timings_ms": last.get("timings_ms"),
			"last_ingestion_per_source": last.get("ingestion_per_source"),
			"last_link_content_dedupe": last.get("dedupe", {}),
			"last_diversity": last.get("diversity"),
			"last_source_diversity": last.get("source_diversity"),
			"last_http_cache": last.get("http_cache"),
			"success": _totals.get("success", 0),
			"failure": _totals.get("failure", 0),
			"latency_ms": _latency_percentiles(latencies),
			"llm": {
				"calls": llm_tot.get("calls", 0),
				"success": llm_tot.get("success", 0),
				"failure": llm_tot.get("failure", 0),
				"cache_hits": llm_tot.get("cache_hits", 0),
				"latency_ms": llm_p,
				"ttft_ms": llm_ttft_p,
				"cache": cache_stats,
			},
		}


def reset() -> None:
	"""Reset all in-memory metrics (for tests)."""
	with _lock:
		_recent.clear()
		_totals.clear()
		_totals.update({
			"runs": 0,
			"last": None,
			"success": 0,
			"failure": 0,
			"llm": {"calls": 0, "success": 0, "failure": 0, "cache_hits": 0, "latencies_ms": [], "ttft_ms": []},
		}) 