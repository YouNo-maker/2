# 注意：此文件已弃用（Deprecated）

- 请仅维护任务于 `/.kiro/specs/preopen-news-driven-plan/tasks.md`。
- 本文件保留作历史参考，内容不再更新。
- 若发现与 `tasks.md` 不一致之处，以 `tasks.md` 为准。

---

# Pre-Open News Driven Plan — Spec & Tasks

## 1. 概述（Overview）
- 功能名称: 开盘前新闻驱动的操盘计划（preopen-news-driven-plan）
- 目标与动机:
  - 在每日开盘前 T-60 至 T-30 时间窗内，自动汇聚多源新闻、解析实体与事件/情绪、进行多维打分，筛选 Top-N 候选并产出 Top-1 可执行操盘计划（JSON+Markdown），交易时段内可动态调整。
  - 提升开盘前决策效率与胜率；保障稳定性、可观测性、合规与成本控制。
- 非目标:
  - 不覆盖跨日持仓策略与组合优化；不承担行情撮合/下单；不构建通用新闻门户。
- 范围:
  - 平台: 后端服务/任务流（可由 CLI/调度器触发）；观测输出与告警；无 GUI 前端。
  - 市场: 按 `market` 配置（示例 SSE），可扩展多市场/多板块灰度启用。

## 2. 用户与场景（Personas & Scenarios）
- 角色:
  - 量化研究员/交易员: 使用 Top-N/Top-1 输出与 `plan.md` 人读摘要。
  - 平台运营者/风控: 关注指标、告警、SLA 与合规。
- 核心旅程（开盘前）:
  1) Scheduler 在 T-60 触发 → 2) Ingestion 抓取增量 → 3) Normalize 清洗/去重 → 4) Entity/Tagger 实体/事件/情绪 → 5) Scoring 计算与去偏 → 6) Planner 生成计划与联网增强 → 7) 输出与可观测。
- 盘中旅程（突发/动态调整）:
  - Intraday Watcher N 分钟轮询，触发重评与替代策略，并发送通知。
- 边界/异常:
  - 源 5xx/超时/限流、代理异常、LLM 降级、数据缺失、行业集中度过高、候选置信不足。

## 3. 需求映射（FRD from Requirements.md）
- R1 新闻获取与调度: 定时、并发抓取、速率限制、重试/降级、条件请求、T-45 完成首次抓取。
- R2 解析与规范化: 标准化字段、语言标注、去重、HTML 去噪、质量统计。
- R3 实体映射与标注: 证券字典、候选歧义与置信、事件类型、情绪方向与强度、证据索引、复核队列。
- R4 多维打分与 Top-N: 聚合权重、行业多样性去偏、权重版本化、无推荐时返回原因、T-35 前产出。
- R5 操盘计划与校验: 入场/止损/止盈/仓位/执行窗口、联网检索增强、缺失回退、校验失败阻断发布、T-30 前完成。
- R6 突发与动态调整: 5 分钟内重评、情绪阈值触发降仓、轮询与熔断策略。
- R7 观测与 SLA: 指标、结构化日志、告警、机器可解析事件输出。
- R8 模型与代理约束: DeepSeek 代理/温度/配额、失败回退与缓存、限流保核心路径。

## 4. 架构与编排（Architecture & Orchestration）
- 调度:
  - `PreOpenPipeline.run(market, trade_date)` at T-60；总超时与并发窗口；批次幂等 `task_id = {market}_{trade_date}`。
  - `IntradayWatcher.run(market, trade_date)` 交易时段内每 N 分钟轮询。
- 处理流水线:
  1) NewsFetcher → 2) Normalizer → 3) EntityResolver → 4) Tagger → 5) Scorer → 6) Planner → 7) WebEnricher → 8) Persist/Emit。
- 可靠性与回退:
  - 指数退避重试、备用源降级、LLM 失败回退规则化输出、低置信进入复核、不阻塞主流。
- 可扩展:
  - SourceAdapter 插拔；事件类型/权重可配置与版本化；缓存与限流。

## 5. 数据模型与存储（Models & Storage）
- 原始与规范化:
  - `raw_news(source_id, payload, etag, last_modified, fetched_at)`
  - `normalized_news(id, title, content, published_at, source_id, url, authors[], language, content_hash, link_canon_hash, outbound_link_count, quality)`
