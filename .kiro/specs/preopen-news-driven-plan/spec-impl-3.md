# preopen-news-driven-plan — Spec ⇄ Impl 映射（Iteration 3）

> 快照日期：2025-09-12（基于当前仓库状态）
> 范围：对照 `.kiro/specs/preopen-news-driven-plan/*` 与 `app/*` 现有实现，标注覆盖/偏差/缺口；在 Iteration 2 的基础上更新新增端点、最小流水线持久化与调度能力。

## 1) 外部 API（HTTP）

- 已实现
  - POST `/v1/pipeline/preopen/run`（接受任务、返回 `T-xx` 截止与 ISO 时间）
  - GET `/v1/pipeline/preopen/status`（查询任务状态）
  - POST `/v1/pipeline/preopen/retry`（将失败项放入重试队列/触发重跑占位）
  - GET `/v1/pipeline/preopen/jobs`（列出当日作业）
  - GET `/v1/pipeline/preopen/job`（按 `task_id` 查询作业）
  - POST `/v1/pipeline/preopen/cancel`（取消作业）
  - GET `/v1/news/topn`（查询当日 Top-N）
  - GET `/v1/plan/latest`（查询当日计划）
  - POST `/v1/plan/validate`（计划结构与风控校验）
  - GET `/v1/health`
  - 调度控制：GET `/v1/scheduler/status`、POST `/v1/scheduler/start|stop|restart`

代码锚点（节选）：
```271:772:app/server.py
@app.post("/v1/pipeline/preopen/run", ...)
@app.get("/v1/pipeline/preopen/status", ...)
@app.post("/v1/pipeline/preopen/retry", ...)
@app.get("/v1/pipeline/preopen/jobs", ...)
@app.get("/v1/pipeline/preopen/job", ...)
@app.post("/v1/pipeline/preopen/cancel", ...)
@app.get("/v1/news/topn", ...)
@app.get("/v1/plan/latest", ...)
@app.post("/v1/plan/validate", ...)
@app.get("/v1/health")
@app.get("/v1/scheduler/status")
@app.post("/v1/scheduler/start")
@app.post("/v1/scheduler/stop")
@app.post("/v1/scheduler/restart")
```

契约模型（已对齐）：
```1:118:app/models.py
class TopNResponse(BaseModel): ...
class PlanLatestResponse(BaseModel): ...
class PlanValidateRequest(BaseModel): ...
class PlanValidateResponse(BaseModel): ...
class PreopenRunRequest(BaseModel): ...
class PreopenRunAccepted(BaseModel): ...
class PreopenStatus(BaseModel): ...
class PreopenJobsResponse(BaseModel): ...
class PreopenCancelRequest/Response(BaseModel): ...
```

行为与边界（与规范对照）：
- `/v1/news/topn`：从 `TopCandidate` 读取，必要时结合 `NormalizedNews` 构造项；无数据时返回 404（符合“无候选达阈值时需有原因”的精神，原因目前以 HTTP 语义呈现）。
- `/v1/plan/latest`：返回最新 `TradePlan`；若 `validation` 缺省则补为 `{passed: true, issues: []}`。
- `/v1/plan/validate`：校验必填与价格一致性、最小 R:R 要求（见实现）；失败返回 `passed=false` 与 issues。
- `/v1/pipeline/preopen/retry`：提供占位式重试/重跑入口（规范中的“重试队列”雏形）。
- 调度控制端点提供最小可控运维面。

## 2) 内部流水线（Ingestion → Normalize → Score → SelectTopN → Plan）

- 已实现：最小同步流水线，含多源聚合与基础去重、解析与质量分、规则化标签与加权打分、Top-N 选择（含分组上限的多样性约束）、计划生成，并将各阶段结果持久化。

代码锚点：
```1:183:app/pipeline/preopen.py
class PreOpenPipeline: ... def run(...):
  - 进度回调 on_progress（Scheduler/Ingestion/Normalize/Score/SelectTopN/Plan）
  - 从配置读取 sources/scoring.weights
  - 写入 RawNews/NormalizedNews/Score/TopCandidate/TradePlan
```

