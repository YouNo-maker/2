# M1 任务清单（最小可用版）
> 注意：权威任务清单请见 `/.kiro/specs/preopen-news-driven-plan/tasks.md`。此文件仅为 M1 里程碑的摘要清单。

> 目标：在不开启联网增强与 LLM 的前提下，交付可用的“新闻→Top-N→计划”同步流水线与查询接口，满足 T-45/T-35/T-30 的基本时序与最小可观测。

## 1. API 层
- [x] 新增 `GET /v1/news/topn?trade_date=YYYY-MM-DD&market=SSE`
  - 返回：Top-N 候选（含分数、维度分项、来源、摘要）
  - 错误码：404（当日无数据）、500（内部错误）
- [x] 新增 `GET /v1/plan/latest?trade_date=YYYY-MM-DD&market=SSE`
  - 返回：当日最新生成的计划（入场/止损/止盈/仓位/执行窗口/备注）
- [x] 新增 `POST /v1/plan/validate`
  - 入参：计划 JSON
  - 返回：校验结果（是否通过、失败项列表）

验收标准：
- [x] FastAPI 文档展示 3 个新端点，示例可调用，状态码与返回结构稳定。
- [x] 增加对应单测覆盖（happy path + 404）。

## 2. 数据模型与存储（SQLite）
- [x] 新建 `app/storage`，引入 SQLAlchemy/SQLModel（SQLite 文件）
- [x] 表结构（最小集）：
  - [x] `raw_news(id, source_id, url, title, published_at, fetched_at, hash, dedup_key, lang, raw)`
  - [x] `normalized_news(id, raw_id, source_id, url, title, text, published_at, quality, entities_json)`
  - [x] `scores(id, normalized_id, relevance, sentiment_strength, event_weight, recency, source_trust, total, version, created_at)`
  - [x] `top_candidates(id, trade_date, market, normalized_id, rank, total_score, created_at)`
  - [x] `trade_plans(id, trade_date, market, plan_json, plan_md, created_at)`
- [x] 迁移/初始化：启动时自动建表；提供 `make reset-db` 脚本（可选）。

验收标准：
- [x] 本地运行可持久化插入/查询，支持并发读。

## 3. 最小流水线（同步）
- [x] Source 适配器（RSS 或 HTTP JSON，取 `config.yaml.sources[0]`）
  - [x] 支持 qps 与重试参数（简单 sleep + 尝试上限）
  - [x] 去重：`url`/`hash`/`dedup_key`，忽略重复
- [x] Normalize
  - [x] HTML 去噪、生成简要 `text`、质量评分（长度/源可信度简单规则）
  - [x] 语言判定（可选，默认 `en`/`zh` 推断失败时标注 `unknown`）
- [x] Rule-based 标签与实体
  - [x] 简单词典（本地 `config/entities.yaml` 可选）匹配主体与板块标签
- [x] Scoring（规则化）
  - [x] 维度：relevance/sentiment_strength/event_weight/recency/source_trust，对应 `config.scoring.weights`
  - [x] 聚合：加权求和，保留版本号 `v1`
- [x] Top-N 选取
  - [x] N 由 `config.preopen.topn_output_minutes_before_open` 不直接决定，固定取前 10；当无候选时返回空集合
- [x] Planner（最小）
  - [x] 规则：根据分数阈值与标签映射到计划条目；生成 `plan.json` 与 `plan.md`
  - [x] 校验：字段完整性、数值范围、风险限额（如单标的最大仓位 10%）

验收标准：
- [x] 通过 `POST /v1/pipeline/preopen/run` 在本地可触发同步执行，T-45/T-35/T-30 仅用于元数据，不阻塞执行。
- [x] 运行后：`raw_news/normalized_news/scores/top_candidates/trade_plans` 有数据，`/news/topn`、`/plan/latest` 可查询。

## 4. 配置与参数
- [x] 扩展 `config/config.yaml`
  - [x] `sources[].type/rss/headers/retry/qps/concurrency`
  - [x] `scoring.weights` 校准默认值已存在；新增 `score_threshold`
- [x] `app/config.py` 读取并兼容默认值；新增 `get_db_path()`（默认 `./data/app.db`）

验收标准：
- [x] 缺项时使用默认值；错误配置给出清晰异常。

## 5. 可观测与日志
- [x] 结构化日志（`structlog` 或标准 logging JSON 格式）
- [x] 关键指标（内存计数即可）：抓取成功/失败数、去重率、入库耗时、打分耗时、Top-N 数量
- [x] 在 `GET /v1/health` 增加简要指标字段（非破坏性，可选）

验收标准：
- [ ] 控制台输出结构化日志；单测断言关键日志段落（可选）。

## 6. 测试
- [x] 单元测试：
  - [ ] 正常触发流水线并产出数据
  - [x] `/news/topn` 空数据返回 404
  - [x] `/plan/latest` 空数据返回 404
  - [x] `POST /v1/plan/validate` 基础校验用例
- [ ] 集成测试：
  - [ ] 从模拟源（本地 JSON/RSS fixture）流到计划生成的端到端

## 7. 文档与脚本
- [x] 更新 `README.md`：新增端点、运行步骤、SQLite 路径、示例 curl
- [x] 新增 `docs/pipeline_m1.md`：架构图、表结构、数据流说明
- [x] 可选：`scripts/seed_demo_data.py` 用于本地演示

---

### 交付标准（Definition of Done）
- [x] 本地可运行，端到端从源到计划生效；关键接口均返回 200/404 合理状态。
- [x] 所有新增代码通过 `pytest`；CI 可在本地通过（如暂无 CI，可留本地命令）。
- [x] 无需 LLM 与外网也能生成非空 Top-N（基于本地 fixtures）。
- [x] 代码与配置清晰、可读，包含必要注释与错误信息。 