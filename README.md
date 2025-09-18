# Preopen News Driven Plan — Minimal API

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Development
- Install dev tools:
```bash
python -m pip install -U pip
pip install -r requirements.txt
# Optional: ruff, mypy, pytest-cov for local checks
python -m pip install ruff mypy pytest-cov
```
- Lint and type check:
```bash
ruff check .
mypy .
```
- Run tests with coverage:
```bash
pytest -q --cov=app --cov-config=.coveragerc --cov-report=term-missing
```

## Endpoints
- POST `/v1/pipeline/preopen/run`
- GET `/v1/pipeline/preopen/status?task_id=...`
- GET `/v1/news/topn?market=SSE[&as_of=ISO8601&n=5][&group_by=sector|source]`
- GET `/v1/plan/latest?trade_date=YYYY-MM-DD&market=SSE`
- POST `/v1/plan/validate`
- GET `/v1/health`

## Storage
- Default SQLite path: `data/app.db`
- To override, set `storage.db_path` in your YAML config and point `APP_CONFIG_PATH` to it.

## HTTP cache (RSS conditional requests)
- RSS adapter persists ETag/Last-Modified cache to `data/http_cache.json` by default.
- Override path via environment variable `APP_CACHE_PATH`.
- On 200 responses, headers are captured and saved; on 304, the adapter returns an empty list.

## Example
```bash
curl -s -X POST http://localhost:8000/v1/pipeline/preopen/run \
  -H 'Content-Type: application/json' \
  -d '{"market":"SSE","trade_date":"2025-09-10","dedupe_key":"SSE_2025-09-10"}'
``` 

## Demo data
```bash
python scripts/seed_demo_data.py --trade-date 2025-09-10 --market SSE --n 3
```
This seeds minimal rows into the default SQLite DB at `data/app.db`.

## JSON logging (optional)
Set `PREOPEN_JSON_LOGS=1` to emit JSON logs to stdout.

```bash
# Windows PowerShell
$env:PREOPEN_JSON_LOGS=1; python main.py

# bash
PREOPEN_JSON_LOGS=1 python main.py
```

## Health with metrics (optional)
- Basic: `GET /v1/health` → `{ "status": "ok" }`
- Verbose: `GET /v1/health?verbose=1` → includes last run metrics snapshot. 

## Entity dictionary (optional)
Create `config/entities.yaml` to improve symbol/sector matching during normalization.

```yaml
symbols:
  - exchange: SSE
    code: "600519"
    name: Kweichow Moutai
    aliases: ["Kweichow Moutai", "Moutai", "贵州茅台", "茅台", "600519"]
    sectors: ["Beverages", "Consumer"]
```
If absent, the pipeline will still work, defaulting to heuristic symbol inference in responses. 

### `/v1/news/topn`

Query params:
- `market` (required)
- `as_of` (optional ISO8601). Date part selects the trade date.
- `n` (optional, default 5)
- `group_by` (optional, default `sector`). One of `sector` or `source`. Determines `group_key` returned for each item.

Response shape:
```json
{
  "as_of": "2025-09-10T10:00:00Z",
  "market": "SSE",
  "weight_version": "v1.0.0",
  "diversity": { "sector_cap_pct": 60 },
  "topn": [
    {
      "symbol": { "exchange": "SSE", "code": "600000" },
      "aggregate_score": 0.91,
      "scores": { "relevance": 0.8, "recency": 0.9 },
      "evidence": { "news_ids": ["123"], "events": ["earnings"], "sentiment": {"overall": "positive"} },
      "sectors": ["Banks"],
      "source_id": "rss_main",
      "rank": 1,
      "group_key": "Banks"
    }
  ]
}
```

Notes:
- When `group_by=sector`, `group_key` is the first sector (if present); when `group_by=source`, it is the `source_id`.
- If sector/source is missing, `group_key` falls back to the item title.

### Configuration

`config/config.yaml` supports diversity hints for clients and scoring knobs:

```yaml
scoring:
  weights:
    relevance: 0.25
    sentiment_strength: 0.20
    event_weight: 0.25
    recency: 0.20
    source_trust: 0.10
  # Preferred threshold for Top-N filtering. If absent, falls back to score_threshold (default 0.0)
  # min_aggregate_score: 0.62
  # Historical weights version surfaced in /v1/news/topn and stored with scores
  # version: v1.0.0
  diversity:
    sector_cap_pct: 60
```
- The API returns `weight_version` (from `scoring.version`, default `v1.0.0`).
- The pipeline filters candidates using `min_aggregate_score` when present; otherwise `score_threshold` (if provided), otherwise no threshold. 

## Docker

```bash
# Build
docker build -t preopen-api .

# Run
docker run --rm -it -p 8000:8000 -e PREOPEN_JSON_LOGS=1 \
  -v %cd%/data:/app/data preopen-api
```

## Docker Compose

```bash
docker compose up --build
```

Notes:
- Data is persisted to the host `./data` directory by default.
- Override config via `APP_CONFIG_PATH` if you provide a custom YAML. 

### Configuration file

```bash
# Copy example and adjust
copy config\config.example.yaml config\config.yaml  # Windows PowerShell
# 或者 Linux/macOS: cp config/config.example.yaml config/config.yaml
```

- Compose 已将宿主机 `./config` 挂载到容器 `/app/config`（只读）。
- 如需使用自定义路径，可设置 `APP_CONFIG_PATH` 指向你的 YAML 文件。

### Compose 环境变量

在仓库根目录创建 `.env`（Compose 会自动加载）：

```env
# 网络
HOST=0.0.0.0
PORT=8000

# 配置文件路径（容器内）
APP_CONFIG_PATH=/app/config/config.yaml

# 可选：启用 JSON 日志
PREOPEN_JSON_LOGS=1

# 可选：禁用计划任务（开发/本地）
# DISABLE_SCHEDULER=1
```

- Compose 会自动加载同目录下的 `.env`，覆盖 `HOST`、`PORT`、`APP_CONFIG_PATH` 等配置。 

## M2 additions
- LLM tagger (optional): set `llm.tagger_enabled: true`, with `llm.prompt_version`, `llm.cache_ttl_minutes` controlling cache.
- Plan enricher stub (optional): set `planner.enricher_enabled: true` (no-op by default).
- Metrics now include LLM counters and cache stats in `/v1/metrics` and per-source breakdown in `/v1/metrics/per-source`. 
