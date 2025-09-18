from __future__ import annotations
import sys
import types
# Provide a minimal 'multipart' shim to avoid hard dependency during import time
if 'multipart' not in sys.modules:
	pkg = types.ModuleType('multipart')
	sub = types.ModuleType('multipart.multipart')
	def _parse_options_header(value: str):
		# minimal stub; not used in our endpoints
		return '', {}
	class _MultipartParser:  # pragma: no cover
		def __init__(self, *args, **kwargs):
			raise RuntimeError("multipart parsing not supported in this build")
	setattr(sub, 'parse_options_header', _parse_options_header)
	setattr(sub, 'MultipartParser', _MultipartParser)
	sys.modules['multipart'] = pkg
	sys.modules['multipart.multipart'] = sub

from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from .models import PreopenRunRequest, DeadlinesSpec, PreopenRunAccepted, PreopenStatus, TopNResponse, TopNItem, PlanLatestResponse, PlanValidateRequest, PlanValidateResponse, SymbolRef, Evidence, PreopenRetryRequest, PreopenCancelRequest, PreopenCancelResponse, PreopenJobsResponse, MetricsSnapshotResponse, AIAskRequest, AIAskResponse
from .models import AIChatRequest
from .config import get_config, get_llm_config
from .pipeline.preopen import PreOpenPipeline
from time import perf_counter
import threading
import logging
import os
import json
import re
import httpx
# LLM cache and metrics
try:
	from .llm_cache import make_cache_key, cache_get, cache_put
except Exception:  # pragma: no cover
	make_cache_key = None
	cache_get = None
	cache_put = None
try:
	from .metrics import record_llm_call
except Exception:  # pragma: no cover
	def record_llm_call(*args: Any, **kwargs: Any) -> None:
		return
# Storage
try:
	from .storage.db import init_db, get_session
	from .storage.models import TopCandidate, NormalizedNews, TradePlan
except Exception:  # pragma: no cover
	init_db = None
	get_session = None
	TopCandidate = None
	NormalizedNews = None
	TradePlan = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
	if init_db:
		init_db()
	_start_scheduler_if_enabled()
	try:
		yield
	finally:
		_stop_scheduler()

app = FastAPI(title="PreOpen News Driven Plan", lifespan=_lifespan)

# Fallback: ensure DB is initialized even if lifespan isn't triggered (e.g., some TestClient usages)
if init_db:
	try:
		init_db()
	except Exception:
		pass

# In-memory stores for simplicity
_jobs: Dict[str, Dict[str, Any]] = {}
_dedupe_index: Dict[str, str] = {}
_cancellation_flags: Dict[str, bool] = {}

_log = logging.getLogger("preopen.api")
# Avoid logging exceptions breaking tests or threads
try:
	logging.raiseExceptions = False  # type: ignore[attr-defined]
except Exception:
	pass
if not _log.handlers:
	if os.getenv("PYTEST_CURRENT_TEST"):
		# Silence logs under pytest to avoid stream handle races on Windows
		h = logging.NullHandler()
		_log.addHandler(h)
		_log.propagate = False
		_log.setLevel(logging.INFO)
	else:
		h = logging.StreamHandler()
		# If enabled, output structured JSON logs with common fields
		class JsonFormatter(logging.Formatter):
			def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
				payload: Dict[str, Any] = {
					"ts": getattr(record, "created", None),
					"level": record.levelname,
					"logger": record.name,
					"message": record.getMessage(),
				}
				# add common extras if present
				for key in ("task_id", "market", "trade_date", "stage", "source", "dedupe_key", "caller", "env"):
					val = getattr(record, key, None)
					if val is not None:
						payload[key] = val
				return json.dumps(payload, ensure_ascii=False)
		fmt_env = os.getenv("PREOPEN_JSON_LOGS")
		try:
			import json as _json  # ensure json available for JsonFormatter
			json = _json  # type: ignore
		except Exception:
			pass
		fmt = fmt_env and JsonFormatter() or logging.Formatter("%(asctime)s %(levelname)s %(message)s")
		h.setFormatter(fmt)
		_log.addHandler(h)
		_log.setLevel(logging.INFO)

# --- Scheduler globals ---
_scheduler_thread: Optional[threading.Thread] = None
_shutdown_event: threading.Event = threading.Event()
_scheduler_state: Dict[str, Any] = {"status": "stopped"}
# Circuit breaker state
_scheduler_fail_streak: int = 0
_scheduler_circuit_until_iso: Optional[str] = None


def _is_trading_day(dt_local: "datetime") -> bool:
	# Monday-Friday treated as trading days (minimal implementation)
	try:
		return dt_local.weekday() < 5
	except Exception:
		return True


def _format_date(dt_local: "datetime") -> str:
	return f"{dt_local.year:04d}-{dt_local.month:02d}-{dt_local.day:02d}"


def _has_job_for(market: str, trade_date: str) -> bool:
	job_key = f"preopen_{market}_{trade_date}"
	return (job_key in _dedupe_index) or (job_key in _jobs)


def _next_trading_day(dt_local: "datetime") -> "datetime":
	# Advance to next weekday
	from datetime import timedelta
	nd = dt_local + timedelta(days=1)
	while not _is_trading_day(nd):
		nd += timedelta(days=1)
	return nd


