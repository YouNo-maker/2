# Pre-Open News Driven Plan — Tasks

## 里程碑（Milestones）
- [x] M1 可用原型（内测）：完成核心流水线端到端（无联网增强），指标与基本告警；交付 Top-N 与初版计划（T-30）
  - 交付：PreOpenPipeline 端到端（无联网增强）；Ingestion（单源）+ Normalize + Scorer + Planner（规则）+ Persistence
  - 可观测：基础指标 + 至少 2 条告警
  - 输出：Top-N 与 plan.json/plan.md
  - AI：AI 问答接口骨架与适配器占位（本地 Mock，无联网）；流式响应占位（SSE/迭代器）与最小演示
- [ ] M2 Beta（灰度）：增加联网增强、行业去偏策略、缓存与限流完善、复核/重试队列、盘中监控
  - 交付：EntityResolver + Tagger（含 LLM 回退与缓存）；Ingestion 备用源/条件请求；多样性去偏；联网 Enricher；IntradayWatcher
  - 可观测：完整告警集与灰度开关
  - AI：DeepSeek 问答服务联通（Chat/Completions，流式）；Top-N 上下文注入；股票智能分析与证据汇总
  - 市场数据：价格快照/分时检索与缓存；相关新闻检索与利好/利空聚合
  - 方案：AI 生成投资方案（买/卖价区间、仓位建议、应急方案≥2 套），与规则 Planner 校验闭环
- [ ] M3 GA（全量）：SLA 达标、权重版本化与历史校准、仪表盘、回滚策略与剧本完善
  - 交付：SLA 达标；权重版本化与历史校准；仪表盘与报表；回滚与补偿完善；安全与合规加固
  - AI：提示词与版本管理；对话与计划生成一致性回归；成本/延迟优化

## 近期执行计划（Sprint：2025-09-17 → 2025-09-24）
- Scheduler
  - [ ] 交易所日历接入（真实交易日历与时区，替换“工作日≈交易日”的近似）
  - [ ] 连续失败熔断与告警挂钩（阈值可配，触发暂停并发出 alert.scheduler.circuit_open）
- Ingestion
  - [ ] REST 新闻源适配器（至少 1 个来源）：统一字段映射、时区/语言规范化
  - [ ] REST 条件请求与缓存（ETag/Last-Modified），记录 304 命中率
  - [ ] content_hash（正文规范化后）与 link_canon_hash 入库，参与软去重
  - [ ] 备用源降级与错误上下文携带（记录 retriable 与最后错误）
- AI/LLM
  - [x] 接口：/v1/ai/chat（会话，流式优先），支持超时/重试与首字节时间（TTFT）指标
  - [ ] 缓存：键=content_hash+prompt_version，TTL 与命中率指标；失败回退规则化并标注 degraded
  - [x] 指标与告警：成功率/延迟/成本阈值纳入 /v1/metrics 与 /v1/alerts
- 可观测性
  - [x] /v1/metrics 扩展（llm、dedupe、per-source），结构化日志字段补全（task_id/stage/source/error_code/retriable/dedupe_key）
  - [ ] 告警规则完善（llm 异常、latency p90 超阈、source 连续失败）
- IntradayWatcher
  - [ ] 最小版：交易时段 N 分钟轮询；负面舆情触发缩仓建议；事件审计可追溯
- QA/E2E
  - [x] 流式问答 E2E（断流/重试/续传；TTFT 与分段耗时）
  - [ ] Ingestion REST+条件请求 E2E（304/去重/降级路径）
  - [ ] 指标与告警灰度演练（至少触发并恢复 3 条关键告警）

- DoD（本 Sprint）
  - [x] /v1/ai/chat 流式端到端成功率 ≥ 99%，结构化错误返回一致
  - [ ] 新增 1 个 REST 源在本地可复现；304 命中率与去重率指标可见
  - [ ] content_hash 入库并参与去重；产生 dedupe_rate 指标并在 /v1/metrics 暴露
  - [x] LLM 指标在 /v1/metrics 暴露且具备告警；成本/延迟阈值可配置
  - [ ] IntradayWatcher 在模拟事件中 ≤5 分钟产出替代策略（缩仓），并记录审计

### Sprint 任务细化（执行清单）
- Scheduler：交易所日历与熔断
  - 子任务
    - [ ] 接入交易日历数据源与时区（Owner: BE，Estimate: 1.5d，依赖：无）
    - [ ] `is_trading_day/next_open/next_close` 对齐单元测试（Owner: BE，Estimate: 0.5d）
    - [ ] 连续失败计数与阈值开关（Owner: BE，Estimate: 0.5d，依赖：指标）
    - [ ] 熔断状态与自动恢复策略（Owner: BE，Estimate: 0.5d）
    - [ ] 告警事件 `alert.scheduler.circuit_open` 与演练（Owner: Ops，Estimate: 0.5d）
  - 验收
    - [ ] 指定非交易日不触发；T-60 仅触发一次
    - [ ] 连续 N（默认3）次失败进入熔断并触发告警；恢复后清零

