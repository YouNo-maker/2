from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DeadlinesSpec(BaseModel):
    fetch_min_before_open: int = Field(default=45, ge=0)
    topn_min_before_open: int = Field(default=35, ge=0)
    plan_min_before_open: int = Field(default=30, ge=0)


class PreopenRunRequest(BaseModel):
    market: str
    trade_date: str
    deadlines: Optional[DeadlinesSpec] = None
    force_recompute: bool = False
    dedupe_key: Optional[str] = None
    async_run: bool = True


class DeadlineTimes(BaseModel):
    fetch: str
    topn: str
    plan: str


class PreopenRunAccepted(BaseModel):
    task_id: str
    status: str = "pending"
    deadlines: Dict[str, str]


class PreopenStatus(BaseModel):
    task_id: str
    status: str
    stage: Optional[str] = None
    started_at: Optional[str] = None
    percent: Optional[int] = None
    errors: List[str] = []
    metrics: Dict[str, Any] = {}


# ---- Top-N & Plan models (aligned to spec) ----
class SymbolRef(BaseModel):
    exchange: str
    code: str


class Evidence(BaseModel):
    news_ids: List[str] = []
    events: List[str] = []
    sentiment: Optional[Dict[str, Any]] = None


class TopNItem(BaseModel):
    symbol: SymbolRef
    aggregate_score: float
    scores: Dict[str, float]
    evidence: Evidence
    sectors: List[str] = []
    source_id: Optional[str] = None
    rank: Optional[int] = None
    group_key: Optional[str] = None


class TopNResponse(BaseModel):
    as_of: str
    market: str
    topn: List[TopNItem]
    weight_version: Optional[str] = None
    diversity: Optional[Dict[str, Any]] = None


class PlanPayload(BaseModel):
    trade_date: str
    market: str
    entries: List[Dict[str, Any]]
    meta: Optional[Dict[str, Any]] = None


class PlanLatestResponse(BaseModel):
    market: str
    trade_date: str
    plan_json: Dict[str, Any]
    plan_md: Optional[str] = None
    validation: Dict[str, Any]
    generated_at: str


class PlanValidateRequest(BaseModel):
    plan: Dict[str, Any]


class PlanValidateResponse(BaseModel):
    passed: bool
    issues: List[str] = []
    severity: Optional[str] = None


class PreopenRetryRequest(BaseModel):
    task_id: str
    async_run: bool = True


class PreopenCancelRequest(BaseModel):
    task_id: str
    force: bool = False


class PreopenCancelResponse(BaseModel):
    task_id: str
    previous_status: str
    new_status: str
    accepted: bool


class PreopenJobsResponse(BaseModel):
    jobs: List[PreopenStatus] 


class MetricsSnapshotResponse(BaseModel):
    runs: int
    last_market: Optional[str] = None
    last_trade_date: Optional[str] = None
    last_counts: Dict[str, Any] = {}
    last_dedupe_rate: Optional[float] = None
    last_timings_ms: Optional[Dict[str, Any]] = None
    last_ingestion_per_source: Optional[Dict[str, Any]] = None
    success: Optional[int] = 0
    failure: Optional[int] = 0
    latency_ms: Optional[Dict[str, int]] = None
    last_link_content_dedupe: Optional[Dict[str, float]] = None
    last_diversity: Optional[Dict[str, Any]] = None
    last_source_diversity: Optional[Dict[str, Any]] = None
    last_http_cache: Optional[Dict[str, Any]] = None


class AlertItem(BaseModel):
    key: str
    level: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    source_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class AlertsResponse(BaseModel):
    alerts: List[AlertItem]
    summary: Optional[Dict[str, Any]] = None

# ---- AI integration ----
class AIAskRequest(BaseModel):
    question: str = Field(min_length=1)
    market: Optional[str] = None
    trade_date: Optional[str] = Field(default=None)
    include_topn_context: bool = True
    max_tokens: Optional[int] = Field(default=None, ge=32, le=4096)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)


class AIAskResponse(BaseModel):
    answer: str
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


# Streaming chat models
class AIChatMessage(BaseModel):
    role: str
    content: str


class AIChatRequest(BaseModel):
    messages: List[AIChatMessage]
    market: Optional[str] = None
    trade_date: Optional[str] = None
    include_topn_context: bool = True
    max_tokens: Optional[int] = Field(default=None, ge=32, le=4096)
    temperature: Optional[float] = Field(default=None, ge=0, le=2) 