组件：
```1:385:app/pipeline/components.py
- fetch_from_all_sources / fetch_from_config_source：RSS 优先，失败走离线 demo；支持 retries 与 qps（最小速率限制）；去重使用 make_dedup_key（规范化 URL，标题回退）
- normalize：HTML 去噪（脚本/样式剥离）、语言启发、质量分
- score_items：规则标签（事件/情绪启发）+ 加权聚合
- select_top_n：按 sector/source 分组轮转 + 组配额（sector_cap_pct）
- generate_plan：基于 Top-1 生成最小可执行计划（JSON+Markdown 摘要）
```

## 3) 数据模型与存储（SQLite via SQLModel）

引导与会话：
```1:45:app/storage/db.py
init_db(); get_session()
```

表结构与选择器：
```1:94:app/storage/models.py
- RawNews / NormalizedNews / Score / TopCandidate / TradePlan
- TopCandidate.select_for(trade_date, market, limit)
- TradePlan.select_latest(trade_date, market)
```

持久化要点：
- `PreOpenPipeline.run` 在写入 `RawNews` 时计算并保存 `dedup_key`（规范化 URL 优先，标题降级）、`hash`（基于 `title|url` 的 SHA-256 简易内容指纹）与 `lang`，并以 `(source_id, dedup_key)` 做软去重。

## 4) 调度器（Scheduler）

- 已实现：
  - 后台线程定时器，依据 `market` 与 `preopen.first_fetch_minutes_before_open` 在开盘前触发流水线（默认为 T-60）。
  - 幂等去重：`_dedupe_index` 避免同一交易日重复触发。
  - 运行状态：`/v1/scheduler/status` 与 start/stop/restart 控制。
- 偏差/缺口：
  - 交易日历为“工作日=交易日”的近似，未接入真实交易所日历与时区。
  - 未实现“连续失败熔断与告警挂钩”。

代码锚点（节选）：
```108:199:app/server.py
_start_scheduler_if_enabled(); _stop_scheduler(); _scheduler_state; _dedupe_index
```

## 5) 采集（Ingestion）与去重/条件请求

- 现状：
  - RSS 适配器支持 `retries`、`qps`、`timeout`；解析 `pubDate`，输出 ISO 时间；支持 ETag/Last-Modified 条件请求，并将条件请求缓存持久化到 JSON 文件（默认 `data/http_cache.json`，可通过环境变量 `APP_CACHE_PATH` 覆盖）。`304 Not Modified` 视为无新增。
  - 多源聚合使用规范化 URL（去除 UTM 等 tracking 参数、统一大小写与端口）+ 标题回退构成 `dedup_key` 去重；提供离线 demo 回退。
  - 入库持久化 `RawNews.hash`、`RawNews.dedup_key`、`RawNews.lang`，并以 `(source_id, dedup_key)` 软去重避免重复写入。
  - 指标 `dedupe_rate` 基于去重键计算，反映规范化后真实去重效果。
- 缺口（对照规范 R1/R2）：
  - 非 RSS 源尚未接入条件请求；多进程/多实例场景下的条件请求缓存一致性策略未定义。
  - 内容级哈希目前基于元数据（`title|url`）的简易 SHA-256，尚未对正文抓取后计算 `content_hash`；未建立哈希版本与回溯策略。
  - 备用源降级/熔断策略与完整错误上下文记录仍未实现。
  - 规范化策略与去重键的版本化标注与可观测性（命中率、冲突率）待补充。

代码锚点：
```1:200:app/sources/rss.py
fetch_rss(...): 条件请求（ETag/If-Modified-Since）、304 处理与 JSON 持久化缓存（APP_CACHE_PATH/data/http_cache.json）
1:385:app/pipeline/components.py
canonicalize_url(), make_dedup_key(), fetch_from_all_sources()
1:300:app/pipeline/preopen.py
PreOpenPipeline.run(): RawNews.hash/dedup_key/lang 持久化与去重、dedupe_rate 指标
```