- Ingestion：REST 源、条件请求、去重与降级
  - 子任务
    - [ ] 定义 `RestSourceAdapter` 接口与配置校验（Owner: BE，Estimate: 0.5d）
    - [ ] 实现首个 REST 源（Owner: BE，Estimate: 1.5d，依赖：配置）
    - [ ] 条件请求支持（ETag/Last-Modified）与 304 统计（Owner: BE，Estimate: 0.5d）
    - [ ] 正文规范化与 `content_hash` 计算（Owner: BE，Estimate: 0.5d）
    - [ ] `link_canon_hash` 规范化与软去重策略（Owner: BE，Estimate: 0.5d）
    - [ ] 备用源降级与错误上下文（Owner: BE，Estimate: 0.5d）
    - [ ] 指标上报：dedupe_rate、304 命中率、重试计数（Owner: BE，Estimate: 0.5d）
  - 验收
    - [ ] 304 命中率可在 `/v1/metrics` 查看；重复 URL 不入库
    - [ ] 同一 `content_hash` 命中缓存/不重复处理；降级路径可观察

- AI/LLM：流式 Chat、缓存与告警
  - 子任务
    - [x] `/v1/ai/chat` 流式（SSE/分块）与取消（Owner: BE，Estimate: 1.5d）
    - [ ] 首字节时间（TTFT）与分段耗时指标（Owner: Obs，Estimate: 0.5d）
    - [ ] 缓存键 `content_hash+prompt_version` 与 TTL，命中率指标（Owner: BE，Estimate: 0.5d）
    - [ ] 失败回退规则化输出 `degraded=true`（Owner: BE，Estimate: 0.5d）
    - [ ] 成本/延迟阈值告警（Owner: Obs，Estimate: 0.5d）
  - 验收
  - [ ] P99 无断流；异常返回结构统一；缓存命中可见

- 可观测性：指标、日志与告警
  - 子任务
    - [ ] `/v1/metrics` 扩展（llm、dedupe、per-source）（Owner: BE，Estimate: 0.5d）
    - [ ] 结构化日志字段补齐与脱敏（Owner: BE，Estimate: 0.5d）
    - [ ] 告警规则（llm 异常、latency p90、source 连续失败）（Owner: Obs，Estimate: 0.5d）
  - 验收
    - [ ] 至少 3 条关键告警在演练中触发并恢复

- IntradayWatcher：最小可用
  - 子任务
    - [ ] 轮询器与退避策略（Owner: BE，Estimate: 0.5d）
    - [ ] 负面舆情触发缩仓建议（Owner: BE，Estimate: 0.5d，依赖：Tagger 输出）
    - [ ] 审计事件与追溯（Owner: BE，Estimate: 0.5d）
  - 验收
    - [ ] 触发到输出 ≤ 5 分钟；审计事件包含 task_id、trigger、decision

- QA/E2E：覆盖关键路径
  - 子任务
    - [ ] 流式问答 E2E（断流/重试/续传）（Owner: QA，Estimate: 1.0d）
    - [ ] REST+条件请求 E2E（304/去重/降级）（Owner: QA，Estimate: 1.0d）
    - [ ] 指标与告警演练脚本（Owner: QA，Estimate: 0.5d）
  - 验收
    - [ ] E2E 全绿；关键指标/告警可视

## 任务拆解（按职能）

### 后端 / 服务
- [ ] Scheduler：交易所日历、T-60 触发、批次幂等、熔断与告警挂钩
  - [x] T-60 触发与批次幂等（最小实现，去重与状态端点）
  - [x] 交易所日历与时区（is_trading_day/next_open/next_close）
  - [ ] 连续失败熔断与告警挂钩
  - DoD：支持 T-60 触发一次且同批次二次调用不重复执行；异常路径产出结构化日志与告警事件
  - 依赖：配置中心、可观测事件总线
