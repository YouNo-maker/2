# 设计说明（Design Spec）

## 1. 概览
本设计实现“开盘前新闻驱动的操盘计划”。系统在开盘前汇聚多源新闻→解析规范化→实体映射与情绪/事件标注→多维打分→生成 Top-N 候选→产出 Top-1 操盘计划，并在交易时段内对突发进行动态调整。整体满足稳定性、可观测、SLA、合规与成本控制（DeepSeek 调用约束）。

## 2. 架构
- 调度层：基于交易所日历的定时器与运行时编排（pre-open pipeline + intraday watcher）
- 采集层：新闻源连接器（REST/RSS/HTML），带速率限制/重试/降级
- 处理层：解析与规范化、实体解析、情绪/事件标注、打分与选择、计划生成
- 增强层：联网检索补全证据（公告/研报/监管动态）
- 存储层：原始与规范化数据、实体字典、索引与缓存
- 可观测层：指标、日志、告警、SLA 报表
- 集成层：代理与密钥管理、DeepSeek LLM 适配器、回退与缓存

### 2.1 数据流（高层）
1. Scheduler 触发 pre-open 流程（T-60 → T-35）
2. Ingestion 并发抓取增量新闻（ETag/Last-Modified）
3. Normalize 清洗标准化并去重
4. Entity Resolver 映射到证券，抽取事件与情绪（LLM+规则回退）
5. Scoring 聚合多维度分数与去偏，产出 Top-N
6. Planner 生成 Top-1 操盘计划，验证一致性，联网检索增强，输出 JSON+Markdown
7. Metrics/Logs 写入可观测系统；失败进入重试/复核队列
8. Intraday Watcher 交易时段轮询与触发重评

## 3. 关键组件设计

### 3.1 Scheduler（调度器）
- 输入：交易所日历、配置（时间偏移、轮询间隔）
- 流程：
  - T-60 触发 PreOpenPipeline（带超时与并发窗口）
  - 交易时段启动 IntradayWatcher（N 分钟轮询）
- 可靠性：
  - 幂等：以批次 ID（date+market）标识任务，重复启动只更新增量
  - 熔断：连续失败达阈值后暂停并告警

### 3.2 Ingestion（新闻采集）
- 支持源：RSS、REST、HTML（可扩展适配器 SourceAdapter）
- 速率限制：基于令牌桶/漏桶，按源配置 QPS、并发
- 重试/降级：指数退避，失败移交备用源，完整错误上下文记录
- 去重：链接规范化、正文内容哈希、指纹（title+pubtime+source）
- 条件请求：ETag/Last-Modified

### 3.3 Normalize（解析与规范化）
- 输出标准字段：`id, title, content, published_at, source_id, url, authors[], language, content_hash, link_canon_hash, outbound_link_count`
- 语言判定：lang tag 或自动检测；不强制翻译
- HTML 去噪：白名单标签、移除脚本样式、保留引文
- 质量控制：字段完整率统计与缺失校验

### 3.4 Entity Resolver（实体映射）
- 字典：证券主数据（交易所、代码、简称、别名）、行业映射
- 匹配：规则（精确/模糊）+ LLM 辅助消歧
- 置信度：0-1；多候选返回候选与理由，<0.70 标记复核
- 证据：句级索引与命中片段

### 3.5 Event & Sentiment Tagger（事件/情绪）
- 事件类型：财报、并购、监管、产能、供需、重大合同、诉讼等（可配置）
- 情绪：方向（多/空/中性）+ 强度（-1..1 或 0..1）
- 实现：规则（关键词/模式）→ 不足时调用 LLM；LLM 失败回退到规则化输出
- DeepSeek 使用：温度 0.2-0.4、函数调用返回 JSON、走全局 HTTP(S) 代理、超时与重试
- 缓存：对相同 content_hash + prompt_version 缓存 LLM 结果

### 3.6 Scoring & Selection（打分与选择）
- 维度：相关性、情绪强度、事件权重、时效衰减、来源可信度、证据质量
- 聚合：可配置加权求和；权重支持版本化与历史校准
- 业务约束：行业多样性去偏、最小置信阈值、样本量门槛
- 输出：Top-N（默认 5）

### 3.7 Planner（操盘计划生成）
- 输入：Top-1 股票 + 特征（昨收、波动率、ATR、均线、支撑阻力）
- 规则：
  - 入场区间：昨收与关键位的关系 + 波动率带
  - 止损：ATR 或支撑下方安全边际
  - 止盈：R:R 比、上方阻力位与动量
  - 仓位：情绪与置信度驱动的上限（含资金管理约束）
  - 执行窗口与触发条件：开盘后 N 分钟/成交量条件等
- 校验：入场/止损/止盈一致性、边界检查与可执行性
- 增强：联网检索公告/研报/监管动态，更新证据与置信度
- 输出：
  - 机器：`plan.json`（版本、参数、风控锚点与证据）
  - 人读：`plan.md`（摘要、理由、关键风险、情景预案）

### 3.8 Intraday Watcher（盘中监控）
- 触发条件：负面舆情/监管通告/异常波动
- 动作：重评计划并输出替代策略（缩仓/撤单/延迟/对冲）
- 通知：与告警系统集成（渠道可配置）