def _start_scheduler_if_enabled() -> None:
	global _scheduler_thread
	if _scheduler_thread and _scheduler_thread.is_alive():
		return
	_shutdown_event.clear()
	cfg = get_config()
	# Do not start scheduler in test runs
	if bool(os.getenv("PYTEST_CURRENT_TEST", "")):
		_log.info("scheduler.disabled in pytest")
		return
	if bool(os.getenv("DISABLE_SCHEDULER", "")):
		_log.info("scheduler.disabled via env")
		return
	# Minimal enablement: run if preopen config exists
	if not isinstance(cfg.get("preopen"), dict):
		return

	def _loop() -> None:
		from datetime import datetime, timedelta
		# Import inside loop to avoid module import-time cycles
		from .util_time import get_market_open_naive_local, is_trading_day, next_trading_day
		try:
			market = str(cfg.get("market") or "SSE")
			first_fetch_min = int(cfg.get("preopen", {}).get("first_fetch_minutes_before_open", 60))
			# Circuit breaker thresholds
			cb_threshold = int((cfg.get("alerts", {}) or {}).get("consecutive_failures_threshold", 3))
			cooldown_min = int((cfg.get("scheduler", {}) or {}).get("circuit_cooldown_minutes", 15))
			global _scheduler_fail_streak, _scheduler_circuit_until_iso
			while not _shutdown_event.is_set():
				now = datetime.now()
				# Ensure intraday watcher state during trading hours
				try:
					from .intraday.watcher import ensure_running_if_trading
					ensure_running_if_trading(market, now)
				except Exception:
					pass
				# If circuit is open, sleep until cooldown expires
				if _scheduler_circuit_until_iso:
					try:
						resume_at = datetime.fromisoformat(_scheduler_circuit_until_iso)
					except Exception:
						resume_at = now
					if now < resume_at:
						_scheduler_state.update({"status": "paused", "reason": "circuit_open", "resume_after": resume_at.isoformat(), "consecutive_failures": _scheduler_fail_streak})
						_shutdown_event.wait(timeout=max(5.0, (resume_at - now).total_seconds()))
						continue
					# cooldown elapsed; close circuit
					_scheduler_circuit_until_iso = None
					_scheduler_state.pop("resume_after", None)
					_scheduler_state.pop("reason", None)
					_scheduler_state["status"] = "running"

				if not is_trading_day(market, now):
					# Sleep until next trading day morning 06:00 local
					next_day = next_trading_day(market, now)
					wake = next_day.replace(hour=6, minute=0, second=0, microsecond=0)
					_scheduler_state.update({"status": "running", "next_wake_at": wake.isoformat(), "reason": "non_trading_day"})
					sleep_s = max(5.0, (wake - now).total_seconds())
					_shutdown_event.wait(timeout=sleep_s)
					continue
				trade_date = _format_date(now)
				open_time = get_market_open_naive_local(market, trade_date)
				run_at = open_time - timedelta(minutes=first_fetch_min)
				_scheduler_state.update({"status": "running", "market": market, "trade_date": trade_date, "next_run_at": run_at.isoformat()})
				if now < run_at:
					# Sleep until run_at
					_shutdown_event.wait(timeout=max(1.0, (run_at - now).total_seconds()))
					continue
				# If we are already past open, schedule for next trading day
				if now >= open_time:
					next_day = next_trading_day(market, now)
					trade_date = _format_date(next_day)
					open_time = get_market_open_naive_local(market, trade_date)
					run_at = open_time - timedelta(minutes=first_fetch_min)
					_scheduler_state.update({"status": "running", "market": market, "trade_date": trade_date, "next_run_at": run_at.isoformat(), "reason": "past_open"})
					sleep_s = max(5.0, (run_at - now).total_seconds())
					_shutdown_event.wait(timeout=sleep_s)
					continue
				# Within pre-open window (>= T-60 and < open); fire once per date
				if _has_job_for(market, trade_date):
					# Already triggered; sleep a bit and re-evaluate
					_shutdown_event.wait(timeout=60.0)
					continue
				try:
					_log.info("scheduler.trigger market=%s trade_date=%s dedupe_key=%s", market, trade_date, f"preopen_{market}_{trade_date}")
					req = PreopenRunRequest(market=market, trade_date=trade_date, deadlines=None, dedupe_key=None, async_run=True, force_recompute=False)
					# Use internal call to reuse idempotency and background worker
					run_preopen_pipeline(req, x_caller="scheduler", x_env=os.getenv("APP_ENV", ""))
					_scheduler_state.update({"last_triggered_trade_date": trade_date, "last_triggered_at": datetime.now().isoformat()})
					# success -> reset streak
					_scheduler_fail_streak = 0
				except Exception as e:
					_scheduler_fail_streak = int(_scheduler_fail_streak) + 1
					_scheduler_state.update({"last_error": str(e), "last_error_at": datetime.now().isoformat(), "consecutive_failures": _scheduler_fail_streak})
					_log.exception("scheduler.error market=%s trade_date=%s", market, trade_date)
					# Open circuit on consecutive failures
					if _scheduler_fail_streak >= cb_threshold:
						resume_at = datetime.now() + timedelta(minutes=cooldown_min)
						_scheduler_circuit_until_iso = resume_at.isoformat()
						_scheduler_state.update({"status": "paused", "reason": "circuit_open", "resume_after": _scheduler_circuit_until_iso})
						# emit alert event for circuit open
						try:
							from .alerts import log_event
							log_event(
								key="alert.scheduler.circuit_open",
								level="critical",
								message=f"Scheduler circuit open after {_scheduler_fail_streak} consecutive failures",
								consecutive_failures=_scheduler_fail_streak,
								resume_after=_scheduler_circuit_until_iso,
							)
						except Exception:
							pass
						# sleep until cooldown expires or shutdown
						_shutdown_event.wait(timeout=max(5.0, (resume_at - datetime.now()).total_seconds()))
						continue
					# Back off for a minute on error
					_shutdown_event.wait(timeout=60.0)
					continue
				# After firing, wait until open + small buffer before considering next day
				now = datetime.now()
				buffer_after_open_s = 5 * 60
				_sleep_until = max(5.0, (open_time - now).total_seconds() + buffer_after_open_s)
				_shutdown_event.wait(timeout=_sleep_until)
		except Exception:
			_log.exception("scheduler.loop.crashed")

	_scheduler_thread = threading.Thread(target=_loop, name="preopen-scheduler", daemon=True)
	_scheduler_thread.start()
	_scheduler_state.update({"status": "running", "started": True})
	_log.info("scheduler.started thread=%s", _scheduler_thread.name)


def _stop_scheduler() -> None:
	_shutdown_event.set()
	thr = _scheduler_thread
	if thr and thr.is_alive():
		try:
			thr.join(timeout=5.0)
		except Exception:
			pass
	globals()["_scheduler_thread"] = None
	_scheduler_state.update({"status": "stopped"})


