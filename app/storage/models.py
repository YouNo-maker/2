from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, select


class RawNews(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None
    hash: Optional[str] = None
    dedup_key: Optional[str] = None
    lang: Optional[str] = None
    raw: Optional[str] = None


class NormalizedNews(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    raw_id: Optional[int] = Field(default=None, foreign_key="rawnews.id")
    source_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    published_at: Optional[str] = None
    quality: Optional[float] = None
    entities_json: Optional[str] = None
    # New: hashes for normalized content and canonical link
    content_hash: Optional[str] = None
    link_canon_hash: Optional[str] = None


class Score(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    normalized_id: int = Field(foreign_key="normalizednews.id")
    relevance: Optional[float] = None
    sentiment_strength: Optional[float] = None
    event_weight: Optional[float] = None
    recency: Optional[float] = None
    source_trust: Optional[float] = None
    total: float = 0.0
    version: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))


class TopCandidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_date: str
    market: str
    normalized_id: int = Field(foreign_key="normalizednews.id")
    rank: int
    total_score: float
    title: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[str] = None
    components_json: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    @staticmethod
    def select_for(trade_date: str, market: str, limit: int):
        stmt = select(TopCandidate).where(
            TopCandidate.trade_date == trade_date,
            TopCandidate.market == market,
        ).order_by(TopCandidate.rank).limit(limit)
        return stmt

    @property
    def components(self) -> Optional[Dict[str, float]]:
        import json
        if not self.components_json:
            return None
        try:
            return json.loads(self.components_json)
        except Exception:
            return None


from sqlalchemy import Column
from sqlalchemy.types import JSON

class TradePlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_date: str
    market: str
    plan_json: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    plan_md: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    @staticmethod
    def select_latest(trade_date: str, market: str):
        stmt = select(TradePlan).where(
            TradePlan.trade_date == trade_date,
            TradePlan.market == market,
        ).order_by(TradePlan.created_at.desc()).limit(1)
        return stmt


class IntradayEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_date: str
    market: str
    event_type: str
    severity: str
    title: Optional[str] = None
    url: Optional[str] = None
    message: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")) 