- 实体与标注:
  - `news_entities(news_id, exchange, code, name, confidence, evidence_indices[])`
  - `news_events(news_id, type, evidence_indices[])`
  - `sentiment(news_id, direction, score)`
- 打分与候选:
  - `stock_scores(as_of, exchange, code, scores{...}, aggregate_score, weight_version)`
  - `top_candidates(as_of, market, list[exchange, code, aggregate_score])`
- 计划:
  - `trade_plans(version, generated_at, symbol{exchange,code}, entry{...}, stop_loss{...}, take_profit{...}, position_limit_pct, execution_window_min, triggers[], evidence[], confidence, validation{passed, issues[]}, plan_json, plan_md)`
- 复核与重试:
  - `review_queue(item_type, ref_id, reason, created_at)`、`retry_queue(task, args, backoff_state)`
- 缓存:
  - `llm_cache(key = content_hash+prompt_version, result, ttl)`

## 6. API 契约（Interfaces）
- 任务入口:
  - `PreOpenPipeline.run(market: string, trade_date: string) -> { task_id, started_at, deadlines: {fetch:T-45,topn:T-35,plan:T-30} }`
  - `IntradayWatcher.run(market: string, trade_date: string) -> { task_id, poll_interval_minutes }`
- 内部服务（示意 JSON I/O）:
  - `NewsFetcher.fetchIncremental(source_id: string, since: ISO8601) -> [raw_news] | {error}`
  - `Normalizer.normalize(raw) -> normalized_news`
  - `EntityResolver.resolve(news) -> { symbols[], confidence_stats, evidence }`
  - `Tagger.tag(news_entities) -> { events[], sentiment }`
  - `Scorer.rank(candidates, weights) -> { ranked: [{symbol, aggregate_score, scores}], topN }`
  - `Planner.generate(top1, market_features) -> { plan_json, plan_md, validation }`
  - `WebEnricher.enrich(plan) -> { plan_json, plan_md, confidence_delta, evidence+ }`
- 错误:
  - 统一结构 `{ code, message, retriable: boolean, context }`；配合 `task_id` 与 `dedupe_key` 幂等。

## 7. 配置（YAML 示例）
```yaml
market: SSE
preopen:
  first_fetch_minutes_before_open: 60
  topn_output_minutes_before_open: 35
  plan_output_minutes_before_open: 30
sources:
  - id: rss_xxx
    type: rss
    qps: 2
    concurrency: 2
    retry: {max: 3, backoff_ms: 250}
llm:
  provider: deepseek
  temperature: 0.3
  proxy: http://proxy.local:7890
  timeout_ms: 12000
  cache_ttl_minutes: 1440
scoring:
  weights:
    relevance: 0.25
    sentiment_strength: 0.20
    event_weight: 0.25
    recency: 0.20
    source_trust: 0.10
  diversity:
    sector_cap_pct: 60
intraday:
  poll_interval_minutes: 5
alerts:
  error_rate_threshold: 0.01
```

## 8. 计算与算法（Scoring/Planning）
- Scoring:
  - 维度: 相关性、情绪强度、事件权重、时效衰减、来源可信度、证据质量（可选）。
  - 聚合: 可配置加权求和；支持权重版本化；行业多样性去偏（sector_cap_pct）。
- Planner:
  - 输入: Top-1 股票与市场特征（昨收、ATR、波动率、均线、支撑/阻力）。
  - 规则: 入场区间（昨收与关键位+波动带）、止损（ATR/支撑下方）、止盈（R:R、阻力位与动量）、仓位上限（由情绪与置信度驱动）、执行窗口与触发条件。
  - 校验: 入场/止损/止盈一致性与可执行性；失败则阻断并给出修复建议。
  - 增强: 联网检索公告/研报/监管动态，调整置信与证据。

## 9. 非功能与 SLA（NFR & SLA）
- 时效: T-45 完成首次抓取；T-35 完成 Top-N；T-30 完成计划。
- 可靠性: 抓取成功率≥99%；失败回退与降级可用；幂等与熔断保护。
- 成本: LLM 结果缓存；非核心路径限流；配额阈值控制。
- 观测: 指标（抓取成功率、去重率、置信度分布、耗时分位、LLM 成功率与延迟、缓存命中率、告警计数）；结构化日志；SLA 报表。
- 安全与合规: 密钥安全、代理与外部调用审计、敏感信息脱敏。

