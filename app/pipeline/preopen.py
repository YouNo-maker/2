from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Any, Callable, Optional
from ..models import DeadlinesSpec
from ..util_time import get_market_open_naive_local, compute_deadlines
import json
import hashlib


class PreOpenPipeline:
	@staticmethod
	def run(market: str, trade_date: str, deadlines: DeadlinesSpec, on_progress: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
		import time
		from app.metrics import record_run
		open_time = get_market_open_naive_local(market, trade_date)
		fetch_t, topn_t, plan_t = compute_deadlines(
			open_time,
			deadlines.fetch_min_before_open,
			deadlines.topn_min_before_open,
			deadlines.plan_min_before_open,
		)
		task_id = f"preopen_{market}_{trade_date}"
		result = {
			"task_id": task_id,
			"started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
			"deadlines": {
				"fetch": "T-45" if deadlines.fetch_min_before_open == 45 else f"T-{deadlines.fetch_min_before_open}",
				"topn": "T-35" if deadlines.topn_min_before_open == 35 else f"T-{deadlines.topn_min_before_open}",
				"plan": "T-30" if deadlines.plan_min_before_open == 30 else f"T-{deadlines.plan_min_before_open}",
				"fetch_at": fetch_t.isoformat(),
				"topn_at": topn_t.isoformat(),
				"plan_at": plan_t.isoformat(),
			},
			"percent": 10,
			"metrics": {"stages": ["Scheduler", "Ingestion", "Normalize", "Score", "SelectTopN", "Plan"], "version": "m2"},
		}

		def _progress(stage: str, pct: int) -> None:
			if on_progress:
				on_progress(stage, pct)

		# Minimal synchronous pipeline for M1
		try:
			from ..config import get_config
			from .components import fetch_from_all_sources, normalize, score_items, select_top_n, generate_plan, make_dedup_key, detect_language_fast
			from ..storage import get_session, RawNews, NormalizedNews, Score, TopCandidate, TradePlan
			from sqlmodel import select
		except Exception:
			# Storage or components not available; return metadata only
			return result

		cfg = get_config()
		try:
			_progress("Ingestion", 20)
			as_of = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
			t0 = time.time()
			raw_items = fetch_from_all_sources(cfg, market, trade_date)
			t_ing = time.time()
			_progress("Normalize", 40)
			norm_items = normalize(raw_items)
			t_norm = time.time()
			_progress("Score", 60)
			scored_items = score_items(norm_items, cfg.get("scoring", {}).get("weights", {}), as_of)
			t_score = time.time()
			_progress("SelectTopN", 75)
			sector_cap = None
			try:
				sector_cap = int(cfg.get("scoring", {}).get("diversity", {}).get("sector_cap_pct", 60))
			except Exception:
				sector_cap = None
			# threshold from config: prefer min_aggregate_score, fallback to score_threshold
			try:
				thr_val = (cfg.get("scoring", {}) or {}).get("min_aggregate_score")
			except Exception:
				thr_val = None
			if thr_val is None:
				thr_val = (cfg.get("scoring", {}) or {}).get("score_threshold", 0.0)
			try:
				threshold = float(thr_val)
			except Exception:
				threshold = 0.0
			topn = select_top_n(scored_items, n=10, threshold=threshold, sector_cap_pct=sector_cap)
			t_sel = time.time()

			# diversity snapshot (best-effort): sector and source distributions before/after
			def _sector_of(si: Any) -> str:
				try:
					ents = si.normalized.entities if hasattr(si, "normalized") else None
					if isinstance(ents, dict):
						secs = ents.get("sectors")
						if isinstance(secs, list) and secs:
							return str(secs[0])
				except Exception:
					pass
				return "unknown"
			from collections import Counter
			pre = Counter(_sector_of(s) for s in scored_items)
			post = Counter(_sector_of(s) for s in topn)
			pre_src = Counter((getattr(getattr(s, "normalized", None), "source_id", "") or "") for s in scored_items)
			post_src = Counter((getattr(getattr(s, "normalized", None), "source_id", "") or "") for s in topn)

			# Metrics snapshot
			try:
				uniq_keys = len({make_dedup_key(getattr(r, "url", None), getattr(r, "title", None)) for r in raw_items})
				ingested = len(raw_items)
				normalized_cnt = len(norm_items)
				topn_cnt = len(topn)
				dedup_rate = 0.0 if ingested == 0 else max(0.0, 1.0 - uniq_keys / max(ingested, 1))
				from .components import get_last_ingest_by_source
				# link/content dedupe estimates on normalized set
				link_uniqs = len({getattr(n, "link_canon_hash", None) for n in norm_items if getattr(n, "link_canon_hash", None)})
				content_uniqs = len({getattr(n, "content_hash", None) for n in norm_items if getattr(n, "content_hash", None)})
				link_dedup_rate = 0.0 if normalized_cnt == 0 else max(0.0, 1.0 - link_uniqs / max(normalized_cnt, 1))
				content_dedup_rate = 0.0 if normalized_cnt == 0 else max(0.0, 1.0 - content_uniqs / max(normalized_cnt, 1))
				# Aggregate HTTP cache stats from sources
				try:
					from ..sources import rss as _rss
					from ..sources import rest as _rest
					rss_stats = _rss.cache_stats()
					rest_stats = _rest.cache_stats()
				except Exception:
					rss_stats = {"sent": 0, "not_modified": 0, "ok": 0, "hit_rate": 0.0}
					rest_stats = {"sent": 0, "not_modified": 0, "ok": 0, "hit_rate": 0.0}
				http_cache = {
					"rss": rss_stats,
					"rest": rest_stats,
					"total": {
						"sent": int(rss_stats.get("sent", 0)) + int(rest_stats.get("sent", 0)),
						"not_modified": int(rss_stats.get("not_modified", 0)) + int(rest_stats.get("not_modified", 0)),
						"ok": int(rss_stats.get("ok", 0)) + int(rest_stats.get("ok", 0)),
						"hit_rate": round(
							(
								(float(rss_stats.get("not_modified", 0)) + float(rest_stats.get("not_modified", 0)))
								/ max(1.0, float(rss_stats.get("sent", 0)) + float(rest_stats.get("sent", 0)))
							),
							4,
						),
					},
				}
				metrics = {
					"market": market,
					"trade_date": trade_date,
					"as_of": as_of,
					"counts": {"ingested": ingested, "normalized": normalized_cnt, "topn": topn_cnt},
					"dedupe_rate": round(dedup_rate, 4),
					"dedupe": {"link": round(link_dedup_rate, 4), "content": round(content_dedup_rate, 4)},
					"timings_ms": {
						"ingestion": int((t_ing - t0) * 1000),
						"normalize": int((t_norm - t_ing) * 1000),
						"score": int((t_score - t_norm) * 1000),
						"select": int((t_sel - t_score) * 1000),
					},
					"ingestion_per_source": get_last_ingest_by_source(),
					"diversity": {"pre": dict(pre), "post": dict(post), "sector_cap_pct": sector_cap},
					"source_diversity": {"pre": dict(pre_src), "post": dict(post_src)},
					"http_cache": http_cache,
				}
				record_run(metrics)
			except Exception:
				pass

			with get_session() as session:
				# Persist raw and normalized
				for r in raw_items:
					key = make_dedup_key(getattr(r, "url", None), getattr(r, "title", None))
					lang = detect_language_fast((getattr(r, "title", None) or "") + " " + (getattr(r, "url", None) or ""))
					content = (getattr(r, "title", None) or "") + "|" + (getattr(r, "url", None) or "")
					hash_val = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
					# Skip insert if duplicate already exists for this source
					exists = session.exec(
						select(RawNews).where(
							RawNews.source_id == (getattr(r, "source_id", None) or "demo"),
							RawNews.dedup_key == key,
						)
					).first()
					if exists:
						continue
					rn = RawNews(
						source_id=(getattr(r, "source_id", None) or "demo"),
						url=getattr(r, "url", None),
						title=getattr(r, "title", None),
						published_at=getattr(r, "published_at", None),
						fetched_at=as_of,
						hash=hash_val,
						dedup_key=key,
						lang=lang,
					)
					session.add(rn)
					session.commit()
					session.refresh(rn)

				for n in norm_items:
					nn = NormalizedNews(
						raw_id=None,
						source_id=n.source_id,
						url=n.url,
						title=n.title,
						text=n.text,
						published_at=n.published_at,
						quality=n.quality,
						entities_json=json.dumps(n.entities) if hasattr(n, "entities") and n.entities is not None else None,
						content_hash=getattr(n, "content_hash", None),
						link_canon_hash=getattr(n, "link_canon_hash", None),
					)
					session.add(nn)
					session.commit()
					session.refresh(nn)

				# Persist scores and topN
				nn_by_url = {n.url: n for n in session.exec(
						NormalizedNews.__table__.select()
					).all()}  # type: ignore

				# For simplicity: query latest normalized again to get IDs
				all_nn = session.exec(
					NormalizedNews.__table__.select()
				).all()  # type: ignore
				url_to_id = {}
				for row in all_nn:
					url_to_id[getattr(row, "url", None)] = getattr(row, "id", None)

				ranked = []
				for idx, s in enumerate(topn, start=1):
					nid = url_to_id.get(s.normalized.url)
					if not nid:
						continue
					# version from config if present
					weight_version = str(cfg.get("scoring", {}).get("version", "v1.0.0"))
					sc = Score(
						normalized_id=nid,
						relevance=s.components.get("relevance"),
						sentiment_strength=s.components.get("sentiment_strength"),
						event_weight=s.components.get("event_weight"),
						recency=s.components.get("recency"),
						source_trust=s.components.get("source_trust"),
						total=s.total,
						version=weight_version,
					)
					session.add(sc)
					session.commit()

					tc = TopCandidate(
						trade_date=trade_date,
						market=market,
						normalized_id=nid,
						rank=idx,
						total_score=s.total,
						title=s.normalized.title,
						url=s.normalized.url,
						published_at=s.normalized.published_at,
						components_json=json.dumps(s.components),
					)
					session.add(tc)
					session.commit()
					ranked.append(tc)

				# Plan based on top1 (if exists)
				best = topn[0] if topn else None
				_progress("Plan", 90)
				plan_json, plan_md = generate_plan(best, market, trade_date)
				# optional enrichment
				try:
					from .enricher import enrich_plan
					plan_json, plan_md = enrich_plan(plan_json, plan_md, cfg)
				except Exception:
					pass
				tp = TradePlan(trade_date=trade_date, market=market, plan_json=plan_json, plan_md=plan_md)
				session.add(tp)
				session.commit()
		except Exception:
			# Keep API responsive even if minimal pipeline fails
			pass

		_progress("Done", 100)
		return result 