- [ ] Ingestion：SourceAdapter、速率限制、重试/降级、条件请求、去重（content_hash/link_canon_hash）
  - [x] RSS SourceAdapter（retries/qps/timeout），规范化 URL 去重，条件请求缓存（ETag/Last-Modified）
  - [ ] 备用源与降级、非 RSS 条件请求、多实例一致性策略
  - 速率与并发：按源 Token Bucket（qps）+ 并发闸（concurrency）
  - 重试/降级：指数退避（250ms*2^k，k≤3）；失败切换备用源，携带错误上下文
  - 条件请求：ETag/Last-Modified 透传；304 计数指标
  - 去重：content_hash（正文规范化后）、link_canon_hash（URL 规范化）；首个可信来源保留策略
  - DoD（M1）：支持≥1 种源（RSS 或 REST），去重有效并产出统计；（M2）备用源降级与条件请求全量生效
  - 依赖：Normalize、Persistence、可观测指标
  - 多源扩展（核心功能#2）：
    - [ ] REST 新闻源适配器（可配置 N 个）：统一字段映射、时区与语言规范化
    - [ ] 源权重与健康度（失败率/延迟）评估与动态调度
    - [ ] 首条可信保留与跨源合并（同事件聚合、相似度阈值）
- [x] Normalize：字段抽取、HTML 去噪、语言判定、质量统计
- [ ] EntityResolver：证券字典加载、规则匹配、LLM 辅助消歧、置信度与证据索引
  - [x] 证券字典加载与别名规则匹配（`config/entities.yaml`）
  - [ ] LLM 消歧与证据索引、置信度输出与复核阈值
  - 匹配：规则精确/模糊，低置信调用 LLM 消歧（可禁用）
  - 证据：句级索引与命中片段回填；输出 confidence 并阈值化入复核
  - DoD：样本集合输出稳定置信与证据；<0.70 自动入复核队列
  - 依赖：LLM 适配器、缓存、Persistence
- [ ] Tagger：事件类型与情绪（规则→LLM 回退）、参数化温度/超时、缓存键
  - 参数化：温度/超时/重试/代理可配，失败路径降级到规则
  - 缓存键：content_hash+prompt_version
  - DoD：同一 content_hash 命中缓存；失败标注 degraded=true 与原因
  - 依赖：LLM、缓存、可观测（命中率、耗时）
- [x] Scorer：各维度打分、权重聚合、行业多样性去偏、阈值与“无推荐”
  - 特征：相关性、情绪强度、事件权重、时效衰减、来源可信度
  - 聚合：权重加和（v1.0.0）；输出 aggregate_score 与各维度贡献
  - 多样性去偏（M2）：行业约束与惩罚项，记录前后差异
  - 阈值与无推荐：min_aggregate_score；不足返回 reason
  - DoD：Top-N 稳定产出；（M2）去偏对 Top-N 有可解释差异记录
  - 依赖：配置权重、数据字典
  - 多维评分（核心功能#3）细化：
    - [ ] 置信区间与时效衰减曲线参数化（半衰期、窗口）
    - [ ] 源可信度动态更新（基于过去 N 次表现）
    - [ ] 反作弊信号（重复转述/标题党惩罚）
- [x] Planner：规则生成、参数缺失回退、内部校验、联网 Enricher、输出 JSON+Markdown
  - 校验：一致性与可执行性，失败阻断并返回修复建议
  - 联网 Enricher（M2）：公告/研报/监管动态检索，更新证据与置信
  - 输出：plan_json 与 plan_md，记录 validation 与版本
  - DoD：plan_json 可机读校验通过；（M2）联网增强能影响 confidence_delta
  - 依赖：Scorer、外部检索、Persistence
  - AI 方案生成（核心功能#5）：
    - [ ] DeepSeek 提示词模板与版本控制（计划生成/应急预案）
    - [ ] 生成买入/卖出价位建议（含区间与置信）、仓位/风控参数
    - [ ] 应急方案≥2 套（缩仓/延迟/撤单/对冲）与触发条件
    - [ ] 规则 Planner 联合校验与不可执行原因报告
- [ ] IntradayWatcher：轮询、触发条件、替代策略（缩仓/撤单/延迟/对冲）、通知集成
  - 轮询：交易时段内每 N 分钟；失败退避与最终告警
  - 触发：负面舆情/监管/异常波动；重评与替代策略（缩仓/撤单/延迟/对冲）
  - 通知：与告警系统集成（渠道可配）
  - DoD：触发到输出≤5 分钟；事件审计可追溯
  - 依赖：可观测、Planner、Scorer
- [x] Persistence：各模型表与索引、版本与审计字段、复核与重试队列
  - 表与索引：raw_news、normalized_news、news_entities、news_events、sentiment、stock_scores、top_candidates、trade_plans、review_queue、retry_queue、llm_cache
  - 审计：版本与创建/更新时间、来源追溯字段；关键列索引与唯一约束
  - DoD：迁移脚本可回滚；读写路径贯通并含最小示例数据
- [ ] Config & Secrets：分层配置、热更新（谨慎）、代理与密钥安全读取
  - 分层配置：默认→环境→工作区覆盖；必要字段校验与错误提示
  - 代理与密钥：HTTP(S) 代理统一；LLM_API_KEY 安全读取；脱敏日志
  - 热更新（M2）：受控开关与白名单字段，失败回滚
  - DoD：启动时校验通过；（M2）热更新生效且有审计记录