## 10. 测试计划（Testing）
- 单元: 适配器（RSS/REST/HTML）、去重与哈希、实体映射与规则/LLM 回退、打分、计划校验逻辑。
- 合约与集成: 端到端（含代理、缓存、回退与熔断）、接口错误结构一致性。
- 回归: 权重与去偏策略版本化对比。
- 负载与限流: 速率限制、并发与重试行为验证；LLM 配额模拟。

## 11. 实施计划与任务拆解（Milestones & Tasks）
- 里程碑:
  - M1 可用原型（内测）: 完成核心流水线端到端（无联网增强），指标与基本告警；交付 Top-N 与初版计划（T-30）。
  - M2 Beta（灰度）: 增加联网增强、行业去偏策略、缓存与限流完善、复核/重试队列、盘中监控。
  - M3 GA（全量）: SLA 达标、权重版本化与历史校准、仪表盘、回滚策略与剧本完善。
- 任务拆解（按职能）:
  - 后端/服务:
    - Scheduler: 交易所日历、T-60 触发、批次幂等、熔断与告警挂钩。
    - Ingestion: SourceAdapter、速率限制、重试/降级、条件请求、去重（content_hash/link_canon_hash）。
    - Normalize: 字段抽取、HTML 去噪、语言判定、质量统计。
    - EntityResolver: 证券字典加载、规则匹配、LLM 辅助消歧、置信度与证据索引。
    - Tagger: 事件类型与情绪（规则→LLM 回退）、参数化温度/超时、缓存键。
    - Scorer: 各维度打分、权重聚合、行业多样性去偏、阈值与“无推荐”。
    - Planner: 规则生成、参数缺失回退、内部校验、联网 Enricher、输出 JSON+Markdown。
    - IntradayWatcher: 轮询、触发条件、替代策略（缩仓/撤单/延迟/对冲）、通知集成。
    - Persistence: 各模型表与索引、版本与审计字段、复核与重试队列。
    - Config & Secrets: 分层配置、热更新（谨慎）、代理与密钥安全读取。
  - 可观测性:
    - 指标埋点（成功率、耗时分位、LLM 成功/延迟、缓存命中）、结构化日志、SLA 时间点事件。
    - 告警规则（抓取成功率<99%、源连续失败熔断、LLM 异常、延迟超标）。
  - 数据/分析:
    - 权重版本化与历史校准；Top-N/Top-1 结果对比分析与回测接口（如适配）。
  - QA:
    - 用例集（边界与异常）、E2E 测试流、性能与限流验证、回归范围。
  - 运维:
    - 配置与开关管理、灰度计划（市场/板块）、回滚与补偿、监控面板。
- 定义完成（DoD）:
  - 合约测试通过；端到端成功率≥SLA；P95 时效满足 T-45/T-35/T-30；无高危告警；关键指标上报全量；文档与运行手册就绪。

### 11.1 详细任务列表（分解 + DoD + 依赖）

