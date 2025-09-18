# preopen-news-driven-plan — Spec ⇄ Impl 映射（Iteration 1）

> 快照日期：2025-09-10（基于当前仓库状态）
> 范围：对照 `.kiro/specs/preopen-news-driven-plan/*` 与 `app/*` 现有实现，标注覆盖/偏差/缺口，并锚定 M1 交付项。

## 1) 外部 API（HTTP）

- 已实现
  - POST `/v1/pipeline/preopen/run`（接受任务、返回 `T-xx` 截止与 ISO 时间）
  - GET `/v1/pipeline/preopen/status`（返回内存任务状态）
  - GET `/v1/health`

代码锚点：
```15:29:app/server.py
@app.post("/v1/pipeline/preopen/run", response_model=PreopenRunAccepted, status_code=202)
def run_preopen_pipeline(req: PreopenRunRequest) -> Any:
    cfg = get_config()
    deadlines = req.deadlines or DeadlinesSpec(
        fetch_min_before_open=cfg["preopen"]["first_fetch_minutes_before_open"] - 15,
        topn_min_before_open=cfg["preopen"]["topn_output_minutes_before_open"],
        plan_min_before_open=cfg["preopen"]["plan_output_minutes_before_open"],
    )
    task_id = f"preopen_{req.market}_{req.trade_date}"
```

```48:61:app/server.py
@app.get("/v1/pipeline/preopen/status", response_model=PreopenStatus)
def preopen_status(task_id: str) -> Any:
    job = _jobs.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="task not found")
    return PreopenStatus(
        task_id=task_id,
        status=job.get("status", "running"),
        stage=job.get("stage"),
        started_at=job.get("started_at"),
        percent=job.get("percent", 10),
        errors=job.get("errors", []),
        metrics=job.get("metrics", {}),
    )
```

- 计划中（M1 必交）
  - GET `/v1/news/topn`（查询当日 Top-N）
  - GET `/v1/plan/latest`（查询当日计划）
  - POST `/v1/plan/validate`（计划结构校验）

偏差与说明：
- `run` 端点默认将 `first_fetch_minutes_before_open` 减 15 作为 `T-45`（与 Spec 的 T-45 对齐）。
- `status` 仅返回内存占位字段，`percent`/`metrics` 非真实进度。

## 2) 内部流水线（Scheduler → Ingestion → Normalize → … → Plan）

- 已实现（占位/元信息）
  - `PreOpenPipeline.run`：仅计算截止时刻与 ISO 字段，返回 `task_id/started_at/deadlines`

代码锚点：
```8:31:app/pipeline/preopen.py
class PreOpenPipeline:
    @staticmethod
    def run(market: str, trade_date: str, deadlines: DeadlinesSpec) -> Dict[str, Any]:
        open_time = get_market_open_naive_local(market, trade_date)
        fetch_t, topn_t, plan_t = compute_deadlines(open_time,
            deadlines.fetch_min_before_open,
            deadlines.topn_min_before_open,
            deadlines.plan_min_before_open,
        )
        result = {
            "deadlines": {
                "fetch": "T-45" if deadlines.fetch_min_before_open == 45 else f"T-{deadlines.fetch_min_before_open}",
                "topn": "T-35" if deadlines.topn_min_before_open == 35 else f"T-{deadlines.topn_min_before_open}",
                "plan": "T-30" if deadlines.plan_min_before_open == 30 else f"T-{deadlines.plan_min_before_open}",
                "fetch_at": fetch_t.isoformat(),
                "topn_at": topn_t.isoformat(),
                "plan_at": plan_t.isoformat(),
            },
        }
        return result
```

- 未实现（M1 需补齐最小能力）
  - `NewsFetcher/Normalizer/EntityResolver/Tagger/Scorer/Planner`（规则化最小版）
  - `WebEnricher`（延后至 M2）
  - `IntradayWatcher`（延后至 M2）

## 3) 数据模型与存储

- 现状：无数据库；内存 `jobs`/`dedupe_index`。
- M1 目标：引入 SQLite + ORM，落库 `raw_news/normalized_news/scores/top_candidates/trade_plans`。

## 4) 配置（config）

