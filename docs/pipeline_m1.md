# Pipeline M1 — Architecture, Storage, and Data Flow

## Overview
- Scope: Minimal offline-capable pre-open pipeline: fetch → normalize → score → select Top-N → generate plan.
- Markets: `SSE` by default, time anchors at T-45 / T-35 / T-30 relative to local 09:30.
- API: `POST /v1/pipeline/preopen/run`, `GET /v1/pipeline/preopen/status`, `GET /v1/news/topn`, `GET /v1/plan/latest`, `POST /v1/plan/validate`, `GET /v1/health`.

## Storage
- Engine: SQLite (default path `data/app.db`, overridable via config `storage.db_path` and `APP_CONFIG_PATH`).
- ORM: SQLModel.

### Tables (minimal set)
- `RawNews` (`raw_news`)
  - id, source_id, url, title, published_at, fetched_at, hash, dedup_key, lang, raw
- `NormalizedNews` (`normalized_news`)
  - id, raw_id, source_id, url, title, text, published_at, quality, entities_json
- `Score` (`scores`)
  - id, normalized_id, relevance, sentiment_strength, event_weight, recency, source_trust, total, version, created_at
- `TopCandidate` (`top_candidates`)
  - id, trade_date, market, normalized_id, rank, total_score, title, url, published_at, components_json, created_at
- `TradePlan` (`trade_plans`)
  - id, trade_date, market, plan_json (JSON), plan_md, created_at

## Configuration
- File: `config/config.yaml` (override with env `APP_CONFIG_PATH`).
- Keys used in M1:
  - `preopen.first_fetch_minutes_before_open` (default 60)
  - `preopen.topn_output_minutes_before_open` (default 35)
  - `preopen.plan_output_minutes_before_open` (default 30)
  - `sources[]` (first source used; RSS supported; offline demo fallback)
  - `scoring.weights`
  - `scoring.min_aggregate_score` (preferred threshold; fallback to `scoring.score_threshold` if absent)
  - `scoring.version` (weights version surfaced in responses and persisted with scores; default `v1.0.0`)
  - `storage.db_path` (optional)
- Sources: `config.yaml.sources[0]`
- Supports RSS with fields: `id`, `type: rss`, `url`, `limit`, optional `timeout`, `retries`, `qps`

## Data Flow
1. Trigger: `POST /v1/pipeline/preopen/run`
   - Returns 202 with `task_id` and computed deadlines: `fetch/topn/plan` and their ISO times.
2. Fetch (Ingestion)
   - Reads first configured source (`sources[0]`), attempts RSS; on failure uses offline demo items.
   - Deduplication by `url`/`title` key.
   - Persist `raw_news` (minimal fields).
3. Normalize
   - Title → brief text; compute length-based `quality` score.
   - Persist to `normalized_news` with optional `entities_json`.
4. Score
   - Compute components: relevance (from quality), sentiment_strength/event_weight (rule-based keywords), recency (time decay), source_trust.
   - Aggregate with `scoring.weights` → `total`; store per-item in `scores`.
5. Select Top-N
   - Greedy diversity by `sector` if present, otherwise `source_id`.
   - Threshold: prefer `scoring.min_aggregate_score`; fallback to `scoring.score_threshold` (default 0.0).
   - N=10. Persist ranked results to `top_candidates` with `components_json`.
6. Plan
   - Generate minimal plan from Top-1; persist `plan_json`/`plan_md` to `trade_plans`.

## Query and Validation
- `GET /v1/news/topn?trade_date=&market=&limit=` → returns ranked candidates with components and timestamps.
  - Response includes `weight_version` (from `scoring.version`, default `v1.0.0`) and optional `diversity.sector_cap_pct` from config.
- `GET /v1/plan/latest?trade_date=&market=` → returns latest plan for the day.
- `POST /v1/plan/validate` → validates required fields, direction ordering, and risk-reward ≥ 1.5.

## Deadlines and Time Model
- Local-naive open time 09:30; compute T-45/T-35/T-30 ISO timestamps for visibility only (non-blocking in M1).

## Observability (M1 minimal)
- Console logs at INFO level (set `PREOPEN_JSON_LOGS=1` for JSON lines).
- Suggested M2: structured JSON logs, counters (ingest_ok/fail, dedupe_rate, persist_ms, score_ms, topn_count), basic alerts. 