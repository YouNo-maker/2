# 开盘前新闻驱动的操盘计划（Pre-Open News Driven Plan — Steering）

## 目标与价值
- 在开盘前 T-60 → T-30 时间窗内，自动汇聚多源新闻→解析→实体/事件/情绪→打分与去偏→输出 Top-N，并为 Top-1 生成可执行操盘计划（JSON+Markdown）。
- 提升开盘前决策效率与胜率，保障稳定性、观测与合规成本控制。

## 当前状态
- **规格名**: `preopen-news-driven-plan`
- **阶段**: implemented
- **审批**: requirements/design/tasks 均已生成且已批准
- **最近更新**: 2025-09-17T00:00:00Z
- **规范目录**: `.kiro/specs/preopen-news-driven-plan/`

## 关键时点（SLA）
- T-45 完成首次抓取
- T-35 输出 Top-N（默认 5）
- T-30 生成 `plan.json` 与 `plan.md`（含校验）

## 核心接口（HTTP）
- `POST /v1/pipeline/preopen/run`（已有，返回 T-xx 与 ISO 截止）
- `GET /v1/pipeline/preopen/status`（已有，内存状态占位）
- `GET /v1/news/topn`（已有）
- `GET /v1/plan/latest`（已有）
- `POST /v1/plan/validate`（已有）
- `POST /v1/ai/ask`（已有）
- `POST /v1/ai/chat`（流式，已联通）
- `GET /v1/metrics`（已有）、`GET /v1/alerts`（已有）

## 实施现状与差异
- 已有：任务入口与时序元信息（`PreOpenPipeline.run`）、T-xx 计算与基本配置；查询接口 TopN/Plan/Validate；持久化（SQLite + SQLModel）落库；Pydantic 合约模型。
- 延后到 M2：`WebEnricher`、`IntradayWatcher`、行业去偏、LLM 缓存与回退/成本阈值告警、REST 源条件请求与降级、观测指标完善

## 验收要点（摘录）
- 抓取：并发/速率限制/退避重试/条件请求与去重；T-45 完成首次抓取
- 实体/标注：证券映射含置信度与证据；<0.70 入复核；LLM 失败回退规则化
- 打分/选择：权重版本化；行业多样性去偏；无候选达阈值返回“无推荐”与原因
- 计划：入场/止损/止盈/仓位/执行窗口/触发；联网检索增强；校验失败阻断发布
- 盘中：5 分钟内重评与替代策略；情绪反转强度超阈值→仓位下调≥50%
- 观测与成本：指标/日志/告警齐备；代理异常不泄露密钥；DeepSeek 走代理、温度 0.2–0.4、函数调用 JSON；结果缓存

## 当前 Sprint 重点（M2 Beta）
- Ingestion：REST 源适配器；ETag/Last-Modified 条件请求与 304 指标
- 去重：content_hash 与 link_canon_hash 入库，dedupe_rate 指标
- AI/LLM：缓存键 `content_hash+prompt_version`；失败回退 `degraded=true`；成本/延迟阈值告警
- Scheduler：连续失败熔断与告警挂钩
- IntradayWatcher：最小 N 分钟轮询与缩仓建议，审计可追溯

## 关联文档
- 需求：`.kiro/specs/preopen-news-driven-plan/requirements.md`
- 设计：`.kiro/specs/preopen-news-driven-plan/design.md`
- 任务：`.kiro/specs/preopen-news-driven-plan/tasks.md`
- Impl 映射：`.kiro/specs/preopen-news-driven-plan/spec-impl-1.md`、`.kiro/specs/preopen-news-driven-plan/spec-impl-2.md`、`.kiro/specs/preopen-news-driven-plan/spec-impl-3.md`

## M2 计划（Beta 灰度）
- 实体与标注：接入 `EntityResolver` 与 `Tagger`，规则优先，LLM 失败回退，命中缓存键为 `content_hash+prompt_version`。
- 多样性去偏：按行业约束与惩罚项完善 `select_top_n`，记录去偏前后差异与 `weight_version`。
- 采集增强：为非 RSS 源补齐条件请求与备用源降级；错误上下文与 304 命中率指标。
- 计划联网增强：`WebEnricher` 检索公告/研报/监管动态，更新证据与置信度。
- 盘中监控：`IntradayWatcher` 每 N 分钟轮询，触发重评与替代策略（缩仓/撤单/延迟/对冲）。
- 调度与控制：`/v1/scheduler/status|start|stop|restart` 已有，结合熔断阈值与重试队列占位 `/v1/pipeline/preopen/retry`。
- 可观测性：完善 `/v1/metrics` 快照；结构化日志字段：`task_id, stage, source, error_code, retriable, dedupe_key`。

## 观测与指标（M2 必备）
- 抓取成功率、304 命中率、去重率、耗时分位（阶段级）、LLM 成功率/延迟/缓存命中率、Top-N 分布与行业集中度、计划校验失败率、告警计数。
- 关键事件：`pipeline.started/topn_ready/plan_ready/failed`、`intraday.reassess`、`alert.triggered`。
- SLA 时间点：T-45/T-35/T-30 命中与超时样本。

## 风险与缓解
- 源质量与速率波动：多源冗余、备用源、条件请求与内容去重；失败路径降级并记录上下文。
- 实体歧义与低置信：LLM 消歧与复核队列；别名/行业词典更新。
- LLM 失败与成本：结果缓存、配额限流、规则化回退；超时/5xx 重试退避。
- 时效与延迟：并发与限流、阶段并行化、去偏与校验在 Top-N 后并行。
- 观测盲区：结构化日志与指标覆盖，至少 3 条关键告警在演练中有效触发。

## 时间表（建议）
- 第 1 周：EntityResolver/Tagger 接入与缓存；采集条件请求与降级完善；指标埋点补齐。
- 第 2 周：多样性去偏、WebEnricher、/v1/metrics 输出、告警规则与阈值；灰度到单市场。
- 第 3 周：IntradayWatcher、熔断与重试路径联动、文档与演练；小范围 Beta。

## 灰度与回滚
- 按市场/板块灰度开关；A/B 切换 `weight_version`。
- 回滚剧本：禁用 LLM 走规则化；配置与权重回退；失败批次重放与补偿。 