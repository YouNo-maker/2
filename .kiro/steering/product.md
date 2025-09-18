# 產品概觀（Product Overview）

## 產品敘述（What it is）
Kiro 式的 Spec-Driven Development，在 AI-DLC（AI Development Life Cycle）中以明確的規格與專案層級 steering 文件，規範 AI 協作的流程與輸出品質。此專案提供適用於 Cursor 與 Claude Code 的命令與結構，將 AI 助手納入可被審核、可被版本控管的工程流程。

## 核心能力（Core Features）
- Steering 文件管理：`/kiro:steering` 建立/更新 `.kiro/steering/` 下的核心文件（`product.md`、`tech.md`、`structure.md`、`preopen-news-driven-plan.md`）
- 自訂情境 Steering：`/kiro:steering-custom` 建立專用的自訂指引（Always/Conditional/Manual 載入）
- 規格生命週期：`/kiro:spec-init → spec-requirements → spec-design → spec-tasks → spec-impl`
- 規格狀態與驗證：`/kiro:spec-status`、`validate-gap`、`validate-design` 支援一致性檢查
- 多代理/多平台支援：`/.cursor/commands/kiro` 與 `/.claude/commands/kiro` 的雙套命令規格

## 主要情境（Target Use Cases）
- 需要以 AI 助手（Cursor、Claude Code）進行日常開發的專案/團隊
- 期望 AI 產出可重現、可審核、可沿用的工程產物
- 欲在多人協作中共享相同的「AI 導航知識（Steering）」與規格

## 主要價值（Key Value Proposition）
- 一致的脈絡：以 Always-included 的核心 Steering，提供穩定的專案背景
- 可審核的流程：規格分階段（Requirements/Design/Tasks/Impl）與人工審核節點
- 可被維護：Steering 與 Specs 均為檔案，隨版本控制維護與審查
- 跨工具一致：同一套方法論覆蓋 Cursor 與 Claude Code

## 關聯文件（Related Docs）
- `AGENTS.md`：AI-DLC 與開發流程說明
- `CLAUDE.md`：在 Claude Code 上的對應說明 

## 活动中的規格（Active Specs）
- `preopen-news-driven-plan`（开盘前新闻驱动的操盘计划）
  - 阶段: implemented；最近更新: 2025-09-11T00:30:00Z
  - 详情参见：`@.kiro/steering/preopen-news-driven-plan.md` 與 `@.kiro/specs/preopen-news-driven-plan/` 