- 后端/服务
  - Scheduler（M1）
    - 交易所日历：实现 `is_trading_day(date)`、`next_open(date)`、`next_close(date)`；支持假日覆盖与时区。
    - 触发与幂等：`PreOpenPipeline.run(market, trade_date)` 带 `task_id` 幂等与重复启动合并；超时与并发窗口配置。
    - 熔断与告警挂钩：连续失败阈值（可配置）→ 暂停触发并发出 `alert.scheduler.circuit_open`。
    - DoD：支持 T-60 触发一次且同批次二次调用不重复执行；异常路径产出结构化日志与告警事件。
    - 依赖：配置中心、可观测事件总线。
  - Ingestion（M1→M2 增强）
    - SourceAdapter 抽象：定义接口（init/fetch/teardown）、注册表与 YAML 校验。
    - 速率与并发：按源 Token Bucket（qps）+ 并发闸（concurrency）。
    - 重试/降级：指数退避（250ms*2^k，k≤3）；失败切换备用源，携带错误上下文。
    - 条件请求：ETag/Last-Modified 透传；304 计数指标。
    - 去重：`content_hash`（正文规范化后）、`link_canon_hash`（URL 规范化）；首个可信来源保留策略。
    - DoD（M1）：支持≥1 种源（RSS 或 REST），去重有效并产出统计；（M2）备用源降级与条件请求全量生效。
    - 依赖：Normalize、Persistence、可观测指标。
  - Normalize（M1）
    - HTML 去噪：白名单标签、移除脚本/样式、外链计数。
    - 语言判定：基于标签优先，缺失时自动检测；记录 `language`。
    - 字段质量：必填字段完整率统计与缺失告警（阈值可配）。
    - DoD：输出字段集合完整、质量统计入库；异常样本进入复核队列。
    - 依赖：Persistence、可观测日志。
  - EntityResolver（M2）
    - 证券字典：加载交易所、代码、简称、别名、行业；增量更新机制。
    - 匹配：规则精确/模糊，低置信调用 LLM 消歧（可禁用）。
    - 证据：句级索引与命中片段回填；`confidence` 输出并阈值化入复核。
    - DoD：对样本集合输出稳定置信与证据；<0.70 自动入复核队列。
    - 依赖：LLM 适配器、缓存、Persistence。
  - Tagger（M2）
    - 事件/情绪规则：关键词/模式；不足时 LLM 回退；结果缓存键=`content_hash+prompt_version`。
    - 参数化：温度/超时/重试/代理可配，失败路径降级到规则。
    - DoD：同一 `content_hash` 命中缓存；失败标注 `degraded=true` 与原因。
    - 依赖：LLM、缓存、可观测（命中率、耗时）。
  - Scorer（M1→M2 去偏）
    - 特征计算：相关性、情绪强度、事件权重、时效衰减、来源可信度。
    - 聚合：权重加和（v1.0.0）；输出 `aggregate_score` 与各维度贡献。
    - 多样性去偏（M2）：行业约束与惩罚项，记录前后差异。
    - 阈值与无推荐：`min_aggregate_score`；不足返回 `reason`。
    - DoD：Top-N 稳定产出；（M2）去偏对 Top-N 有可解释差异记录。
    - 依赖：配置权重、数据字典。
  - Planner（M1→M2 联网增强）
    - 规则生成：入场/止损/止盈/仓位/执行窗口/触发条件。
    - 校验：一致性与可执行性，失败阻断并返回修复建议。
    - 联网 Enricher（M2）：公告/研报/监管动态检索，更新证据与置信。
    - 输出：`plan_json` 与 `plan_md`，记录 `validation` 与版本。
    - DoD：`plan_json` 可机读校验通过；（M2）联网增强能影响 `confidence_delta`。
    - 依赖：Scorer、外部检索、Persistence。
  - IntradayWatcher（M2）
    - 轮询：交易时段内每 N 分钟；失败退避与最终告警。
    - 触发：负面舆情/监管/异常波动；重评与替代策略（缩仓/撤单/延迟/对冲）。
    - 通知：与告警系统集成（渠道可配）。
    - DoD：触发到输出≤5 分钟；事件审计可追溯。
    - 依赖：可观测、Planner、Scorer。
  - Persistence（M1）
    - 表与索引：`raw_news`、`normalized_news`、`news_entities`、`news_events`、`sentiment`、`stock_scores`、`top_candidates`、`trade_plans`、`review_queue`、`retry_queue`、`llm_cache`。
    - 审计：版本与创建/更新时间、来源追溯字段；关键列索引与唯一约束。
    - DoD：迁移脚本可回滚；读写路径贯通并含最小示例数据。
    - 依赖：无（底座）。
  - Config & Secrets（M1→M2 热更新）
    - 分层配置：默认→环境→工作区覆盖；必要字段校验与错误提示。
    - 代理与密钥：HTTP(S) 代理统一；`LLM_API_KEY` 安全读取；脱敏日志。
    - 热更新（M2）：受控开关与白名单字段，失败回滚。
    - DoD：启动时校验通过；（M2）热更新生效且有审计记录。