def _extract_events_and_sentiment(title: Optional[str]) -> tuple[List[str], Optional[str]]:
	t = (title or "").lower()
	events: List[str] = []
	if any(k in t for k in ("earnings", "results", "profit", "beat")):
		events.append("earnings")
	if any(k in t for k in ("contract", "order", "deal", "award")):
		events.append("contract")
	if any(k in t for k in ("merger", "acquisition", "m&a", "takeover")):
		events.append("m&a")
	if any(k in t for k in ("guidance", "forecast", "outlook")):
		events.append("guidance")
	# sentiment (use word-boundary regex to avoid substring false-positives like 'startup'/'update')
	pos_words = (
		"surge", "surges", "surged",
		"rise", "rises", "rose",
		"up",
		"beat", "beats", "beating",
		"win", "wins", "winning",
		"strong", "strengthens", "rally", "rallies",
	)
	neg_words = (
		"fall", "falls", "fell",
		"down",
		"miss", "misses", "missed",
		"loss", "losses",
		"weak", "weakness",
		"plunge", "plunges", "plunged",
		"plummet", "plummets",
		"drop", "drops", "dropped",
		"slump", "slumps", "slumped",
	)
	def _matches_any(text: str, words: tuple[str, ...]) -> bool:
		pattern = r"\b(?:%s)\b" % "|".join(re.escape(w) for w in words)
		return re.search(pattern, text) is not None
	if _matches_any(t, pos_words):
		sent = "positive"
	elif _matches_any(t, neg_words):
		sent = "negative"
	else:
		sent = "neutral"
	return events, sent


def _infer_symbol_code(norm: Optional["NormalizedNews"]) -> Optional[str]:
	if not norm:
		return None
	# Prefer explicit entities_json if available
	if getattr(norm, "entities_json", None):
		try:
			data = json.loads(norm.entities_json)
			if isinstance(data, dict):
				syms = data.get("symbols")
				if isinstance(syms, list) and syms:
					first = syms[0]
					if isinstance(first, str) and first.strip():
						return first.strip()
		except Exception:
			pass
	# Heuristic from title (e.g., 6-digit A-share codes or uppercase tickers up to 6 chars)
	title = getattr(norm, "title", "") or ""
	m = re.search(r"\b(\d{6})\b", title)
	if m:
		return m.group(1)
	m2 = re.search(r"\b([A-Z]{2,6})\b", title)
	if m2:
		return m2.group(1)
	return None


def _compose_topn_context_str(market: Optional[str], trade_date: Optional[str], limit: int = 5) -> Optional[str]:
	if not get_session or not TopCandidate:
		return None
	from datetime import datetime as _dt
	_use_market = market or (get_config().get("market") or "SSE")
	_use_trade_date = trade_date or _dt.utcnow().isoformat().split("T")[0]
	try:
		with get_session() as session:
			from sqlmodel import select
			stmt = select(TopCandidate).where(
				TopCandidate.trade_date == _use_trade_date,
				TopCandidate.market == _use_market,
			).order_by(TopCandidate.rank).limit(limit)
			rows: List[Any] = session.exec(stmt).all()
			if not rows:
				return None
			lines: List[str] = []
			for r in rows:
				try:
					norm = session.get(NormalizedNews, r.normalized_id)
				except Exception:
					norm = None
				symbol_code = _infer_symbol_code(norm) or str(r.normalized_id)
				events, sentiment = _extract_events_and_sentiment((getattr(norm, "title", None) or r.title or ""))
				parts = [f"#{r.rank}", f"symbol={symbol_code}", f"score={r.total_score:.3f}"]
				if events:
					parts.append(f"events={'|'.join(events)}")
				if sentiment:
					parts.append(f"sentiment={sentiment}")
				t = (r.title or getattr(norm, "title", None) or "").strip()
				if t:
					parts.append(f"title={t}")
				lines.append("; ".join(parts))
			return "\n".join(lines)
	except Exception:
		return None


def _call_deepseek(messages: List[Dict[str, Any]], temperature: float, max_tokens: Optional[int]) -> tuple[str, Optional[str], Optional[Dict[str, Any]]]:
	cfg = get_llm_config()
	api_key = cfg.get("api_key")
	base_url = str(cfg.get("base_url") or "https://api.deepseek.com")
	if not api_key:
		raise HTTPException(status_code=500, detail="DeepSeek API key not configured")
	url = base_url.rstrip("/") + "/chat/completions"
	payload: Dict[str, Any] = {
		"model": "deepseek-chat",
		"messages": messages,
		"temperature": float(temperature),
		"stream": False,
	}
	if max_tokens is not None:
		payload["max_tokens"] = int(max_tokens)
	# Optional cache
	cache_key = None
	if make_cache_key and cache_get:
		try:
			cache_key = make_cache_key("deepseek", "deepseek-chat", temperature, max_tokens, messages)
			cached = cache_get(cache_key)
			if cached:
				answer, model, usage = cached
				record_llm_call("success", 0, True)
				return answer or "", model, usage
		except Exception:
			pass
	try:
		t0 = perf_counter()
		timeout_ms = int(cfg.get("timeout_ms") or 12000)
		with httpx.Client(timeout=timeout_ms / 1000.0) as client:
			r = client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload)
			dur_ms = int((perf_counter() - t0) * 1000)
			if r.status_code >= 400:
				record_llm_call("failure", dur_ms, False)
				raise HTTPException(status_code=502, detail=f"DeepSeek error {r.status_code}: {r.text[:200]}")
			data = r.json()
			choices = data.get("choices") or []
			if not choices:
				record_llm_call("failure", dur_ms, False)
				raise HTTPException(status_code=502, detail="DeepSeek returned no choices")
			msg = (choices[0].get("message") or {})
			answer = (msg.get("content") or "").strip()
			model = data.get("model")
			usage = data.get("usage")
			record_llm_call("success", dur_ms, False)
			if cache_key and cache_put:
				try:
					cache_put(cache_key, answer, model, usage)
				except Exception:
					pass
			return answer, model, usage
	except HTTPException:
		raise
	except Exception as e:
		record_llm_call("failure", 0, False)
		raise HTTPException(status_code=502, detail=f"DeepSeek request failed: {e}")