- [ ] AI 问答服务（DeepSeek，核心功能#1）
  - [x] DeepSeek 客户端适配器：密钥/代理/超时/重试；Chat/Completions（非流式已通）
  - [x] 接口：/v1/ai/ask（一次问答，非流式）
  - [x] 接口：/v1/ai/chat（会话，流式优先）
  - [ ] Prompt/系统指令模板与版本；温度/最大 Token 参数化；函数调用（可选）
  - [ ] 缓存：问答键指纹（normalized prompt+context+version），TTL 与命中率指标
  - [ ] 安全与成本：长度/速率限制；敏感词/越权请求拦截；重试与熔断
  - DoD：本地与沙盒 Key 均可运行；端到端流式输出稳定（>99% 无断流）；有结构化错误
- [ ] 市场数据（核心功能#4 部分）
  - [ ] 价格客户端：实时/延迟价格与分时/日线；多提供方抽象；单位/时区统一
  - [ ] 缓存：快照 TTL/分时切片；批量拉取与降采样
  - [ ] 相关新闻检索：按证券与时间窗聚合；利好/利空聚合与示例片段
  - DoD：单支/多支股票查询稳定；错误降级与回退源可用
- [ ] 检索与增强（核心功能#4 补充）
  - [ ] NewsSearch：关键词/实体检索；布尔/时间窗过滤；结果去重
  - [ ] Enricher：为 AI/Planner 汇总证据（要点/链接/时间线）并产出结构化上下文
  - DoD：在 Top-N 与 AI 问答中可复用同一上下文接口

### 可观测性
- [ ] 指标埋点：成功率、耗时分位、LLM 成功/延迟、缓存命中；结构化日志；SLA 时间点事件
  - [x] 基础运行指标与延迟分位（近期 N 次、P50/P90/P99）
  - [ ] LLM 成功率/延迟、缓存命中率、SLA 时间点事件与结构化日志
  - 指标清单：抓取成功率、去重率、置信度分布、LLM 成功率与延迟、缓存命中率、304 命中率、重试计数
  - 日志字段：task_id、stage、source、error_code、retriable、dedupe_key
  - 流式与对话：
    - [ ] 流式分段耗时、首字节时间（TTFT）、断流计数、重连
    - [ ] 会话命中率/成本与上下文长度分布
  - [x] 端点：GET `/v1/metrics/per-source`、GET `/v1/health?verbose=1`
- [ ] 告警规则：抓取成功率<99%、源连续失败熔断、LLM 异常、延迟超标
  - [x] 已实现：overall_error_rate_high、fetch_success_rate_low、latency_p90_high、source_consecutive_failures
  - [x] 端点：GET `/v1/alerts`
  - [ ] LLM 异常与成本阈值告警
  - DoD：核心指标在 `/v1/metrics` 暴露；至少 3 条关键告警在灰度演练中触发并恢复

### 数据 / 分析
- [ ] 权重版本化与历史校准
  - 流程：离线 K 折/网格或贝叶斯；Platt scaling 标定；多市场/行业分桶
  - 上线：灰度 A/B（weight_version），上线验收基于胜率/回撤/命中率
- [ ] Top-N/Top-1 结果对比分析与回测接口（如适配）

### QA
- [ ] 用例集：边界与异常
- [ ] 端到端（E2E）测试流：含代理、缓存、回退与熔断
  - DoD：E2E 稳定通过；错误结构一致；包含代理/缓存/回退/熔断路径
- [ ] 性能与限流验证：速率限制、并发与重试行为
- [ ] 回归范围
- [ ] 覆盖率阈值：CI 行 70% / 分支 60%
- [ ] 桩与夹具：LLM Mock（可控延迟/失败率/返回），新闻源录制回放
- [ ] 缓存命中 A/B
- [ ] AI 流式问答 E2E：
  - [ ] 断流/重试/续传；上下文注入长度边界；提示词版本回归
  - [ ] 方案生成一致性快照比对（关键信息字段）
- [ ] 市场数据与检索 E2E：
  - [ ] 价格/分时对齐校验；相关新闻利好/利空聚合正确性

### 运维
- [ ] 配置与开关管理
  - 开关：市场/板块灰度，按 weight_version A/B
- [ ] 灰度计划（市场/板块）
  - DoD：灰度切换无感
- [ ] 回滚与补偿
  - 失败批次重放、配置回滚、规则/权重回退
  - DoD：回滚剧本 1 次演练通过
- [ ] 监控面板
  - 关键指标与告警总览；SLA 报表（可选） 