- 可观测性（M1→M2 告警完善）
  - 指标：成功率、耗时分位、LLM 成功/延迟、缓存命中、SLA 时间点事件、304 命中率、重试计数。
  - 日志：结构化字段（task_id、stage、source、error_code、retriable、dedupe_key）。
  - 告警：抓取成功率<99%、连续失败熔断、LLM 超时/配额、阶段延迟超标。
  - DoD：核心指标在 `/v1/metrics` 暴露；至少 3 条关键告警在灰度演练中触发并恢复。

- 测试（贯穿 M1-M3）
  - 单元：适配器、去重与哈希、实体匹配与回退、打分、计划校验。
  - 合约/集成：端到端（含代理、缓存、回退与熔断）；错误结构一致性。
  - 桩与夹具：LLM Mock（可控延迟/失败率/返回），新闻源录制回放。
  - 性能与限流：QPS/并发/重试行为验证；缓存命中 A/B。
  - DoD：CI 最低覆盖率阈值（行 70%/分支 60%）；E2E 稳定通过。

- 运维与运营（M2→M3）
  - 开关管理与灰度（市场/板块），按 `weight_version` A/B。
  - 回滚与补偿：失败批次重放、配置回滚、规则/权重回退。
  - 监控面板：关键指标与告警总览；SLA 报表（可选）。
  - DoD：灰度切换无感；回滚剧本 1 次演练通过。

- 里程碑交付清单
  - M1（最小可用）
    - PreOpenPipeline 端到端（无联网增强）；Ingestion（单源）+ Normalize + Scorer + Planner（规则）+ Persistence；基本指标 + 2 条告警；Top-N 与 `plan.json`/`plan.md` 产出。
  - M2（灰度）
    - EntityResolver + Tagger（含 LLM 回退与缓存）；Ingestion 备用源/条件请求；多样性去偏；联网 Enricher；IntradayWatcher；完整告警集与灰度开关。
  - M3（全量）
    - SLA 达标；权重版本化与历史校准；仪表盘与报表；回滚与补偿完善；安全与合规加固。

## 12. 验收标准（Acceptance Criteria）
- AC-PreOpen:
  - T-45 完成首次抓取；T-35 输出 Top-N（默认 5）；T-30 产出 `plan.json` 与 `plan.md`，并包含校验结果。
  - 任一源 5xx/超时/限流 → 最多 3 次退避重试，失败降级到备用源并记录上下文。
  - 速率限制与并发不超过配置阈值；条件请求使用 ETag/Last-Modified；去重保留首个可信来源。
- AC-Entity/Tagging:
  - 证券映射输出置信度；<0.70 标记复核；多候选返回理由与证据索引。
  - 事件类型与情绪方向/分数正确输出；LLM 失败回退规则化并标注降级原因。
- AC-Scoring/Selection:
  - 聚合分按权重版本化；行业多样性去偏生效并记录差异；当无候选达阈值时返回“无推荐”，含原因。
- AC-Planner:
  - 计划包含入场/止损/止盈/仓位/执行窗口/触发条件；联网检索补全证据并调整置信；校验失败阻断并返回修复建议。
- AC-Intraday:
  - 突发/异常在 5 分钟内重评并输出替代策略；情绪由正转负且强度超阈值 → 仓位建议下调≥50%，并通知。
- AC-Observability & SLA:
  - 指标、日志与告警完整输出；代理/网络异常打印环境与回退策略，且不泄露密钥；机器可解析事件产出。
- AC-LLM & Cost:
  - DeepSeek 通过 HTTP(S) 代理，温度 0.2–0.4，函数调用 JSON；失败重试与配额限流；缓存命中直接返回。

## 13. 发布、回滚与运营（Release & Ops）
- 发布策略: 市场/板块灰度；开关控制；权重/规则版本化；读写双轨（如需）。
- 回滚策略: 配置回滚、规则/权重回退、禁用 LLM 走规则化降级；任务级补偿与重放（基于队列/缓存）。
- 监控与告警: 预设阈值；分布式追踪（可选）；SLO/SLA 报表。
- 故障剧本: 源整体异常、代理不可用、LLM 配额耗尽、缓存雪崩、数据库瓶颈。