@app.post("/v1/pipeline/preopen/run", response_model=PreopenRunAccepted, status_code=202)
def run_preopen_pipeline(
	req: PreopenRunRequest,
	x_caller: Optional[str] = Header(default=None, alias="X-Caller"),
	x_env: Optional[str] = Header(default=None, alias="X-Env"),
) -> Any:
	cfg = get_config()

	deadlines = req.deadlines or DeadlinesSpec(
		fetch_min_before_open=cfg["preopen"]["first_fetch_minutes_before_open"] - 15,  # default to T-45 if first_fetch is 60
		topn_min_before_open=cfg["preopen"]["topn_output_minutes_before_open"],
		plan_min_before_open=cfg["preopen"]["plan_output_minutes_before_open"],
	)

	task_id = f"preopen_{req.market}_{req.trade_date}"
	dedupe_key = req.dedupe_key or task_id

	if not req.force_recompute and dedupe_key in _dedupe_index:
		existing_task_id = _dedupe_index[dedupe_key]
		job = _jobs.get(existing_task_id)
		if job:
			return PreopenRunAccepted(task_id=existing_task_id, status=job.get("status", "pending"), deadlines=job.get("deadlines", {}))

	# Start job (synchronously create record)
	start_t = perf_counter()

	def _run_pipeline_background():
		try:
			_log.info(
				"pipeline.start task_id=%s market=%s trade_date=%s caller=%s env=%s",
				task_id,
				req.market,
				req.trade_date,
				x_caller,
				x_env,
				extra={"task_id": task_id, "market": req.market, "trade_date": req.trade_date, "caller": x_caller, "env": x_env},
			)
			def _on_progress(stage: str, pct: int) -> None:
				_jobs[task_id]["stage"] = stage
				_jobs[task_id]["percent"] = pct
				if _cancellation_flags.get(task_id):
					raise RuntimeError("cancelled")
			plan_meta = PreOpenPipeline.run(req.market, req.trade_date, deadlines, on_progress=_on_progress)
			# keep job's own id in record
			plan_meta["task_id"] = task_id
			_jobs[task_id].update({**plan_meta, "status": "completed", "stage": "Done"})
			_log.info("pipeline.done task_id=%s", task_id, extra={"task_id": task_id})
		except Exception as e:
			_jobs[task_id]["status"] = "failed"
			_jobs[task_id]["errors"].append(str(e))
			_log.exception("pipeline.error task_id=%s", task_id, extra={"task_id": task_id})
			# record failed run into metrics snapshot (best-effort)
			try:
				from app.metrics import record_run  # local import to avoid circular at module import
				record_run({
					"market": req.market,
					"trade_date": req.trade_date,
					"counts": {"ingested": 0, "normalized": 0, "topn": 0},
					"timings_ms": None,
					"error": str(e),
				})
			except Exception:
				pass

	# Create initial job record
	from .util_time import get_market_open_naive_local, compute_deadlines
	open_time = get_market_open_naive_local(req.market, req.trade_date)
	fetch_t, topn_t, plan_t = compute_deadlines(
		open_time,
		deadlines.fetch_min_before_open,
		deadlines.topn_min_before_open,
		deadlines.plan_min_before_open,
	)
	plan_meta_preview = {
		"task_id": task_id,
		"deadlines": {
			"fetch": "T-45" if deadlines.fetch_min_before_open == 45 else f"T-{deadlines.fetch_min_before_open}",
			"topn": "T-35" if deadlines.topn_min_before_open == 35 else f"T-{deadlines.topn_min_before_open}",
			"plan": "T-30" if deadlines.plan_min_before_open == 30 else f"T-{deadlines.plan_min_before_open}",
			"fetch_at": fetch_t.isoformat(),
			"topn_at": topn_t.isoformat(),
			"plan_at": plan_t.isoformat(),
		},
	}
	elapsed_ms = int((perf_counter() - start_t) * 1000)
	_jobs[task_id] = {
		"status": "running",
		"stage": "Scheduler",
		**plan_meta_preview,
		"errors": [],
		"metrics": {"elapsed_ms": elapsed_ms, "caller": x_caller or "", "env": x_env or ""},
		"request": {
			"market": req.market,
			"trade_date": req.trade_date,
			"deadlines_spec": {
				"fetch_min_before_open": deadlines.fetch_min_before_open,
				"topn_min_before_open": deadlines.topn_min_before_open,
				"plan_min_before_open": deadlines.plan_min_before_open,
			},
			"dedupe_key": dedupe_key,
			"async_run": req.async_run,
			"headers": {"X-Caller": x_caller or "", "X-Env": x_env or ""},
		},
	}
	_cancellation_flags.pop(task_id, None)
	_dedupe_index[dedupe_key] = task_id

	if req.async_run:
		# tiny delay to keep initial stage visible to immediate status checks
		def _starter():
			import time
			time.sleep(0.05)
			_run_pipeline_background()
		thread = threading.Thread(target=_starter, name=f"preopen-{task_id}", daemon=True)
		thread.start()
	else:
		# Synchronous run for callers explicitly opting in
		_run_pipeline_background()

	return PreopenRunAccepted(task_id=task_id, status="pending", deadlines=_jobs[task_id]["deadlines"])


@app.get("/v1/pipeline/preopen/status", response_model=PreopenStatus)
def preopen_status(task_id: str) -> Any:
	job = _jobs.get(task_id)
	if not job:
		raise HTTPException(status_code=404, detail="task not found")
	return PreopenStatus(
		task_id=task_id,
		status=job.get("status", "running"),
		stage=job.get("stage"),
		started_at=job.get("started_at"),
		percent=job.get("percent", 10),
		errors=job.get("errors", []),
		metrics=job.get("metrics", {}),
	)


