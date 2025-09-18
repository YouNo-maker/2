from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import threading
try:
	from ..entities import resolve_entities_from_text
except Exception:  # pragma: no cover
	resolve_entities_from_text = None  # type: ignore
from ..config import get_config  # add near other imports where used
try:
	from ..tagger import tag_with_fallback as _tag_with_fallback
except Exception:  # pragma: no cover
	_tag_with_fallback = None  # type: ignore


@dataclass
class RawItem:
	source_id: str
	url: Optional[str]
	title: Optional[str]
	published_at: Optional[str]
	raw: Optional[str] = None


@dataclass
class NormalizedItem:
	source_id: str
	url: Optional[str]
	title: str
	text: str
	published_at: Optional[str]
	quality: float
	entities: Dict[str, Any]
	# Optional hashes populated by normalize()
	content_hash: Optional[str] = None
	link_canon_hash: Optional[str] = None


@dataclass
class ScoredItem:
	normalized: NormalizedItem
	components: Dict[str, float]
	total: float


def _now_utc_iso() -> str:
	return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# URL normalization and dedup helpers
# - canonicalize_url: lowercases scheme/host, strips fragments, removes tracking params, sorts query
# - make_dedup_key: prefer canonical URL; fallback to normalized title
TRACKING_QUERY_PARAMS = {
	"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
	"gclid", "fbclid", "igshid", "msclkid", "ref", "ref_src",
}


def canonicalize_url(url: Optional[str]) -> Optional[str]:
	if not url or not isinstance(url, str):
		return None
	try:
		p = urlparse(url.strip())
		if not p.scheme or not p.netloc:
			return url.strip()
		scheme = (p.scheme or "http").lower()
		netloc = (p.hostname or "").lower()
		if p.port and not ((scheme == "http" and p.port == 80) or (scheme == "https" and p.port == 443)):
			netloc = f"{netloc}:{p.port}"
		path = p.path or "/"
		# filter query params
		q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False) if k not in TRACKING_QUERY_PARAMS]
		q.sort(key=lambda kv: (kv[0], kv[1]))
		query = urlencode(q, doseq=True)
		return urlunparse((scheme, netloc, path, "", query, ""))
	except Exception:
		return url.strip()


def _normalize_text_for_key(text: Optional[str]) -> Optional[str]:
	if not text:
		return None
	s = str(text)
	s = re.sub(r"<[^>]+>", " ", s)
	s = re.sub(r"\s+", " ", s).strip().lower()
	return s or None


def make_dedup_key(url: Optional[str], title: Optional[str]) -> str:
	cu = canonicalize_url(url)
	if cu:
		return cu
	t = _normalize_text_for_key(title)
	return t or ""


def detect_language_fast(s: str) -> str:
	if not s:
		return "unknown"
	if re.search(r"[\u4e00-\u9fff]", s):
		return "zh"
	if re.search(r"[A-Za-z]", s):
		return "en"
	return "unknown"


def _sha256_hex(s: str) -> str:
	import hashlib
	return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


# ---------------- Ingestion (per-source) ----------------
_ingest_lock = threading.Lock()
_last_ingest_by_source: Dict[str, Dict[str, Any]] = {}


def _coerce_float(v: Any, d: Optional[float] = None) -> Optional[float]:
	try:
		if v is None:
			return d
		return float(v)
	except Exception:
		return d


def _coerce_int(v: Any, d: int) -> int:
	try:
		return int(v)
	except Exception:
		return d


