from __future__ import annotations
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Any


def get_market_open_naive_local(market: str, trade_date: str) -> datetime:
    # Market-aware implementation using per-market defaults; expects trade_date in YYYY-MM-DD
    # No timezone handling to keep dependencies minimal
    year, month, day = map(int, trade_date.split("-"))
    try:
        info = _get_market_defaults(market)
        open_h, open_m = info["open"]
    except Exception:
        open_h, open_m = 9, 30
    return datetime(year, month, day, open_h, open_m, 0)


def compute_deadlines(open_time: datetime, fetch_min: int, topn_min: int, plan_min: int) -> Tuple[datetime, datetime, datetime]:
    fetch_time = open_time - timedelta(minutes=fetch_min)
    topn_time = open_time - timedelta(minutes=topn_min)
    plan_time = open_time - timedelta(minutes=plan_min)
    return fetch_time, topn_time, plan_time


_MARKET_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # China A-share (Shanghai/Shenzhen): simplified session (ignore lunch break)
    "SSE": {"open": (9, 30), "close": (15, 0)},
    "SZSE": {"open": (9, 30), "close": (15, 0)},
    # US markets
    "NYSE": {"open": (9, 30), "close": (16, 0)},
    "NASDAQ": {"open": (9, 30), "close": (16, 0)},
    # Hong Kong
    "HKEX": {"open": (9, 30), "close": (16, 0)},
}


def _get_market_defaults(market: str) -> Dict[str, Any]:
    return _MARKET_DEFAULTS.get((market or "SSE").upper(), _MARKET_DEFAULTS["SSE"])


def get_market_close_naive_local(market: str, trade_date: str) -> datetime:
    """Return local-close datetime (naive) for the given market and trade date (YYYY-MM-DD).
    Simplified single-session close; no timezone handling.
    """
    year, month, day = map(int, trade_date.split("-"))
    info = _get_market_defaults(market)
    close_h, close_m = info["close"]
    return datetime(year, month, day, close_h, close_m, 0)


def is_trading_day(market: str, dt_local: datetime) -> bool:
    """Return True if dt_local's date is a trading day for the given market.
    Minimal behavior: Monday–Friday, minus optional holidays in config.market_calendar.
    """
    try:
        if dt_local.weekday() >= 5:
            return False
    except Exception:
        return True
    # Optional holiday support via config
    try:
        from .config import get_config
        cfg = get_config() or {}
        cal = cfg.get("market_calendar") or {}
        mkey = (market or "SSE").upper()
        holidays = None
        if isinstance(cal.get(mkey), dict):
            holidays = cal.get(mkey, {}).get("holidays")
        if holidays is None:
            holidays = cal.get("holidays")
        if isinstance(holidays, list):
            iso = f"{dt_local.year:04d}-{dt_local.month:02d}-{dt_local.day:02d}"
            return iso not in set(str(x) for x in holidays)
    except Exception:
        pass
    return True


def next_trading_day(market: str, dt_local: datetime) -> datetime:
    """Return the next trading-day date (keeping naive datetime, time component unchanged)."""
    nd = dt_local + timedelta(days=1)
    # Iterate until a trading day is found
    while not is_trading_day(market, nd):
        nd += timedelta(days=1)
    return nd


def next_open_local(market: str, from_dt_local: datetime) -> datetime:
    """Return the next open datetime (naive local) on or after from_dt_local.
    If the current day is a trading day and from_dt_local is before today's open, returns today's open.
    Otherwise, returns the next trading day's open.
    """
    date_str = f"{from_dt_local.year:04d}-{from_dt_local.month:02d}-{from_dt_local.day:02d}"
    today_open = get_market_open_naive_local(market, date_str)
    if is_trading_day(market, from_dt_local) and from_dt_local < today_open:
        return today_open
    nd = next_trading_day(market, from_dt_local)
    nd_str = f"{nd.year:04d}-{nd.month:02d}-{nd.day:02d}"
    return get_market_open_naive_local(market, nd_str)


def next_close_local(market: str, from_dt_local: datetime) -> datetime:
    """Return the next close datetime (naive local) on or after from_dt_local.
    If before today's close, returns today's close; else next trading day's close.
    """
    date_str = f"{from_dt_local.year:04d}-{from_dt_local.month:02d}-{from_dt_local.day:02d}"
    today_close = get_market_close_naive_local(market, date_str)
    if is_trading_day(market, from_dt_local) and from_dt_local < today_close:
        return today_close
    nd = next_trading_day(market, from_dt_local)
    nd_str = f"{nd.year:04d}-{nd.month:02d}-{nd.day:02d}"
    return get_market_close_naive_local(market, nd_str) 