@app.post("/v1/pipeline/preopen/retry", response_model=PreopenRunAccepted, status_code=202)
def retry_preopen(req: PreopenRetryRequest) -> Any:
	orig_id = req.task_id
	job = _jobs.get(orig_id)
	if not job:
		raise HTTPException(status_code=404, detail="task not found")

	# derive market/trade_date
	req_meta = job.get("request", {}) or {}
	market: Optional[str] = req_meta.get("market")
	trade_date: Optional[str] = req_meta.get("trade_date")
	m = re.match(r"^preopen_(.+)_(\d{4}-\d{2}-\d{2})$", orig_id)
	if m:
		market = market or m.group(1)
		trade_date = trade_date or m.group(2)
	if not market or not trade_date:
		raise HTTPException(status_code=400, detail="cannot infer market/trade_date from original task")

	# deadlines numbers
	cfg = get_config()
	dspec = (req_meta.get("deadlines_spec") or {})
	fetch_min = dspec.get("fetch_min_before_open")
	topn_min = dspec.get("topn_min_before_open")
	plan_min = dspec.get("plan_min_before_open")
	if fetch_min is None or topn_min is None or plan_min is None:
		d = job.get("deadlines", {})
		def _parse_t(v: Any) -> Optional[int]:
			try:
				s = str(v)
				return int(s.replace("T-", "")) if s.startswith("T-") else None
			except Exception:
				return None
		fetch_min = fetch_min or _parse_t(d.get("fetch")) or (cfg["preopen"]["first_fetch_minutes_before_open"] - 15)
		topn_min = topn_min or _parse_t(d.get("topn")) or cfg["preopen"]["topn_output_minutes_before_open"]
		plan_min = plan_min or _parse_t(d.get("plan")) or cfg["preopen"]["plan_output_minutes_before_open"]
	deadlines = DeadlinesSpec(
		fetch_min_before_open=fetch_min,
		topn_min_before_open=topn_min,
		plan_min_before_open=plan_min,
	)

	# new id
	i = 1
	while f"{orig_id}_retry{i}" in _jobs:
		i += 1
	new_id = f"{orig_id}_retry{i}"

	start_t = perf_counter()

	def _run_pipeline_background_retry():
		try:
			_log.info(
				"pipeline.retry.start new_id=%s retry_of=%s market=%s trade_date=%s",
				new_id,
				orig_id,
				market,
				trade_date,
				extra={"task_id": new_id, "market": market, "trade_date": trade_date},
			)
			def _on_progress(stage: str, pct: int) -> None:
				_jobs[new_id]["stage"] = stage
				_jobs[new_id]["percent"] = pct
			plan_meta = PreOpenPipeline.run(market, trade_date, deadlines, on_progress=_on_progress)
			plan_meta["task_id"] = new_id
			_jobs[new_id].update({**plan_meta, "status": "completed", "stage": "Done"})
			_log.info("pipeline.retry.done new_id=%s", new_id, extra={"task_id": new_id})
		except Exception as e:
			_jobs[new_id]["status"] = "failed"
			_jobs[new_id]["errors"].append(str(e))
			_log.exception("pipeline.retry.error new_id=%s", new_id, extra={"task_id": new_id})

	from .util_time import get_market_open_naive_local, compute_deadlines
	open_time = get_market_open_naive_local(market, trade_date)
	fetch_t, topn_t, plan_t = compute_deadlines(
		open_time,
		deadlines.fetch_min_before_open,
		deadlines.topn_min_before_open,
		deadlines.plan_min_before_open,
	)
	plan_meta_preview = {
		"task_id": new_id,
		"deadlines": {
			"fetch": "T-45" if deadlines.fetch_min_before_open == 45 else f"T-{deadlines.fetch_min_before_open}",
			"topn": "T-35" if deadlines.topn_min_before_open == 35 else f"T-{deadlines.topn_min_before_open}",
			"plan": "T-30" if deadlines.plan_min_before_open == 30 else f"T-{deadlines.plan_min_before_open}",
			"fetch_at": fetch_t.isoformat(),
			"topn_at": topn_t.isoformat(),
			"plan_at": plan_t.isoformat(),
		},
	}
	elapsed_ms = int((perf_counter() - start_t) * 1000)
	_jobs[new_id] = {
		"status": "running",
		"stage": "Scheduler",
		**plan_meta_preview,
		"errors": [],
		"metrics": {"elapsed_ms": elapsed_ms, "retry_of": orig_id, "caller": (job.get("metrics", {}) or {}).get("caller", ""), "env": (job.get("metrics", {}) or {}).get("env", "")},
		"request": {
			"market": market,
			"trade_date": trade_date,
			"deadlines_spec": {
				"fetch_min_before_open": deadlines.fetch_min_before_open,
				"topn_min_before_open": deadlines.topn_min_before_open,
				"plan_min_before_open": deadlines.plan_min_before_open,
			},
			"dedupe_key": None,
			"async_run": req.async_run,
			"headers": (req_meta.get("headers") or {}),
		},
		"retry_of": orig_id,
	}

	if req.async_run:
		thread = threading.Thread(target=_run_pipeline_background_retry, name=f"preopen-{new_id}", daemon=True)
		thread.start()
	else:
		_run_pipeline_background_retry()

	return PreopenRunAccepted(task_id=new_id, status="pending", deadlines=_jobs[new_id]["deadlines"])


@app.get("/v1/pipeline/preopen/jobs", response_model=PreopenJobsResponse)
def list_jobs() -> Any:
	items: List[PreopenStatus] = []
	for tid, job in _jobs.items():
		items.append(
			PreopenStatus(
				task_id=tid,
				status=job.get("status", "running"),
				stage=job.get("stage"),
				started_at=job.get("started_at"),
				percent=job.get("percent", 10),
				errors=job.get("errors", []),
				metrics=job.get("metrics", {}),
			)
		)
	return PreopenJobsResponse(jobs=items)


@app.get("/v1/pipeline/preopen/job", response_model=PreopenStatus)
def get_job(task_id: str) -> Any:
	job = _jobs.get(task_id)
	if not job:
		raise HTTPException(status_code=404, detail="task not found")
	return PreopenStatus(
		task_id=task_id,
		status=job.get("status", "running"),
		stage=job.get("stage") or "Scheduler",
		started_at=job.get("started_at"),
		percent=job.get("percent", 10),
		errors=job.get("errors", []),
		metrics=job.get("metrics", {}),
	)