def fetch_from_all_sources(cfg: Dict[str, Any], market: str, trade_date: str) -> List[RawItem]:
	sources = (cfg.get("sources") or []) if isinstance(cfg, dict) else []
	# global defaults
	g_timeout = _coerce_int(((cfg.get("network") or {}).get("timeout_sec")), 10)
	g_retries = _coerce_int(((cfg.get("network") or {}).get("retries")), 0)
	g_qps = _coerce_float(((cfg.get("network") or {}).get("qps")), None)
	g_conc = _coerce_int(((cfg.get("network") or {}).get("concurrency")), 1)
	results: List[RawItem] = []
	seen_keys: set[str] = set()
	per_source: Dict[str, Dict[str, Any]] = {}
	# concurrency via threads (lightweight; IO bound)
	threads: List[threading.Thread] = []
	sem = threading.Semaphore(max(1, g_conc))

	def _run_one(src: Dict[str, Any]) -> None:
		if not isinstance(src, dict):
			return
		sid = str(src.get("id") or "")
		stype = str(src.get("type") or "rss").lower()
		url = src.get("url")
		# per-source options
		retries = _coerce_int(src.get("retries"), g_retries)
		timeout = _coerce_int(src.get("timeout"), g_timeout)
		qps = _coerce_float(src.get("qps"), g_qps)
		headers = src.get("headers") if isinstance(src.get("headers"), dict) else None
		params = src.get("params") if isinstance(src.get("params"), dict) else None
		limit = _coerce_int(src.get("limit"), 30)
		start_ms = datetime.now(timezone.utc)
		fetched_count = 0
		kept_count = 0
		fallback_used = False
		error_msg: Optional[str] = None
		try:
			if stype == "rss":
				from ..sources.rss import fetch_rss
				# Include retries/qps/limit for M2 robustness; but tests may patch with reduced signature
				try:
					items = fetch_rss(url, limit=limit, timeout=timeout, retries=retries, qps=qps)
				except TypeError:
					items = fetch_rss(url, limit=limit, timeout=timeout)
			elif stype == "rest":
				from ..sources.rest import fetch_rest
				items = fetch_rest(url, method=str(src.get("method", "GET")), headers=headers, params=params, timeout=timeout, retries=retries, qps=qps, item_path=str(src.get("item_path", "items")), title_field=str(src.get("title_field", "title")), url_field=str(src.get("url_field", "url")), published_at_field=str(src.get("published_at_field", "published_at")))
			else:
				items = []
			fetched_count = len(items) if isinstance(items, list) else 0
			for it in (items or []):
				title = (it.get("title") if isinstance(it, dict) else None)
				link = (it.get("url") if isinstance(it, dict) else None)
				pub = (it.get("published_at") if isinstance(it, dict) else None)
				key = make_dedup_key(link, title)
				if key in seen_keys:
					continue
				seen_keys.add(key)
				results.append(RawItem(source_id=sid or stype, url=link, title=title, published_at=pub))
				kept_count += 1
		except Exception as e:
			error_msg = str(e)
		finally:
			end_ms = datetime.now(timezone.utc)
			duration_ms = int((end_ms - start_ms).total_seconds() * 1000)
			per_source[sid or stype] = {
				"attempted": 1,
				"fetched": fetched_count,
				"kept": kept_count,
				"duration_ms": duration_ms,
				"fallback_used": fallback_used,
				"error": error_msg,
			}
			sem.release()

	for src in sources:
		sem.acquire()
		t = threading.Thread(target=_run_one, args=(src,))
		t.daemon = True
		threads.append(t)
		t.start()

	for t in threads:
		t.join()

	with _ingest_lock:
		_last_ingest_by_source.clear()
		_last_ingest_by_source.update(per_source)

	return results


def get_last_ingest_by_source() -> Dict[str, Any]:
	with _ingest_lock:
		return dict(_last_ingest_by_source)


def normalize(items: List[RawItem]) -> List[NormalizedItem]:
	normalized: List[NormalizedItem] = []
	tag_re = re.compile(r"<[^>]+>")
	script_style_re = re.compile(r"<(script|style)[^>]*>.*?</\\1>", re.IGNORECASE | re.DOTALL)

	def strip_html(text: str) -> str:
		if not text:
			return ""
		no_ss = script_style_re.sub(" ", text)
		no_tags = tag_re.sub(" ", no_ss)
		return re.sub(r"\s+", " ", no_tags).strip()

	def detect_language(s: str) -> str:
		if not s:
			return "unknown"
		# crude heuristic: presence of CJK → zh; predominantly ascii letters → en
		if re.search(r"[\u4e00-\u9fff]", s):
			return "zh"
		if re.search(r"[A-Za-z]", s):
			return "en"
		return "unknown"

	for it in items:
		title_raw = (it.title or "").strip()
		title = strip_html(title_raw)
		text = title
		# quality: combine normalized length and minor boost if language confidently detected
		length_score = min(len(text) / 140.0, 1.0)
		lang = detect_language(text)
		lang_bonus = 0.05 if lang in ("en", "zh") else 0.0
		quality = round(min(1.0, 0.5 + 0.5 * length_score + lang_bonus), 3)
		ents: Dict[str, Any] = {"symbols": [], "sectors": []}
		if resolve_entities_from_text is not None:
			try:
				ents = resolve_entities_from_text(title)
			except Exception:
				ents = {"symbols": [], "sectors": []}
		# hashes
		canon = canonicalize_url(it.url)
		link_canon_hash = _sha256_hex(canon) if canon else None
		content_basis = f"{title}\n{canon or (it.url or '')}"
		content_hash = _sha256_hex(content_basis)
		normalized.append(
			NormalizedItem(
				source_id=it.source_id,
				url=it.url,
				title=title or "Untitled",
				text=text or "",
				published_at=it.published_at,
				quality=quality,
				entities=ents,
				content_hash=content_hash,
				link_canon_hash=link_canon_hash,
			)
		)
	return normalized


