# preopen-news-driven-plan — Spec ⇄ Impl 映射（Iteration 2）

> 快照日期：2025-09-11（基于当前仓库状态）
> 范围：对照 `.kiro/specs/preopen-news-driven-plan/*` 与 `app/*` 现有实现，标注覆盖/偏差/缺口，并锚定 M1 交付项（已含查询与校验端点、SQLite 持久化、最小流水线）。

## 1) 外部 API（HTTP）

- 已实现
  - POST `/v1/pipeline/preopen/run`（接受任务、返回 `T-xx` 截止与 ISO 时间）
  - GET `/v1/pipeline/preopen/status`（返回内存任务状态）
  - GET `/v1/news/topn`（查询当日 Top-N）
  - GET `/v1/plan/latest`（查询当日计划）
  - POST `/v1/plan/validate`（计划结构与风控校验）
  - GET `/v1/health`

代码锚点：
```130:210:app/server.py
@app.post("/v1/pipeline/preopen/run", response_model=PreopenRunAccepted, status_code=202)
...
return PreopenRunAccepted(task_id=task_id, status="pending", deadlines=_jobs[task_id]["deadlines"])
```

```213:351:app/server.py
@app.get("/v1/pipeline/preopen/status", response_model=PreopenStatus)
...
@app.get("/v1/news/topn", response_model=TopNResponse)
...
@app.get("/v1/plan/latest", response_model=PlanLatestResponse)
...
@app.post("/v1/plan/validate", response_model=PlanValidateResponse)
...
@app.get("/v1/health")
```

契约模型：
```1:92:app/models.py
class TopNResponse(BaseModel): ...
class PlanLatestResponse(BaseModel): ...
class PlanValidateRequest(BaseModel): ...
class PlanValidateResponse(BaseModel): ...
```

行为与边界：
- `/v1/news/topn`：当存储未初始化或无数据返回 404；从 `TopCandidate` 读取、可选补充 `NormalizedNews` 推断 `symbol.code`，返回 evidence.events/sentiment。
- `/v1/plan/latest`：当无匹配返回 404；如 `plan_json.validation` 缺失则默认 `{passed: true, issues: []}`。
- `/v1/plan/validate`：检查必填、LONG/SHORT 价格顺序、风险回报 ≥ 1.5；失败返回 `passed=false` 与 issues 列表。

测试锚点：
```1:109:tests/test_api_m1.py
- 404 用例：topn/plan.latest
- 校验用例：plan.validate（缺字段）
- happy path：插入行后 topn 返回 200；插入 TradePlan 后 plan.latest 返回 200
```

## 2) 内部流水线（Ingestion → Normalize → Score → SelectTopN → Plan）

- 已实现：最小同步流水线，含规则化打分、多源聚合与去重、Top-N 选择、计划生成，并持久化。

代码锚点：
```1:147:app/pipeline/preopen.py
class PreOpenPipeline: ... def run(...):
  - 进度回调 on_progress（Scheduler/Ingestion/Normalize/Score/SelectTopN/Plan）
  - 从配置读取 sources 与 scoring.weights
  - 生成 top1 计划（json/md）并写入 TradePlan
```

组件：
```1:290:app/pipeline/components.py
- fetch_from_all_sources / fetch_from_config_source（RSS 优先，失败走离线 demo）
- normalize（标题→文本，长度质量分）
- score_items（规则标签、加权聚合）
- select_top_n（按源轮转的贪心多样性）
- generate_plan（基于 Top-1 最小计划）
```

## 3) 数据模型与存储（SQLite via SQLModel）

引导与会话：
```1:21:app/storage/db.py
init_db(); get_session()
```

表结构与选择器：
```1:94:app/storage/models.py
- RawNews / NormalizedNews / Score / TopCandidate / TradePlan
- TopCandidate.select_for(trade_date, market, limit)
- TradePlan.select_latest(trade_date, market)
```

端点与 ORM 交互：
```213:351:app/server.py
- /v1/news/topn：查询 TopCandidate，补充 NormalizedNews，构造 TopNItem
- /v1/plan/latest：查询 TradePlan 最新一条并补全 validation 缺省
```

## 4) 配置（config）

- `APP_CONFIG_PATH` 指向 YAML；权重在 `scoring.weights`，阈值 `scoring.score_threshold`，来源 `sources[]`。
- Uvicorn 入口：
```1:7:main.py
uvicorn.run("app.server:app", host=os.getenv("HOST","0.0.0.0"), port=int(os.getenv("PORT","8000")))
```

## 5) 时间与 T-xx

- 固定本地 09:30（SSE），计算 T-45/T-35/T-30；流水线与 run/status 均回传 ISO 截止时间。

## 6) 与 Spec 的偏差/假设

- 情感与事件识别为规则最小集；`/v1/news/topn` 的 `symbol.code` 采用实体或标题启发式，非强保证。
- 计划生成使用静态价位与置信度映射 top1，总体满足校验规则，非真实撮合/风控引擎。
- 观测为最小日志；度量指标与告警留待 M2。

## 7) 覆盖与缺口清单

- 覆盖：
  - API 与合约：TopN/PlanLatest/PlanValidate/Health 已达成；Run/Status 已有。
  - 存储：5 张核心表与查询选择器已达成。
  - 流水线：规则化最小能力与持久化已达成。
  - 测试：核心路径与 404/校验用例已覆盖。
- 缺口：
  - 实体识别/行业多样性/权重版本化更细粒度。
  - 真实交易日历与时区。
  - 结构化日志、指标、重试队列 `/v1/retry`（Spec 草拟，未实现）。

---

结论：M1 目标的查询接口、最小流水线与 SQLite 持久化均已对齐 Spec；后续迭代聚焦可观测性、计划质量与多样性、以及更真实的市场约束。 