@app.post("/v1/pipeline/preopen/cancel", response_model=PreopenCancelResponse)
def cancel_job(req: PreopenCancelRequest) -> Any:
	tid = req.task_id
	job = _jobs.get(tid)
	if not job:
		raise HTTPException(status_code=404, detail="task not found")
	prev = job.get("status", "running")
	if prev in ("completed", "failed") and not req.force:
		return PreopenCancelResponse(task_id=tid, previous_status=prev, new_status=prev, accepted=False)
	# mark cancellation; background runner checks this flag via progress callback
	_cancellation_flags[tid] = True
	# optionally flip status to failed-cancelled if not started using progress
	if job.get("stage") in (None, "Scheduler"):
		job["status"] = "failed"
		job["errors"].append("cancelled")
		job["stage"] = "Cancelled"
	return PreopenCancelResponse(task_id=tid, previous_status=prev, new_status=job.get("status", prev), accepted=True)


@app.get("/v1/news/topn", response_model=TopNResponse)
def get_topn(
	market: str = Query(...),
	as_of: Optional[str] = Query(default=None),
	n: int = Query(5, ge=1, le=100),
	group_by: str = Query(default="sector", description="Grouping key for diversity hints: 'sector' or 'source'"),
) -> TopNResponse:
	if not get_session or not TopCandidate or not NormalizedNews:
		# Treat uninitialized storage as no data available
		raise HTTPException(status_code=404, detail="no candidates for market")
	# validate group_by
	if group_by not in ("sector", "source"):
		raise HTTPException(status_code=400, detail="group_by must be 'sector' or 'source'")
	# derive trade_date from as_of (date part) or today if omitted
	from datetime import datetime
	trade_date = (as_of or datetime.utcnow().isoformat() + "Z").split("T")[0]
	with get_session() as session:
		from sqlmodel import select  # local import to avoid hard dependency at module import time
		stmt = select(TopCandidate).where(
			TopCandidate.trade_date == trade_date,
			TopCandidate.market == market,
		)
		rows: List[Any] = session.exec(stmt).all()
		# If as_of is provided, filter out future-published items conservatively
		if as_of:
			try:
				rows = [r for r in rows if not getattr(r, "published_at", None) or getattr(r, "published_at") <= as_of]
			except Exception:
				pass
		# Sort deterministically: rank asc, then created_at desc (if available), then id desc (if available)
		from datetime import datetime as _dt
		def _ts(s: Optional[str]) -> float:
			if not s:
				return 0.0
			try:
				return _dt.fromisoformat(s.replace("Z", "+00:00")).timestamp()
			except Exception:
				return 0.0
		rows.sort(key=lambda r: (
			getattr(r, "rank", 0),
			-1.0 * _ts(getattr(r, "created_at", None)),
			-1 * int(getattr(r, "id", 0) or 0),
		))
		rows = rows[:n]
		if not rows:
			raise HTTPException(status_code=404, detail="no candidates for date/market")
		items: List[TopNItem] = []
		# Optional: fetch scores/components already embedded in TopCandidate.components_json
		for r in rows:
			# Attempt to infer symbol from NormalizedNews.entities_json or title
			norm: Optional[NormalizedNews] = None
			try:
				norm = session.get(NormalizedNews, r.normalized_id)
			except Exception:
				norm = None
			symbol_code = _infer_symbol_code(norm)
			symbol = SymbolRef(exchange=market, code=symbol_code or str(r.normalized_id))
			components = r.components or {}
			# Evidence enrichment from title keywords
			title_for_signals = (getattr(norm, "title", None) or r.title or "")
			events, sentiment = _extract_events_and_sentiment(title_for_signals)
			# sectors from entities_json if present
			sectors: List[str] = []
			if norm and getattr(norm, "entities_json", None):
				try:
					edata = json.loads(norm.entities_json)
					if isinstance(edata, dict):
						secs = edata.get("sectors")
						if isinstance(secs, list):
							sectors = [str(x) for x in secs if isinstance(x, (str, int))][:3]
				except Exception:
					sectors = []
			# determine group key
			if group_by == "sector":
				group_key = sectors[0] if sectors else None
			else:  # source
				group_key = getattr(norm, "source_id", None)
			# When grouping by source, if missing, do not fallback to title to avoid misleading grouping. For sector, fallback to title for display.
			if not group_key:
				group_key = (r.title or "") if group_by == "sector" else None
			items.append(
				TopNItem(
					symbol=symbol,
					aggregate_score=r.total_score,
					scores=components,
					evidence=Evidence(news_ids=[str(r.normalized_id)], events=events, sentiment={"overall": sentiment} if sentiment else None),
					sectors=sectors,
					source_id=getattr(norm, "source_id", None),
					rank=r.rank,
					group_key=group_key,
				)
			)
		cfg = get_config()
		weight_version = (cfg.get("scoring", {}) or {}).get("version") or "v1.0.0"
		diversity_cfg = (cfg.get("scoring", {}) or {}).get("diversity", {}) if isinstance(cfg.get("scoring", {}), dict) else {}
		sector_cap_pct = None
		try:
			sector_cap_pct = int(diversity_cfg.get("sector_cap_pct")) if diversity_cfg and diversity_cfg.get("sector_cap_pct") is not None else None
		except Exception:
			sector_cap_pct = None
		return TopNResponse(
			as_of=as_of or datetime.utcnow().isoformat() + "Z",
			market=market,
			topn=items,
			weight_version=weight_version,
			diversity={"sector_cap_pct": sector_cap_pct} if sector_cap_pct is not None else None,
		)


@app.post("/v1/ai/ask", response_model=AIAskResponse)
def ai_ask(req: AIAskRequest) -> Any:
	context_lines: List[str] = []
	if req.include_topn_context:
		ctx = _compose_topn_context_str(req.market, req.trade_date, limit=5)
		if ctx:
			context_lines.append("Top candidates:\n" + ctx)
	sys_prompt = "You are a helpful assistant for pre-open market planning. Answer concisely."
	user_content = req.question
	if context_lines:
		user_content = "\n\n".join(context_lines + ["Question:", req.question])
	messages = [
		{"role": "system", "content": sys_prompt},
		{"role": "user", "content": user_content},
	]
	temp = float(req.temperature if req.temperature is not None else get_llm_config().get("temperature", 0.3))
	answer, model, usage = _call_deepseek(messages, temperature=temp, max_tokens=req.max_tokens)
	return AIAskResponse(answer=answer, model=model, usage=usage)