- 默认配置与已覆盖字段：
```27:43:app/config.py
base: Dict[str, Any] = {
    "market": "SSE",
    "preopen": {
        "first_fetch_minutes_before_open": 60,
        "topn_output_minutes_before_open": 35,
        "plan_output_minutes_before_open": 30,
    },
    "intraday": {"poll_interval_minutes": 5},
    "alerts": {"error_rate_threshold": 0.01},
    "llm": {"provider": "deepseek", "temperature": 0.3, "timeout_ms": 12000, "cache_ttl_minutes": 1440},
}
```
- Spec 差异：`scoring.weights`、`sources[]`、`llm.proxy`、`scoring.diversity` 等尚未落地；M1 需扩展。

## 5) 时间与交易日（T-xx 计算）

- 现状：SSE 09:30 本地时间（无时区/日历），计算 T-xx。

代码锚点：
```6:12:app/util_time.py
def get_market_open_naive_local(market: str, trade_date: str) -> datetime:
    # Minimal implementation: support SSE 09:30 local
    year, month, day = map(int, trade_date.split("-"))
    return datetime(year, month, day, 9, 30, 0)
```

```14:18:app/util_time.py
def compute_deadlines(open_time: datetime, fetch_min: int, topn_min: int, plan_min: int) -> Tuple[datetime, datetime, datetime]:
    fetch_time = open_time - timedelta(minutes=fetch_min)
    topn_time = open_time - timedelta(minutes=topn_min)
    plan_time = open_time - timedelta(minutes=plan_min)
    return fetch_time, topn_time, plan_time
```

- M1 决策：保持“本地无时区 + 固定 09:30”，真实交易日历留待后续。

## 6) 合约模型（Pydantic）

- 已有：`PreopenRunRequest/DeadlinesSpec/PreopenRunAccepted/PreopenStatus`

代码锚点：
```12:18:app/models.py
class PreopenRunRequest(BaseModel):
    market: str
    trade_date: str
    deadlines: Optional[DeadlinesSpec] = None
    force_recompute: bool = False
    dedupe_key: Optional[str] = None
```

- M1 待补：
  - `TopNResponse`、`PlanLatestResponse`、`PlanValidateRequest/Response`
  - ORM/DAO 模型（SQLite）

## 7) 测试覆盖

- 已有：
  - 健康检查、`/v1/pipeline/preopen/run` 接受与 T-xx/ISO 字段、`/v1/pipeline/preopen/status`、幂等去重

代码锚点：
```16:38:tests/test_preopen.py
def test_preopen_run_accepts_and_returns_deadlines():
    resp = client.post("/v1/pipeline/preopen/run", json=body)
    assert data["deadlines"]["fetch"] == "T-45"
    assert "fetch_at" in deadlines and deadlines["fetch_at"].startswith("2025-09-10T")
```

- M1 需增：
  - `/v1/news/topn` 正常/404、`/v1/plan/latest` 正常/404、`/v1/plan/validate` 校验用例
  - 端到端（使用本地 fixtures 源）

## 8) 与 Spec 的差异/假设

- 本次 Iteration 固定“同步流水线 + 单体 + SQLite”，不引入队列/调度器/LLM/代理。
- `Top-N` 固定 N=10（可由 Query 覆盖），不实现行业多样性去偏；M2 规划加入。
- Planner 走规则化最小集，生成 `plan.json/md` 与基础校验。

## 9) M1 交付映射到 `tasks.md`

- API：新增 3 个端点（TopN/Plan/Validate）→ 参见 `tasks.md` 第 1 节
- 存储：建 5 张核心表 → 参见 `tasks.md` 第 2 节
- 流水线：规则化最小能力 → 参见 `tasks.md` 第 3 节
- 配置扩展/可观测/测试/文档 → 参见 `tasks.md` 第 4–7 节

## 10) 风险与后续（对 M2 的前置）

- 交易所日历/时区、行业去偏策略、联网增强与 LLM 接入、观测指标标准化与告警、盘中监控。

---

结论：当前实现满足 Spec 的任务入口与时序元信息；M1 需补齐最小流水线、存储与查询接口，确保“离线可用、可查询、可观测”。后续迭代聚焦去偏、LLM 与盘中能力。 