## 6) 可观测性与健康

- 已有：
  - 运行快照指标聚合：`app.metrics.record_run/snapshot`；`/v1/health` 健康探针；`/v1/metrics` 指标快照端点（返回最近一次运行关键统计）。
  - 采集侧 `dedupe_rate` 采用规范化后的去重键统计，更贴近实际去重强度；`metrics.runs` 计数在每次 `record_run` 时自增。
- 缺口：
  - 结构化日志标准化、关键告警规则（抓取成功率<99%、连续失败熔断、LLM 超时/配额）尚未实现。

代码锚点：
```1:34:app/metrics.py
record_run(...); snapshot()
```

## 7) 与 Spec 的偏差/假设（仍然成立或新识别）

- 实体/事件/情绪：当前以规则/启发为主；`app/entities.py` 基于别名词典做符号与行业抽取，LLM 消歧与缓存留待后续。
- 计划生成：使用静态价位与置信度映射 Top-1，满足基本校验，非真实风控引擎。
- 交易所日历与时区：仍为近似；真实日历接入列入后续。
- 重试队列：提供 `/v1/pipeline/preopen/retry` 占位，未实现持久化队列与回退链路。

## 8) 任务映射到 `tasks.md`

- 可标记为已覆盖（或已具备 M1 最小能力）：
  - Normalize、Scorer、Planner、Persistence（已在 `tasks.md` 勾选）
  - Top-N/Plan/Validate/Health/Run/Status/Retry/Scheduler 控制端点（新增覆盖）
  - Ingestion：RSS 条件请求（ETag/Last-Modified，持久化缓存）、URL 规范化与 `dedup_key`、基于去重键的指标与入库软去重
- 建议保持未勾选并在 M2/M3 实施：
  - Scheduler（需引入真实交易日历、熔断与告警）
  - Ingestion（非 RSS 源条件请求、正文级 `content_hash`、备用源降级/熔断、错误上下文/可观测性增强、多实例缓存一致性）
  - Tagger/EntityResolver 的 LLM 回退与缓存、行业多样性更完善、权重版本化与历史校准
  - 可观测性（/v1/metrics、结构化日志与告警规则）与 IntradayWatcher

## 4) 可观测与指标
- 已实现：`/v1/metrics`、`/v1/metrics/per-source`、`/v1/alerts`
- 新增：LLM 指标与缓存命中（`metrics.llm`），每次运行记录多样性分布（pre/post 与 `sector_cap_pct`）

代码锚点：
```938:1007:app/server.py
@app.get("/v1/metrics", ...)
@app.get("/v1/metrics/per-source", ...)
@app.get("/v1/alerts")
```
```1:160:app/metrics.py
record_llm_call(...)
snapshot() -> { ..., "llm": {calls, success, failure, cache_hits, latency_ms, cache}, ... }
```

## 5) 组件扩展
- Tagger：`app/tagger.py`（LLM 优先、规则回退、`content_hash+prompt_version` 缓存）
- LLM 缓存：`app/llm_cache.py`（TTL，线程安全）
- Enricher：`app/enricher.py`（占位，可由 `planner.enricher_enabled` 控制）
- Scorer 集成：`score_items` 可选择调用 Tagger（配置 `llm.tagger_enabled`）
- Pipeline 记录 diversity 前后分布，并在生成计划后调用 Enricher（占位）

配置：
```1:40:config/config.yaml
llm:
  tagger_enabled: false
  prompt_version: v1
planner:
  enricher_enabled: false
```

---

结论：在 Iteration 2 的基础上，当前实现进一步完善了调度控制与重试入口，并在采集层引入了条件请求与基于规范化 URL 的去重，最小流水线端到端与 SQLite 持久化已稳定；与规范的主要差距集中在条件请求缓存持久化、正文级去重与回溯、真实交易日历、以及可观测/告警与 LLM 能力与盘中监控，这些将作为 M2/M3 的优先项推进。 