@app.post("/v1/ai/chat")

def ai_chat(req: AIChatRequest) -> Any:
	# Compose optional TopN context
	msgs: List[Dict[str, Any]] = []
	if req.include_topn_context:
		ctx = _compose_topn_context_str(req.market, req.trade_date, limit=5)
		if ctx:
			msgs.append({"role": "system", "content": "Top candidates:\n" + ctx})
	# Append user-provided messages
	for m in (req.messages or []):
		msgs.append({"role": m.role, "content": m.content})
	# Ensure a system prompt exists
	has_system = any((m.get("role") == "system") for m in msgs)
	if not has_system:
		msgs.insert(0, {"role": "system", "content": "You are a helpful assistant for pre-open market planning. Answer concisely."})
	# Stream via SSE from DeepSeek, with cache and TTFT metrics
	cfg = get_llm_config()
	api_key = cfg.get("api_key")
	base_url = str(cfg.get("base_url") or "https://api.deepseek.com")
	if not api_key:
		raise HTTPException(status_code=500, detail="DeepSeek API key not configured")
	url = base_url.rstrip("/") + "/chat/completions"
	temperature = float(req.temperature if req.temperature is not None else cfg.get("temperature", 0.3))
	payload: Dict[str, Any] = {
		"model": "deepseek-chat",
		"messages": msgs,
		"temperature": temperature,
		"stream": True,
	}
	if req.max_tokens is not None:
		payload["max_tokens"] = int(req.max_tokens)

	# Try cache (non-streaming, we stream the cached content ourselves)
	cache_key = None
	cached = None
	if make_cache_key and cache_get:
		try:
			cache_key = make_cache_key("deepseek", "deepseek-chat", temperature, req.max_tokens, msgs)
			cached = cache_get(cache_key)
		except Exception:
			cached = None
	if isinstance(cached, tuple):
		cached_answer, cached_model, cached_usage = cached
		if isinstance(cached_answer, str) and cached_answer:
			def _cached_stream() -> Any:
				start = perf_counter()
				chunk = 120
				for i in range(0, len(cached_answer), chunk):
					part = cached_answer[i:i+chunk]
					if part:
						yield f"data: {json.dumps({'delta': part})}\n\n"
				dur_ms = int((perf_counter() - start) * 1000)
				try:
					record_llm_call("success", dur_ms, True, ttft_ms=0)
				except Exception:
					pass
			return StreamingResponse(_cached_stream(), media_type="text/event-stream")

	def _event_stream() -> Any:
		start = perf_counter()
		first_delta_ms: Optional[int] = None
		ok = False
		buf: List[str] = []
		try:
			with httpx.Client(timeout=(cfg.get("timeout_ms") or 12000) / 1000.0) as client:
				r = client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, stream=True)
				if r.status_code >= 400:
					yield f"data: {json.dumps({'error': f'DeepSeek error {r.status_code}'})}\n\n"
					try:
						record_llm_call("failure", int((perf_counter() - start) * 1000), False, ttft_ms=None)
					except Exception:
						pass
					return
				for line in r.iter_lines():
					if not line:
						continue
					try:
						text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
						if text.startswith("data: "):
							data_str = text[6:].strip()
							if data_str == "[DONE]":
								ok = True
								break
							chunk = json.loads(data_str)
							delta = (((chunk.get('choices') or [{}])[0].get('delta')) or {}).get('content')
							if delta:
								buf.append(delta)
								if first_delta_ms is None:
									first_delta_ms = int((perf_counter() - start) * 1000)
								yield f"data: {json.dumps({'delta': delta})}\n\n"
					except Exception:
						continue
		finally:
			dur_ms = int((perf_counter() - start) * 1000)
			try:
				record_llm_call("success" if ok else "failure", dur_ms, False, ttft_ms=first_delta_ms if ok else None)
			except Exception:
				pass
			if ok and cache_key and cache_put:
				try:
					full = "".join(buf)
					cache_put(cache_key, full, None, None)
				except Exception:
					pass

	return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.get("/v1/plan/latest", response_model=PlanLatestResponse)
def get_plan_latest(trade_date: str = Query(...), market: str = Query(...)) -> PlanLatestResponse:
	if not get_session or not TradePlan:
		raise HTTPException(status_code=404, detail="no plan for date/market")
	with get_session() as session:
		from sqlmodel import select  # local import
		stmt = TradePlan.select_latest(trade_date, market)
		row = session.exec(stmt).first()
		if not row:
			raise HTTPException(status_code=404, detail="no plan for date/market")
		# minimal validation summary if present in plan_json
		validation = row.plan_json.get("validation") if isinstance(row.plan_json, dict) else None
		if not isinstance(validation, dict):
			validation = {"passed": True, "issues": []}
		return PlanLatestResponse(
			market=row.market,
			trade_date=row.trade_date,
			plan_json=row.plan_json,
			plan_md=getattr(row, "plan_md", None),
			validation=validation,
			generated_at=row.created_at,
		)


@app.post("/v1/plan/validate", response_model=PlanValidateResponse)
def validate_plan(req: PlanValidateRequest) -> PlanValidateResponse:
	reasons: List[str] = []
	plan = req.plan or {}

	# minimal schema checks
	for key in ("trade_date", "market", "entries"):
		if key not in plan:
			reasons.append(f"missing field: {key}")
	entries = plan.get("entries")
	if isinstance(entries, list):
		for idx, entry in enumerate(entries):
			for k in ("symbol", "direction", "entry", "stop", "take_profit"):
				if k not in entry:
					reasons.append(f"entries[{idx}].{k} missing")
			# stricter: number checks and relationships
			try:
				entry_px = float(entry.get("entry")) if "entry" in entry else None
				stop_px = float(entry.get("stop")) if "stop" in entry else None
				tp_px = float(entry.get("take_profit")) if "take_profit" in entry else None
			except Exception:
				entry_px = stop_px = tp_px = None
				reasons.append(f"entries[{idx}] numeric fields must be numbers")
			direction = (entry.get("direction") or "").upper()
			if entry_px is not None and stop_px is not None and tp_px is not None:
				if direction not in ("LONG", "SHORT"):
					reasons.append(f"entries[{idx}].direction must be LONG or SHORT")
				else:
					if direction == "LONG":
						if not (stop_px < entry_px < tp_px):
							reasons.append(f"entries[{idx}] LONG requires stop < entry < take_profit")
					else:  # SHORT
						if not (tp_px < entry_px < stop_px):
							reasons.append(f"entries[{idx}] SHORT requires take_profit < entry < stop")
					# risk-reward >= 1.5
					r = abs(entry_px - stop_px)
					rew = abs(tp_px - entry_px)
					if r <= 0 or rew / r < 1.5:
						reasons.append(f"entries[{idx}] risk-reward must be >= 1.5")
	else:
		if "entries" in plan and not isinstance(plan["entries"], list):
			reasons.append("entries must be a list")

	severity = "error" if len(reasons) > 0 else None
	return PlanValidateResponse(passed=len(reasons) == 0, issues=reasons, severity=severity)