def simple_rule_tags(n: NormalizedItem) -> Tuple[float, float]:
	"""Returns (event_weight, sentiment_strength) with trivial rules.
	- event_weight: +0.8 if keyword like 'earnings'/'contract' in title, else 0.5
	- sentiment_strength: 0.6 if 'up'/'surge' in title, 0.4 if 'down'/'fall', else 0.5
	"""
	title = (n.title or "").lower()
	event_weight = 0.8 if any(k in title for k in ("earnings", "contract", "merger", "m\u0026a")) else 0.5
	if any(k in title for k in ("up", "surge", "beat", "win")):
		sentiment_strength = 0.6
	elif any(k in title for k in ("down", "fall", "miss", "loss")):
		sentiment_strength = 0.4
	else:
		sentiment_strength = 0.5
	return event_weight, sentiment_strength


def compute_recency(published_at: Optional[str], as_of_iso: Optional[str]) -> float:
	try:
		if not published_at or not as_of_iso:
			return 0.5
		t_pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
		t_asof = datetime.fromisoformat(as_of_iso.replace("Z", "+00:00"))
		delta_min = max((t_asof - t_pub).total_seconds() / 60.0, 0.0)
		# Map 0..180 min -> 1..0.2, clamp [0.2, 1]
		if delta_min <= 0:
			return 1.0
		score = max(1.0 - (delta_min / 180.0), 0.2)
		return round(score, 3)
	except Exception:
		return 0.5


def score_items(norms: List[NormalizedItem], weights: Dict[str, float], as_of_iso: Optional[str]) -> List[ScoredItem]:
	scored: List[ScoredItem] = []
	w_rel = float(weights.get("relevance", 0.25))
	w_sent = float(weights.get("sentiment_strength", 0.20))
	w_evt = float(weights.get("event_weight", 0.25))
	w_rec = float(weights.get("recency", 0.20))
	w_src = float(weights.get("source_trust", 0.10))

	cfg = get_config()
	use_llm_tagger = bool(((cfg.get("llm") or {}).get("tagger_enabled", False)))

	for n in norms:
		if _tag_with_fallback and use_llm_tagger:
			try:
				event_weight, sentiment_strength, meta = _tag_with_fallback(n.title, cfg)
				# best-effort: attach meta for downstream debugging if needed
				setattr(n, "_tag_meta", meta)
			except Exception:
				event_weight, sentiment_strength = simple_rule_tags(n)
		else:
			event_weight, sentiment_strength = simple_rule_tags(n)
		has_entities = False
		try:
			if isinstance(n.entities, dict):
				has_entities = bool((n.entities.get("symbols") or []) or (n.entities.get("sectors") or []))
		except Exception:
			has_entities = False
		base_rel = min(max(n.quality, 0.0), 1.0)
		relevance = min(base_rel + (0.1 if has_entities else 0.0), 1.0)
		recency = compute_recency(n.published_at, as_of_iso)
		source_trust = 0.8 if (n.source_id or "").startswith("rss") else 0.7
		total = (
			w_rel * relevance
			+ w_sent * sentiment_strength
			+ w_evt * event_weight
			+ w_rec * recency
			+ w_src * source_trust
		)
		components = {
			"relevance": round(relevance, 3),
			"sentiment_strength": round(sentiment_strength, 3),
			"event_weight": round(event_weight, 3),
			"recency": round(recency, 3),
			"source_trust": round(source_trust, 3),
		}
		scored.append(ScoredItem(normalized=n, components=components, total=round(total, 4)))
	return scored


