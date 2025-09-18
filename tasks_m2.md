# M2 任务清单（稳定性与联网增强）
> 注意：权威任务清单请见 `/.kiro/specs/preopen-news-driven-plan/tasks.md`。此文件仅为 M2 里程碑的工作视图。

## 目标
- 在 M1 的可用基础上，提高稳定性、可观测性与多源联网能力，减少去偏并完善回退机制。

## 范围
- **联网增强**
  - [x] 多源并发抓取（RSS/HTTP JSON），增加 `headers/retry/qps/concurrency` 支持（已有 RSS 基础）
  - [ ] 条件请求与缓存（ETag/Last-Modified）
  - [ ] 失败回退与指数退避重试（按源粒度记录 error 与 fallback_used）
- **去偏与多样性**
  - [x] 多样性约束（行业/来源配额）基础实现（`select_top_n(sector_cap_pct)`）
  - [x] 记录 pre/post 分布与 `sector_cap_pct` 到运行指标（`metrics.diversity`）
  - [ ] 权重版本化与变更日志（weight_version 配置化输出到分数表）
- **可观测性/运维**
  - [x] 结构化 JSON 日志（任务/阶段，环境变量 `PREOPEN_JSON_LOGS` 打开）
  - [x] 指标：成功率、耗时分位（P50/P90/P99）、每源抓取明细 `/v1/metrics/per-source`
  - [x] LLM：调用计数/成功率/延迟与缓存命中（`/v1/metrics.llm`）
  - [ ] SLA 时间点事件（T-45/T-35/T-30 命中率）
- **流水线与复核**
  - [x] 作业控制：`/v1/pipeline/preopen/retry|jobs|job|cancel`（已具备）
  - [ ] 人工复核占位（低置信实体与计划校验失败入队）
  - [ ] 盘中监控（IntradayWatcher）与触发策略（缩仓/撤单/延迟/对冲）
- **Tagger 与 Enricher**
  - [x] Tagger：LLM 优先 + 规则回退，缓存键 `content_hash+prompt_version`，可通过 `llm.tagger_enabled` 控制
  - [x] LLM 缓存：`app/llm_cache.py`（TTL，可观测 stats）
  - [x] Enricher：占位（`app/enricher.py`），可由 `planner.enricher_enabled` 控制（当前为 no-op）
  - [ ] Prompt & 提示工程：函数调用 JSON 契约、错误恢复与裁剪
- **测试与文档**
  - [ ] 端到端集成测试（fixtures → plan），含缓存命中/LLM 失败回退用例
  - [ ] README 更新（配置项、指标项说明）

## 交付标准（DoD）
- [ ] 在不依赖外网的情况下，端到端通过；开启联网后具备稳定的增益与可回退策略。
- [ ] 指标与日志可用于问题定位；关键告警可运行（至少 3 条）。
- [ ] 新增代码通过 `pytest`，关键路径具备集成测试，覆盖率达标。

## 任务拆分与负责人（示例）
- 条件请求与缓存（ETag/LM）：Owner: TBD，Estimate: 2d
- LLM Tagger 提示与解析稳健性：Owner: TBD，Estimate: 2d
- IntradayWatcher & 策略触发：Owner: TBD，Estimate: 3d
- 复核队列与管理端点：Owner: TBD，Estimate: 2d
- 集成测试与文档：Owner: TBD, Estimate: 2d 