### 3.9 Observability（可观测）
- 指标：抓取成功率、去重率、映射置信度分布、处理耗时分位、LLM 成功率与延迟、缓存命中率、告警计数
- 日志：结构化日志（任务、源、错误、重试、降级）
- SLA：关键阶段完成时点（T-45 完成抓取、T-35 完成 Top-N、T-30 完成计划）

### 3.10 Config & Secrets（配置与密钥）
- 配置分层：默认→环境→工作区覆盖；支持热更新（谨慎）
- 代理：全局 HTTP(S) 代理地址与认证
- 密钥：DeepSeek API Key 安全存取（环境变量/密钥管理）

### 3.11 Storage（存储与模式）
- 原始：`raw_news`（源、原始 payload、etag/last_modified）
- 规范化：`normalized_news`（字段、哈希、质量指标）
- 实体与标注：`news_entities`、`news_events`、`sentiment`
- 打分与候选：`stock_scores`、`top_candidates`
- 计划：`trade_plans`（json+md、版本与校验状态）
- 复核与队列：`review_queue`、`retry_queue`
- 缓存：`llm_cache`（content_hash+prompt_version→result）

## 4. 数据模型（示例）

### 4.1 规范化新闻
```json
{
  "id": "news_20250910_001",
  "title": "某公司发布季度财报",
  "content": "...",
  "published_at": "2025-09-10T00:12:00Z",
  "source_id": "rss_xxx",
  "url": "https://example.com/a",
  "authors": ["编辑部"],
  "language": "zh",
  "content_hash": "sha256:...",
  "link_canon_hash": "sha256:...",
  "outbound_link_count": 3
}
```

### 4.2 实体与事件标注
```json
{
  "news_id": "news_20250910_001",
  "symbols": [
    {
      "exchange": "SSE",
      "code": "600000",
      "name": "浦发银行",
      "confidence": 0.86,
      "evidence_indices": [2, 5]
    }
  ],
  "events": [
    {
      "type": "earnings",
      "sentiment": { "direction": "bullish", "score": 0.62 },
      "evidence_indices": [3]
    }
  ]
}
```

### 4.3 打分结果
```json
{
  "as_of": "2025-09-10T00:20:00Z",
  "symbol": { "exchange": "SSE", "code": "600000" },
  "scores": {
    "relevance": 0.78,
    "sentiment_strength": 0.62,
    "event_weight": 0.80,
    "recency": 0.90,
    "source_trust": 0.85
  },
  "aggregate_score": 0.79,
  "weight_version": "2025-09-10"
}
```

### 4.4 操盘计划
```json
{
  "version": "v1",
  "generated_at": "2025-09-10T00:25:00Z",
  "symbol": { "exchange": "SSE", "code": "600000" },
  "entry": { "type": "range", "low": 9.85, "high": 9.98 },
  "stop_loss": { "type": "atr", "value": 0.35 },
  "take_profit": { "type": "rr", "rr": 2.0, "target": 10.7 },
  "position_limit_pct": 12,
  "execution_window_min": 20,
  "triggers": ["volume_spike", "breakout_ma"],
  "evidence": ["公告链接...", "研报摘要..."],
  "confidence": 0.72,
  "validation": { "passed": true, "issues": [] }
}
```

## 5. 接口与编排
- 任务入口：
  - `PreOpenPipeline.run(market, trade_date)`
  - `IntradayWatcher.run(market, trade_date)`
- 内部服务接口（示意）：
  - `NewsFetcher.fetchIncremental(source, since)`
  - `Normalizer.normalize(raw)`
  - `EntityResolver.resolve(news)`
  - `Tagger.tag(news_entities)`
  - `Scorer.rank(candidates, weights)`
  - `Planner.generate(top1, market_features)`
  - `WebEnricher.enrich(plan)`
- 幂等与重试：基于 `task_id` + `dedupe_key`；所有接口返回结构化错误

## 6. 非功能（NFR）与 SLA
- 时效：
  - T-45 完成首次抓取；T-35 完成 Top-N；T-30 完成计划
- 可靠性：抓取成功率≥99%，LLM 失败回退可用
- 可扩展：新增新闻源/事件类型/权重无需停机
- 成本控制：结果缓存；命中直接返回；非核心任务限流

## 7. 错误处理与回退
- 抓取失败→重试→备用源→降级
- 实体/情绪低置信→复核队列，不阻塞主流
- LLM 失败→规则化回退，标注降级原因
- 数据缺失→规则估算（ATR/昨收/支撑阻力）并下调置信度

## 8. 安全与合规
- 密钥管理：仅在运行时解密至内存；不落盘
- 审计：关键操作与外部调用审计日志
- 隐私：不记录敏感内容明文

## 9. 测试与验证
- 单测：适配器/打分/计划校验逻辑覆盖
- 集成：端到端（含代理、缓存、回退）
- 回归：权重与去偏策略版本化对比
- 负载：速率限制与并发行为验证

## 10. 推广与运维
- 灰度：市场/板块分批启用
- 回滚：按版本切换权重与规则
- 监控：指标面板与告警阈值预设

## 11. 配置示例（YAML）
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