## 14. 风险与对策（Risks & Mitigations）
- 源质量与速率波动 → 多源冗余、备用源、指纹去重与条件请求。
- 实体歧义/低置信 → LLM 辅助消歧与复核队列、行业与别名字典扩充。
- LLM 失败/成本超额 → 结果缓存、配额限流、规则化回退、提示工程与函数调用收敛。
- 时效与延迟 → 并发与分段流水线、超时与重试窗口、去偏与校验并行化。
- 观测盲区 → 结构化日志与指标覆盖、演练告警。

## 15. 开放问题（Open Questions）
- 目标市场/交易所清单与交易日历来源？
- 证券主数据与行业映射的权威来源与更新频率？
- 联网增强的数据源与额度限制？是否需要抓取全文内容与版权合规评估？
- 盘中通知渠道（邮件/IM/Webhook）与路由策略？
- 最小置信阈值与行业去偏参数的初始默认值与校准流程？ 

## 16. API 接口详解（HTTP + 内部 RPC）
- 认证与安全:
  - 支持 `Authorization: Bearer <token>` 或 `X-API-Key: <key>`；优先 Bearer。
  - 幂等头: `Idempotency-Key`（建议 `market_tradeDate`）；关联 ID: `X-Request-Id`。
  - 速率限制响应头: `X-RateLimit-Limit`/`Remaining`/`Reset`。
  - 审计字段: `X-Caller`、`X-Env`；禁止在日志中输出密钥/令牌。
- 通用查询参数与分页:
  - `page`、`page_size`（默认 50，最大 200）、`next_token`（连续分页）
  - 时间过滤: `as_of`（ISO8601）、`from`/`to`

### 16.1 外部 REST Endpoints
- POST `/v1/pipeline/preopen/run`
  - 描述: 触发 T-60 开盘前流水线（可在日内补跑）。
  - Request:
```json
{
  "market": "SSE",
  "trade_date": "2025-09-10",
  "deadlines": {
    "fetch_min_before_open": 45,
    "topn_min_before_open": 35,
    "plan_min_before_open": 30
  },
  "force_recompute": false,
  "dedupe_key": "SSE_2025-09-10"
}
```
  - Response 202 Accepted:
```json
{
  "task_id": "preopen_SSE_2025-09-10",
  "status": "pending",
  "deadlines": {"fetch":"T-45","topn":"T-35","plan":"T-30"}
}
```

- GET `/v1/pipeline/preopen/status`
  - Query: `task_id`
  - Response 200:
```json
{
  "task_id": "preopen_SSE_2025-09-10",
  "status": "running",
  "stage": "Scorer",
  "started_at": "2025-09-10T00:00:00Z",
  "percent": 62,
  "errors": [],
  "metrics": {"elapsed_ms": 42310}
}
```

- GET `/v1/news/topn`
  - Query: `market`, `as_of`, `n`（默认 5）
  - Response 200:
```json
{
  "as_of": "2025-09-10T00:25:00Z",
  "market": "SSE",
  "topn": [
    {
      "symbol": {"exchange": "SSE", "code": "600519"},
      "aggregate_score": 0.78,
      "scores": {
        "relevance": 0.86,
        "sentiment_strength": 0.72,
        "event_weight": 0.90,
        "recency": 0.66,
        "source_trust": 0.80
      },
      "evidence": {
        "news_ids": ["n_abc123", "n_def456"],
        "events": ["earnings", "regulatory"],
        "sentiment": {"direction": "positive", "score": 0.63}
      }
    }
  ],
  "weight_version": "v1.0.0"
}
```

- GET `/v1/plan/latest`
  - Query: `market`, `trade_date`
  - Response 200:
```json
{
  "market": "SSE",
  "trade_date": "2025-09-10",
  "plan_json": {"symbol": {"exchange": "SSE", "code": "600519"}, "entry": {"type": "range", "low": 1685.0, "high": 1702.0}, "stop_loss": {"type": "price", "value": 1650.0}, "take_profit": {"type": "rr", "rr": 2.0}, "position_limit_pct": 10, "execution_window_min": 20, "triggers": ["gap_up<2%","vol_spike<2x"]},
  "plan_md": "## 今日计划...",
  "validation": {"passed": true, "issues": []},
  "generated_at": "2025-09-10T00:30:00Z"
}
```

- POST `/v1/plan/validate`
  - Body: `plan_json`
  - Response 200:
```json
{"passed": false, "issues": ["stop_loss above entry_low"], "severity": "error"}
```

