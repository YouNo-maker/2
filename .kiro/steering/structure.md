# 專案結構與慣例（Project Structure）

## 根目錄組織（Root Organization）
- `app/`：應用程式程式碼（FastAPI、Pipeline、Storage、Models）
- `config/`：預設設定檔（`config.yaml`）
- `scripts/`：腳本（如 `seed_demo_data.py`）
- `README.md`：啟動與端點說明
- `main.py`：Uvicorn 入口（啟動 `app/server.py`）
- `.kiro/steering/`：本目錄（Steering 文件）
- `.kiro/specs/`：功能規格（依 feature 建立子目錄）

## Steering 檔案（Steering Files）
- 核心檔案（Always Included）：
  - `product.md`：產品脈絡與價值主張
  - `tech.md`：技術堆疊、工具與常用指令
  - `structure.md`：目錄結構、命名慣例與引用規則
  - `preopen-news-driven-plan.md`：開盤前新聞驅動計劃的 Steering（預設載入）
- 自訂檔案（Custom Steering）：可依主題新增；使用 `@filename.md` 於其他 Steering/Specs 引用

## Specs 目錄（.kiro/specs/）
- 路徑：`.kiro/specs/[feature-name]/`
- 典型檔案：
  - `requirements.md`：需求（EARS 格式）
  - `design.md`：技術設計
  - `spec-tasks.md`：落地實作任務（與實作映射文件 `spec-impl-*.md` 對照）
  - `spec-impl-*.md`：規格與實作映射快照（固定版本）

## 命名與組織（Conventions）
- 檔案內容以清楚的章節與項目列表呈現，避免過度冗長
- 每個 Steering 檔案聚焦單一領域（Single Responsibility）
- 採「增量更新」原則：新增為主、若需廢止以 [DEPRECATED] 註記

## 引用與載入（Reference & Inclusion）
- Always Included：`product.md`、`tech.md`、`structure.md`、`preopen-news-driven-plan.md`
- Conditional/Manual：自訂 Steering 以 `@filename.md` 引用；Specs 檔案可互相引用以形成上下文 