@app.get("/v1/health")
def health(verbose: int = Query(0, ge=0, le=1)) -> Dict[str, Any]:
	if not verbose:
		return {"status": "ok"}
	try:
		from app.metrics import snapshot
		from app.alerts import evaluate as eval_alerts
		return {"status": "ok", "metrics": snapshot(), "alerts": eval_alerts()}
	except Exception:
		return {"status": "ok", "metrics": {}, "alerts": {"alerts": [], "summary": {}}}


@app.get("/v1/scheduler/status")
def scheduler_status() -> Any:
	alive = bool(_scheduler_thread and _scheduler_thread.is_alive())
	state = dict(_scheduler_state)
	state["is_alive"] = alive
	return state


@app.post("/v1/scheduler/start")
def scheduler_start(force: int = Query(0, ge=0, le=1)) -> Any:
	if force:
		try:
			os.environ.pop("DISABLE_SCHEDULER", None)
		except Exception:
			pass
	_start_scheduler_if_enabled()
	return scheduler_status()


@app.post("/v1/scheduler/stop")
def scheduler_stop() -> Any:
	_stop_scheduler()
	return scheduler_status()


@app.post("/v1/scheduler/restart")
def scheduler_restart(force: int = Query(0, ge=0, le=1)) -> Any:
	_stop_scheduler()
	if force:
		try:
			os.environ.pop("DISABLE_SCHEDULER", None)
		except Exception:
			pass
	_start_scheduler_if_enabled()
	return scheduler_status()

@app.get("/v1/metrics", response_model=MetricsSnapshotResponse)
def get_metrics() -> Any:
	try:
		from app.metrics import snapshot
		data = snapshot()
		return data
	except Exception:
		return {
			"runs": 0,
			"last_market": None,
			"last_trade_date": None,
			"last_counts": {},
			"last_dedupe_rate": None,
			"last_timings_ms": None,
		}


@app.get("/v1/metrics/per-source")
def get_metrics_per_source(
	with_summary: bool = Query(False, description="If true, include aggregate summary across sources")
) -> Any:
	try:
		from app.metrics import snapshot
		data = snapshot()
		per_source = data.get("last_ingestion_per_source") or None
		if per_source is None or (isinstance(per_source, dict) and len(per_source) == 0):
			try:
				from app.pipeline.components import get_last_ingest_by_source
				per_source = get_last_ingest_by_source() or {}
			except Exception:
				per_source = {}
		# If not requesting summary, return the raw per-source mapping for backward compatibility
		if not with_summary:
			return per_source
		# Build simple aggregates
		try:
			ids = list(per_source.keys()) if isinstance(per_source, dict) else []
			attempted = sum(int((per_source[k] or {}).get("attempted", 0)) for k in ids)
			fetched = sum(int((per_source[k] or {}).get("fetched", 0)) for k in ids)
			kept = sum(int((per_source[k] or {}).get("kept", 0)) for k in ids)
			errors = sum(1 for k in ids if (per_source[k] or {}).get("error"))
			fallbacks = sum(1 for k in ids if bool((per_source[k] or {}).get("fallback_used")))
			durations = [int((per_source[k] or {}).get("duration_ms", 0)) for k in ids if (per_source[k] or {}).get("duration_ms") is not None]
			avg_ms = int(sum(durations) / len(durations)) if durations else 0
			max_ms = max(durations) if durations else 0
			return {
				"sources": per_source,
				"summary": {
					"total_sources": len(ids),
					"totals": {"attempted": attempted, "fetched": fetched, "kept": kept},
					"errors": {"count": errors},
					"fallbacks": {"count": fallbacks},
					"duration_ms": {"avg": avg_ms, "max": max_ms},
				},
			}
		except Exception:
			# if aggregation fails, still return raw mapping
			return per_source
	except Exception:
		return {}


@app.get("/v1/alerts")
def get_alerts() -> Dict[str, Any]:
	try:
		from app.alerts import evaluate as eval_alerts
		return eval_alerts()
	except Exception:
		return {"alerts": [], "summary": {}} 


@app.get("/v1/intraday/status")
def intraday_status() -> Any:
	try:
		from .intraday.watcher import watcher_status
		return watcher_status()
	except Exception as e:
		return {"running": False, "error": str(e)}


@app.post("/v1/intraday/start")
def intraday_start(market: Optional[str] = Query(None), trade_date: Optional[str] = Query(None), interval_minutes: Optional[int] = Query(None)) -> Any:
	try:
		cfg = get_config()
		mkt = market or str(cfg.get("market") or "SSE")
		from datetime import datetime as _dt
		td = trade_date or _dt.now().strftime("%Y-%m-%d")
		intr = (cfg.get("intraday") or {})
		iv = int(interval_minutes or intr.get("poll_interval_minutes") or 5)
		from .intraday.watcher import start_watcher, watcher_status
		start_watcher(mkt, td, iv)
		return watcher_status()
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"failed to start intraday watcher: {e}")


@app.post("/v1/intraday/stop")
def intraday_stop() -> Any:
	try:
		from .intraday.watcher import stop_watcher, watcher_status
		stop_watcher()
		return watcher_status()
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"failed to stop intraday watcher: {e}") 