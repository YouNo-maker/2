#!/usr/bin/env python3
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from typing import Dict, Any

from app.storage.db import init_db, get_session
from app.storage.models import RawNews, NormalizedNews, Score, TopCandidate, TradePlan


def _now() -> str:
	return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def seed(trade_date: str, market: str, n: int) -> Dict[str, Any]:
	init_db()
	created = {"raw": 0, "normalized": 0, "scores": 0, "topn": 0, "plans": 0}
	as_of = _now()

	with get_session() as session:
		# Create Raw and Normalized
		normalized_ids = []
		for i in range(1, n + 1):
			url = f"https://example.com/{market}/{trade_date}/seed/{i}"
			title = f"[{market}] Seed headline {i} for {trade_date}"
			published = f"{trade_date}T07:{20 + i:02d}:00Z"

			r = RawNews(
				source_id="seed",
				url=url,
				title=title,
				published_at=published,
				fetched_at=as_of,
			)
			session.add(r)
			session.commit()
			session.refresh(r)
			created["raw"] += 1

			nn = NormalizedNews(
				raw_id=r.id,
				source_id="seed",
				url=url,
				title=title,
				text=title,
				published_at=published,
				quality=0.8,
				entities_json=None,
			)
			session.add(nn)
			session.commit()
			session.refresh(nn)
			normalized_ids.append(nn.id)
			created["normalized"] += 1

		# Scores and TopN
		for rank, nid in enumerate(normalized_ids, start=1):
			score_total = round(0.75 - (rank - 1) * 0.03, 4)
			sc = Score(
				normalized_id=nid,
				relevance=0.8,
				sentiment_strength=0.55,
				event_weight=0.6,
				recency=0.7,
				source_trust=0.8,
				total=score_total,
				version="v1",
			)
			session.add(sc)
			session.commit()
			created["scores"] += 1

			nn_row = session.get(NormalizedNews, nid)
			tc = TopCandidate(
				trade_date=trade_date,
				market=market,
				normalized_id=nid,
				rank=rank,
				total_score=score_total,
				title=nn_row.title if nn_row else None,
				url=nn_row.url if nn_row else None,
				published_at=nn_row.published_at if nn_row else None,
				components_json='{"relevance":0.8,"sentiment_strength":0.55,"event_weight":0.6,"recency":0.7,"source_trust":0.8}',
			)
			session.add(tc)
			session.commit()
			created["topn"] += 1

		# Plan (based on top1)
		plan_json = {
			"market": market,
			"trade_date": trade_date,
			"entries": [
				{"symbol": "DEMO", "side": "LONG", "entry": 10.0, "take_profit": 11.8, "stop": 9.2}
			],
			"validation": {"passed": True, "issues": []},
		}
		plan_md = f"# Plan for {market} {trade_date}\n\n- DEMO LONG entry 10.0, TP 11.8, Stop 9.2\n"
		plan = TradePlan(trade_date=trade_date, market=market, plan_json=plan_json, plan_md=plan_md)
		session.add(plan)
		session.commit()
		created["plans"] += 1

	return {"created": created}


def main() -> None:
	parser = argparse.ArgumentParser(description="Seed demo data for TopN and Plan.")
	parser.add_argument("--trade-date", dest="trade_date", required=False, default=datetime.now().date().isoformat())
	parser.add_argument("--market", dest="market", required=False, default="SSE")
	parser.add_argument("--n", dest="n", type=int, required=False, default=3)
	args = parser.parse_args()
	res = seed(args.trade_date, args.market, max(1, args.n))
	print(res)


if __name__ == "__main__":
	main() 