def select_top_n(scored: List[ScoredItem], n: int, threshold: float, sector_cap_pct: Optional[int] = None) -> List[ScoredItem]:
	filtered = [s for s in scored if s.total >= threshold]
	filtered.sort(key=lambda s: s.total, reverse=True)
	if len(filtered) <= n:
		return filtered
	# Diversity: prefer grouping by sector if available; otherwise fall back to source_id
	from collections import defaultdict, deque
	groups: Dict[str, deque] = defaultdict(deque)
	order: List[str] = []
	# Detect sectors
	has_sector = False
	for s in filtered:
		ents = s.normalized.entities if isinstance(s.normalized.entities, dict) else {}
		secs = ents.get("sectors") if isinstance(ents, dict) else None
		if isinstance(secs, list) and len(secs) > 0:
			has_sector = True
			break
	for s in filtered:
		if has_sector:
			ents = s.normalized.entities if isinstance(s.normalized.entities, dict) else {}
			secs = ents.get("sectors") if isinstance(ents, dict) else None
			key = (secs[0] if isinstance(secs, list) and secs else "unknown")
		else:
			key = (s.normalized.source_id or "")
		if key not in groups:
			order.append(key)
		groups[key].append(s)
	result: List[ScoredItem] = []
	cap_pct = 100 if sector_cap_pct is None else max(1, min(100, int(sector_cap_pct)))
	max_per_group = max(1, int(n * cap_pct / 100))
	group_counts: Dict[str, int] = defaultdict(int)
	while len(result) < n and any(groups.values()):
		for key in list(order):
			if len(result) >= n:
				break
			if groups[key]:
				if group_counts[key] >= max_per_group:
					# skip this group this round
					pass
				else:
					result.append(groups[key].popleft())
					group_counts[key] += 1
			else:
				# remove exhausted group from rotation
				order.remove(key)
	if len(result) < n:
		# fill remaining with leftovers preserving original order
		leftovers: List[ScoredItem] = []
		for key in order:
			leftovers.extend(list(groups[key]))
		for s in leftovers:
			if len(result) >= n:
				break
			# honor group cap as well
			k = order[0] if not has_sector else ((s.normalized.entities or {}).get("sectors", ["unknown"])[0] if isinstance(s.normalized.entities, dict) else "unknown")
			if group_counts[k] >= max_per_group:
				continue
			result.append(s)
			group_counts[k] += 1
	return result





def generate_plan(top1: Optional[ScoredItem], market: str, trade_date: str) -> Tuple[Dict[str, Any], str]:
	if not top1:
		plan_json = {"trade_date": trade_date, "market": market, "entries": [], "version": "v1", "generated_at": _now_utc_iso()}
		# validation: no entries → passed=false with issue
		plan_json["validation"] = {"passed": False, "issues": ["no candidate above threshold"]}
		plan_md = f"# Plan {trade_date} {market}\n\n- No entry (no candidate above threshold)\n"
		return plan_json, plan_md

	# Minimal static numbers; in real impl use market features
	entry = 100.0
	stop = 95.0
	tp = 110.0
	confidence = round(float(top1.total), 3)
	plan_json = {
		"trade_date": trade_date,
		"market": market,
		"version": "v1",
		"generated_at": _now_utc_iso(),
		"entries": [
			{
				"symbol": top1.normalized.entities.get("symbols", ["DEMO1"])[0] if isinstance(top1.normalized.entities, dict) else "DEMO1",
				"direction": "LONG",
				"entry": entry,
				"stop": stop,
				"take_profit": tp,
				"rationale": top1.normalized.title,
				"evidence_source": top1.normalized.url,
				"confidence": confidence,
				"position_limit_pct": 10,
				"execution_window_min": 30,
			}
		],
	}
	plan_md = f"# Plan {trade_date} {market}\n\n- Entry: {entry}\n- Stop: {stop}\n- Take Profit: {tp}\n- Rationale: {top1.normalized.title}\n"
	return plan_json, plan_md 