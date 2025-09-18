from __future__ import annotations
from app.pipeline.components import NormalizedItem, ScoredItem, score_items, select_top_n


def _mk_norm(title: str, source: str, published_at: str = "2025-09-10T07:30:00Z", ents=None):
	if ents is None:
		ents = {"symbols": [], "sectors": []}
	return NormalizedItem(source_id=source, url=None, title=title, text=title, published_at=published_at, quality=0.6, entities=ents)


def test_entity_boost_increases_relevance():
	n1 = _mk_norm("News with no entities", "rss_a", ents={"symbols": [], "sectors": []})
	n2 = _mk_norm("News with entities", "rss_a", ents={"symbols": ["600519"], "sectors": ["Beverages"]})
	sc = score_items([n1, n2], {"relevance": 1.0, "sentiment_strength": 0.0, "event_weight": 0.0, "recency": 0.0, "source_trust": 0.0}, as_of_iso="2025-09-10T08:00:00Z")
	s1 = [s for s in sc if s.normalized.title == n1.title][0]
	s2 = [s for s in sc if s.normalized.title == n2.title][0]
	assert s2.components["relevance"] >= s1.components["relevance"] + 0.099


def test_sector_diversity_cap():
	# 5 candidates from same sector and 5 from another, n=6, cap=50% -> each sector max 3
	cands = []
	for i in range(5):
		cands.append(ScoredItem(normalized=_mk_norm(f"A{i}", "rss_a", ents={"symbols": [f"A{i}"], "sectors": ["S1"]}), components={"relevance": 0.9}, total=0.9 - i * 0.01))
	for i in range(5):
		cands.append(ScoredItem(normalized=_mk_norm(f"B{i}", "rss_b", ents={"symbols": [f"B{i}"], "sectors": ["S2"]}), components={"relevance": 0.9}, total=0.85 - i * 0.01))
	selected = select_top_n(cands, n=6, threshold=0.0, sector_cap_pct=50)
	s1 = [s for s in selected if s.normalized.entities.get("sectors")[0] == "S1"]
	s2 = [s for s in selected if s.normalized.entities.get("sectors")[0] == "S2"]
	assert len(s1) <= 3 and len(s2) <= 3
	assert len(selected) == 6 