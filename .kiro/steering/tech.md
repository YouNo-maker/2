# 技術堆疊與開發環境（Technology Stack）

## 架構概覽（Architecture）
- 文檔驅動：以 Markdown 檔案定義 Steering（`.kiro/steering/`）與 Specs（`.kiro/specs/`）
- 指令介面：
  - Cursor 指令位於 `.cursor/commands/kiro/`
  - Claude Code 指令位於 `.claude/commands/kiro/`
- 核心 Steering（預設 Always Included）：`product.md`、`tech.md`、`structure.md`、`preopen-news-driven-plan.md`

## 開發環境（Development Environment）
- 主要工具：Cursor、Claude Code
- 版本控制：Git（建議）
- 文件格式：Markdown（UTF-8）

## 常用指令（Common Commands）
- Steering 管理：
  - `/kiro:steering`：建立/更新核心 Steering 文件
  - `/kiro:steering-custom`：為特定情境建立自訂 Steering
- 規格生命週期：
  - `/kiro:spec-init [description]`
  - `/kiro:spec-requirements [feature]`
  - `/kiro:spec-design [feature]`
  - `/kiro:spec-tasks [feature]`
  - `/kiro:spec-status [feature]`
  - （若有）`/kiro:spec-impl [feature]`
- 驗證/審核：
  - `validate-gap`：需求到設計的落差檢查
  - `validate-design`：設計一致性與完整性檢查

## 環境變數（Environment Variables）
- `APP_CONFIG_PATH`：指向 YAML 設定檔，預設 `config/config.yaml`
- `PREOPEN_JSON_LOGS`：設為 `1` 輸出 JSON 日誌到 stdout
- `HOST`：服務綁定位址，預設 `0.0.0.0`
- `PORT`：服務埠號，預設 `8000`

## 連接埠與服務（Ports & Services）
- 服務：FastAPI（`app/server.py`）以 Uvicorn 啟動（`main.py`）
- 預設埠：`8000`（可由 `PORT` 覆寫）
- 儲存：SQLite（`data/app.db`，可由配置 `storage.db_path` 覆寫） 