- POST `/v1/retry`
  - 描述: 将失败项放入重试队列。
  - Body: `{ "task": "news_fetch", "args": {...} }`

- GET `/v1/metrics` / `/v1/health`
  - 暴露基本指标与健康状态，Prometheus 兼容文本格式可选。

### 16.2 Webhook 事件（可选）
- 事件名: `pipeline.started`、`pipeline.topn_ready`、`pipeline.plan_ready`、`pipeline.failed`、`intraday.reassess`、`alert.triggered`
- 事件示例:
```json
{
  "event": "pipeline.plan_ready",
  "task_id": "preopen_SSE_2025-09-10",
  "market": "SSE",
  "trade_date": "2025-09-10",
  "plan_id": "plan_01H...",
  "generated_at": "2025-09-10T00:30:00Z"
}
```

### 16.3 错误码与 HTTP 映射
- `E1001 SourceTimeout` → 504；`E1002 RateLimited` → 429；`E2001 NormalizeError` → 422；
- `E3001 EntityAmbiguous` → 409；`E3002 LLMCallFailed` → 502；
- `E4001 ScoringWeightsInvalid` → 400；`E4002 NoCandidateAboveThreshold` → 200（携带 reason）；
- `E5001 PlanValidationFailed` → 422；`E9001 InternalError` → 500。
- 错误结构统一:
```json
{"code": "E3002", "message": "LLM call failed", "retriable": true, "context": {"provider": "deepseek", "timeout_ms": 12000}}
```

### 16.4 内部 RPC（示意）
- 统一以 JSON Schema 约束 I/O，支持 gRPC/HTTP 任一实现；请求包含 `task_id`/`dedupe_key`。
- `NewsFetcher.fetchIncremental({source_id, since}) -> {items: [raw_news], stats}`
- `EntityResolver.resolve({news}) -> {symbols[], evidence_indices[], confidence_stats}`
- `Tagger.tag({news_entities}) -> {events[], sentiment}`
- `Scorer.rank({candidates, weights, diversity}) -> {ranked[], topN, diagnostics}`
- `Planner.generate({top1, market_features}) -> {plan_json, plan_md, validation}`


## 17. AI 模型调用与提示工程（LLM Invocation）
- 供应商与接入:
  - Provider: `deepseek`；Base URL: 由配置 `llm.base_url`；代理 `llm.proxy`；Key: `LLM_API_KEY`（环境变量）。
  - 默认参数: `temperature=0.3`、`top_p=0.9`、`max_tokens=1024`、`timeout_ms=12000`、`retries=3`、退避 `250ms*2^k`。
  - 观测: 计时、成功率、超时与重试计数、token 估算成本、缓存命中率。
- 函数调用（Function Calling）定义:
  - `extract_entities`
```json
{
  "name": "extract_entities",
  "parameters": {
    "type": "object",
    "properties": {
      "symbols": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "exchange": {"type": "string"},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "aliases": {"type": "array", "items": {"type": "string"}}
          },
          "required": ["exchange", "code", "confidence"]
        }
      },
      "evidence_indices": {"type": "array", "items": {"type": "integer"}}
    },
    "required": ["symbols"]
  }
}
```
  - `tag_events_and_sentiment`
```json
{
  "name": "tag_events_and_sentiment",
  "parameters": {
    "type": "object",
    "properties": {
      "events": {"type": "array", "items": {"type": "string", "enum": ["earnings","regulatory","mna","product","macro","rumor"]}},
      "sentiment": {"type": "object", "properties": {"direction": {"type": "string", "enum": ["positive","negative","neutral"]}, "score": {"type": "number", "minimum": -1, "maximum": 1}}, "required": ["direction","score"]}
    }
  }
}
```
  - `generate_plan`
