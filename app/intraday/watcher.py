from __future__ import annotations
from typing import Optional, Dict, Any, List
import threading
import time
import re
from datetime import datetime

from sqlmodel import select
from ..storage.db import get_session
from ..storage.models import NormalizedNews, IntradayEvent
from ..util_time import get_market_open_naive_local, get_market_close_naive_local
from ..config import get_config


_NEGATIVE_PATTERNS = [
    r"\bdown\b", r"\bfall\b", r"\bloss\b", r"\bwarn\w*\b",
    r"监管", r"处罚", r"罚款", r"预警", r"下跌", r"亏损",
]
_NEG_RE = re.compile("|".join(_NEGATIVE_PATTERNS), flags=re.IGNORECASE)


_state_lock = threading.Lock()
_watcher_thread: Optional[threading.Thread] = None
_stop_evt: Optional[threading.Event] = None
_state: Dict[str, Any] = {"running": False, "market": None, "trade_date": None, "interval_minutes": None, "last_tick_at": None, "last_seen_id": 0}


def _tick(market: str, trade_date: str, interval_minutes: int) -> None:
    global _state
    while _stop_evt and not _stop_evt.is_set():
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        try:
            with get_session() as session:
                last_id = int(_state.get("last_seen_id") or 0)
                stmt = select(NormalizedNews).order_by(NormalizedNews.id.desc()).limit(100)
                rows: List[NormalizedNews] = session.exec(stmt).all()
                new_rows = [r for r in rows if (r.id or 0) > last_id]
                triggered = 0
                for r in new_rows:
                    title = (r.title or "")
                    if not title:
                        continue
                    if _NEG_RE.search(title):
                        ev = IntradayEvent(
                            trade_date=trade_date,
                            market=market,
                            event_type="news_negative",
                            severity="warning",
                            title=r.title,
                            url=r.url,
                            message=f"Negative signal detected: {r.title}",
                        )
                        session.add(ev)
                        session.commit()
                        triggered += 1
                if rows:
                    _state["last_seen_id"] = max((r.id or 0) for r in rows)
        except Exception:
            pass
        with _state_lock:
            _state["last_tick_at"] = now_iso
        # Sleep until next poll or stop
        if _stop_evt and _stop_evt.wait(timeout=max(5.0, 60.0 * float(interval_minutes))):
            break


def start_watcher(market: str, trade_date: str, interval_minutes: int) -> None:
    global _watcher_thread, _stop_evt
    with _state_lock:
        # If same market/date running, no-op
        if _state.get("running") and _state.get("market") == market and _state.get("trade_date") == trade_date:
            return
        # Stop existing if any
        if _stop_evt is not None:
            try:
                _stop_evt.set()
            except Exception:
                pass
        _stop_evt = threading.Event()
        _state.update({
            "running": True,
            "market": market,
            "trade_date": trade_date,
            "interval_minutes": int(interval_minutes),
            "last_tick_at": None,
        })
        _watcher_thread = threading.Thread(target=_tick, args=(market, trade_date, int(interval_minutes)), daemon=True)
        _watcher_thread.start()


def stop_watcher() -> None:
    global _watcher_thread, _stop_evt
    with _state_lock:
        if _stop_evt is not None:
            try:
                _stop_evt.set()
            except Exception:
                pass
        _stop_evt = None
        _watcher_thread = None
        _state.update({"running": False})


def watcher_status(limit_events: int = 20) -> Dict[str, Any]:
    out = {}
    with _state_lock:
        out = dict(_state)
    # Append recent events from DB
    try:
        with get_session() as session:
            stmt = select(IntradayEvent).order_by(IntradayEvent.id.desc()).limit(int(limit_events))
            rows: List[IntradayEvent] = session.exec(stmt).all()
            out["recent_events"] = [
                {
                    "id": r.id,
                    "trade_date": r.trade_date,
                    "market": r.market,
                    "event_type": r.event_type,
                    "severity": r.severity,
                    "title": r.title,
                    "url": r.url,
                    "message": r.message,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
    except Exception:
        out["recent_events"] = []
    return out


def ensure_running_if_trading(market: str, now_local: datetime) -> None:
    cfg = get_config() or {}
    intr = cfg.get("intraday") or {}
    if not bool(intr.get("watcher_enabled", False)):
        stop_watcher()
        return
    try:
        interval = int((intr.get("poll_interval_minutes") or 5))
    except Exception:
        interval = 5
    date_str = f"{now_local.year:04d}-{now_local.month:02d}-{now_local.day:02d}"
    open_t = get_market_open_naive_local(market, date_str)
    close_t = get_market_close_naive_local(market, date_str)
    if open_t <= now_local < close_t:
        start_watcher(market, date_str, interval)
    else:
        stop_watcher() 