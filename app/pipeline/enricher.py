from __future__ import annotations
from typing import Any, Tuple, Dict
from datetime import datetime, timezone


def enrich_plan(plan_json: Dict[str, Any], plan_md: str, cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
	"""Optionally enrich the plan based on config.
	cfg.enrichment.enabled: bool to toggle enrichment.
	This minimal enricher just adds a metadata note and timestamp; no external calls.
	"""
	enabled = False
	try:
		enabled = bool(((cfg.get("enrichment") or {}).get("enabled", False)))
	except Exception:
		enabled = False
	if not enabled:
		return plan_json, plan_md
	stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
	meta = {
		"enriched_at": stamp,
		"notes": "minimal enrichment enabled",
	}
	# attach to JSON
	try:
		plan_json = dict(plan_json)
		plan_json["enrichment"] = meta
	except Exception:
		pass
	# append to markdown
	try:
		plan_md = plan_md + f"\n- Enrichment: minimal at {stamp}\n"
	except Exception:
		pass
	return plan_json, plan_md 