```json
{
  "name": "generate_plan",
  "parameters": {
    "type": "object",
    "properties": {
      "symbol": {"type": "object", "properties": {"exchange": {"type": "string"}, "code": {"type": "string"}}, "required": ["exchange","code"]},
      "entry": {"type": "object", "properties": {"type": {"type": "string", "enum": ["range","stop"]}, "low": {"type": "number"}, "high": {"type": "number"}}},
      "stop_loss": {"type": "object", "properties": {"type": {"type": "string", "enum": ["price","percent"]}, "value": {"type": "number"}}},
      "take_profit": {"type": "object", "properties": {"type": {"type": "string", "enum": ["rr","price"]}, "rr": {"type": "number"}, "value": {"type": "number"}}},
      "position_limit_pct": {"type": "number"},
      "execution_window_min": {"type": "integer"},
      "triggers": {"type": "array", "items": {"type": "string"}},
      "evidence": {"type": "array", "items": {"type": "string"}},
      "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["symbol","entry","stop_loss","take_profit","position_limit_pct"]
  }
}
```
  - `validate_plan`
```json
{
  "name": "validate_plan",
  "parameters": {
    "type": "object",
    "properties": {
      "passed": {"type": "boolean"},
      "issues": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["passed"]
  }
}
```
- 提示与上下文:
  - System Prompt 模板: 角色=金融 NLP/交易助理；输出必须符合 JSON Schema；禁止编造不存在的证券代码；不确定时降低 `confidence` 并返回复核理由。
  - 少样本（可选）: 每个函数保留 1-2 个短示例，版本化 `prompt_version`。
- 缓存与回退:
  - 缓存键: `sha256(content_hash + prompt_version + function_name)`；TTL `llm.cache_ttl_minutes`（默认 1440）。
  - 回退策略: 超时/失败→规则化算法（正则/词典/启发式）；标注 `degraded=true` 与 `degrade_reason`。
- 合规与过滤:
  - 屏蔽敏感/受限领域；只允许公开新闻内容；遵守版权与隐私；脱敏日志。


## 18. 打分权重细化与优化（Scoring Weights & Tuning）
- 特征与归一化:
  - `relevance`∈[0,1]（实体匹配置信与主题相似度）；`sentiment_strength`∈[0,1]（|情绪|）；
  - `event_weight`∈[0,1]（事件类型映射分）；`recency` 使用半衰期衰减 `half_life_hours=6`：`recency = exp(- ln(2) * age_hours / half_life_hours)`；
  - `source_trust`∈[0,1]（来源可信度基表）。
- 初始权重（v1.0.0）与约束:
  - `weights = {relevance:0.25, sentiment_strength:0.20, event_weight:0.25, recency:0.20, source_trust:0.10}`；非负、和为 1。
  - 事件加权系数 `event_multipliers`（乘于 `event_weight` 维度）:
```yaml
mna: 1.20
regulatory: 1.10
earnings: 1.00
product: 0.95
macro: 0.90
rumor: 0.70
```
- 多样性去偏（行业约束）:
  - 贪心选择+惩罚项: `score' = score - lambda * sector_count(symbol.sector)`，其中 `lambda` 默认 0.03，`sector_cap_pct=60`。
  - 记录前后分数差异以便审计与解释。
- 阈值与选择:
  - `min_aggregate_score=0.62`；不足则返回“无推荐”，并给出原因（如“情绪与可信度不足”）。
- 权重优化流程:
  - 离线: 历史标注/策略结果数据集，K 折（K=5）交叉验证，目标函数 AUC/F1/PR-AUC；
  - 搜索: 网格/贝叶斯优化（TPE）在约束域内寻找最优；
  - 标定: 使用逻辑回归/Platt scaling 将聚合分映射为胜率估计 `p(win)`；
  - 多市场/行业分桶: 按行业或波动率分层训练权重，产出 `weight_version` 与适用条件；
  - 上线: 灰度 A/B（`weight_version=vNext`）与在线多臂赌博机（epsilon-greedy ε=0.1）；
  - 验收: 线上 P90 胜率/回撤/命中率不劣于当前版本且满足风险阈值后晋升。
- 动态调整与自适应:
  - 盘中监控情绪突变: 若情绪由正转负且 `|Δscore_sentiment|>0.4` → `position_limit_pct` 至少下调 50%。
  - 配置覆盖:
```yaml
scoring:
  min_aggregate_score: 0.62
  diversity:
    lambda: 0.03
  event_multipliers_version: v1
```
- 诊断与可解释:
  - 输出各维度贡献、事件系数、行业惩罚 `lambda` 的影响、归一化中间值；
  - 记录 `weight_version` 与数据集哈希以便可追溯。