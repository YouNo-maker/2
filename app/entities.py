from __future__ import annotations
from typing import Any, Dict, List, Set
from pathlib import Path
import yaml
import re
import threading

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] | None = None


def _config_dir() -> Path:
	from .config import Path as _P  # type: ignore[attr-defined]
	# Fallback: compute relative to project root
	try:
		return _P(__file__).resolve().parents[1] / "config"  # type: ignore
	except Exception:
		return Path(__file__).resolve().parents[1] / "config"


def load_entity_dict() -> Dict[str, Any]:
	global _CACHE
	with _CACHE_LOCK:
		if _CACHE is not None:
			return _CACHE
		path = _config_dir() / "entities.yaml"
		if not path.exists():
			_CACHE = {"symbols": []}
			return _CACHE
		with path.open("r", encoding="utf-8") as f:
			data = yaml.safe_load(f) or {}
		if not isinstance(data, dict):
			data = {"symbols": []}
		# normalize structure
		syms = data.get("symbols") or []
		norm_syms: List[Dict[str, Any]] = []
		for s in syms:
			if not isinstance(s, dict):
				continue
			code = str(s.get("code") or "").strip()
			if not code:
				continue
			aliases = s.get("aliases") or []
			if isinstance(aliases, str):
				aliases = [aliases]
			norm_syms.append({
				"exchange": s.get("exchange") or "",
				"code": code,
				"name": s.get("name") or "",
				"aliases": [a for a in aliases if isinstance(a, str) and a.strip()],
				"sectors": [x for x in (s.get("sectors") or []) if isinstance(x, str)],
			})
		_CACHE = {"symbols": norm_syms}
		return _CACHE


def resolve_entities_from_text(text: str) -> Dict[str, List[str]]:
	text_l = (text or "").lower()
	cfg = load_entity_dict()
	out_symbols: Set[str] = set()
	out_sectors: Set[str] = set()
	for s in cfg.get("symbols", []):
		aliases: List[str] = s.get("aliases", [])
		for alias in aliases:
			alias_l = alias.lower()
			# word boundary match for latin, substring for CJK
			if re.search(r"[a-zA-Z0-9]", alias_l):
				pattern = r"\b%s\b" % re.escape(alias_l)
				if re.search(pattern, text_l):
					out_symbols.add(str(s.get("code")))
					for sec in s.get("sectors", []) or []:
						out_sectors.add(sec)
			else:
				if alias_l in text_l:
					out_symbols.add(str(s.get("code")))
					for sec in s.get("sectors", []) or []:
						out_sectors.add(sec)
	return {"symbols": sorted(out_symbols), "sectors": sorted(out_sectors)} 