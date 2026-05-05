# CLAUDE.md — 執行入口

> 版本：v1.0 | 專案：ScriptFlow 短影音變現操盤台

---

## 真相優先級

1. **需求文件（不能改）** — 產品需求、功能定義
2. **邊界規則（不能破）** — 下方硬紅線 + rules/ 內所有規則
3. **其他規範（遵守，有疑問先提出再動手）**

---

## 開工前必讀順序

**每次開工必讀（永遠載入）：**
1. 本文件
2. `@docs/spec-user.md` — 產品需求
3. `@docs/spec-developer.md` — 開發規格

**按任務按需讀（當下需要才載入）：**
- `@docs/architecture.md` — 做架構決策、新增模組時
- `@docs/dev-order.md` — 確認施工順序、開始新 Phase 時
- `@docs/engineering-guardrails.md` — 跨模組互動、重構時
- `@docs/setup-checklist.md` — 環境設定、部署時
- `@docs/backend-standards.md` — 寫後端程式時
- `@docs/frontend-standards.md` — 寫前端程式時
- `@docs/performance-memory-standards.md` — 效能相關任務時
- `@docs/security-standards.md` — 認證、資料存取、外部服務時
- `@docs/vibecoding-safety-rules.md` — AI 產出程式碼後自我檢查時

**自動載入（無需手動引用）：**
- `.claude/rules/` 下所有 rule 檔 — 依當前編輯的檔案路徑自動觸發

---

## 衝突處理

**規則數值或嚴格程度衝突（自動處理）：**
若兩份 rule 檔對同一事項有不同數值或標準，**以較嚴格的那個為準**，不需要等待確認。

**規則方向衝突（需確認）：**
```
⚠️ 衝突：[文件A] vs [文件B]
衝突點：...
不自行解決，請確認後繼續
```

---

## 硬紅線

- [禁止] hardcode 任何 secret、API key、密碼
- [禁止] 信任 client 傳來的權限欄位（role、isAdmin）
- [禁止] 未驗證所有權直接操作資源
- [禁止] 拼接 SQL 字串，一律用 ORM 或參數化查詢
- [禁止] 回傳完整 DB 物件，一律用 response schema 過濾
- [禁止] 將 stack trace 或內部錯誤暴露給 client
- [禁止] 管理操作不留稽核紀錄
- [禁止] ScriptService 直接讀取 Firestore candidates collection（須透過 CandidateService）
- [禁止] 任何 service 直接 import 外部服務 SDK（如 openai、google.cloud），只能透過 infra/ 層
- [禁止] 前端 JS 直接呼叫 OpenAI API 或爬取服務
- [禁止] LLM 輸出用 innerHTML 渲染（須用 textContent 或 DOMPurify）
- [禁止] 生產環境開啟 FastAPI /docs、/redoc 或 debug=True

---

## 技術棧速查

| 層級 | 技術 |
|---|---|
| 前端 | HTML + CSS + JS（dashboard.js, tracking.js, api.js, common.js） |
| 後端 | Python 3.12 + FastAPI |
| 資料庫 | Firestore（candidates, scripts, tracking, brand_dna collections） |
| 排程 | APScheduler（09:00 GMT+8 每日爬取） |
| 部署 | GCP Cloud Run |
| AI | OpenAI GPT-5-mini（文字生成） |
| 圖像 | OpenAI gpt-image-1（分鏡示意圖，與文字共用同一把 API key） |
| 爬取 | 爬取輔助服務（小紅書 / 抖音 / Threads） |

---

## 檔案存放規則

**後端：**
```
main.py                        ← FastAPI 啟動點、DI 組裝
scheduler.py                   ← APScheduler 排程
modules/{功能}/route.py        ← 入口層（只呼叫 service）
modules/{功能}/service.py      ← 業務邏輯層
domain/                        ← 跨模組共用規則（不依賴任何層）
infra/                         ← 外部服務封裝（Firestore、OpenAI API 等）
```

**前端：**
```
static/js/api.js               ← 所有 fetch 唯一入口
static/js/dashboard.js         ← 主操作台頁面邏輯
static/js/tracking.js          ← 成效追蹤頁面邏輯
static/js/common.js            ← 跨頁共用（Tab 切換、排程狀態）
static/css/main.css            ← 全站樣式
static/index.html              ← 主頁面
```

**禁止：**
- 不可在 `static/js/api.js` 以外的地方寫 `fetch`
- 不可在 `modules/` 之外新增 route 或 service
- CSS 和 JS 不可內嵌在 HTML `<style>` 或 `<script>` 標籤

---

## 變更隔離原則

- 每個 service 只操作自己的 Firestore collection
- 跨模組資料只透過 service 的公開函式傳遞
- 修改 domain/ 的設定（prompt、禁詞、分類）不需要改 service 邏輯
- 換外部服務供應商只改對應 infra/ 檔案

---

## 工作原則

**寫 code 時**
- 對應 rule 存在就必須遵守，不跳過
- 不修改任務範圍外的程式碼
- 新增套件前告知，等確認再加

**修 bug 時**
- 只修有問題的地方，不順手重構
- 修改前說明根因，確認方向再動手

---

## 交付前檢查

架構品質：
- [ ] lint 通過
- [ ] 相關測試通過
- [ ] 新功能有對應測試
- [ ] 未修改任務範圍外的程式碼
- [ ] 無 hardcode secret
- [ ] response 已用 schema 過濾

安全自檢（見 `docs/vibecoding-safety-rules.md`）：
- [ ] OpenAI API Key 不在前端 JS 或程式碼中
- [ ] LLM 輸出用 textContent 渲染
- [ ] /docs、/redoc 生產環境關閉
- [ ] debug=False 確認

---

## 文件索引

### 專案規格

| 文件 | 用途 |
|---|---|
| `@docs/spec-user.md` | 產品需求 |
| `@docs/spec-developer.md` | 開發規格 |
| `@docs/architecture.md` | 系統架構 |

### 開發參考

| 文件 | 用途 |
|---|---|
| `@docs/dev-order.md` | 開發順序（Phase 0-7） |
| `@docs/engineering-guardrails.md` | 工程邊界 |
| `@docs/setup-checklist.md` | 環境設定 |

### 標準規範

| 文件 | 用途 |
|---|---|
| `@docs/backend-standards.md` | 後端標準 |
| `@docs/frontend-standards.md` | 前端標準 |
| `@docs/performance-memory-standards.md` | 效能與記憶體 |
| `@docs/security-standards.md` | 資安標準 |
| `@docs/vibecoding-safety-rules.md` | Vibe Coding 安全規則 |

### 全域 Rules（自動觸發）

| 文件 | 用途 |
|---|---|
| `@.claude/rules/rule-auth.md` | 認證、授權、JWT、OAuth |
| `@.claude/rules/rule-api.md` | API 安全、注入防護 |
| `@.claude/rules/rule-cloud.md` | GCP、CORS、HTTP 標頭 |
| `@.claude/rules/rule-ai-llm.md` | AI / LLM 安全 |
| `@.claude/rules/rule-vibecoding-safety.md` | Vibe Coding 安全自檢 |
| `@.claude/rules/rule-api-design.md` | API 設計規範 |
| `@.claude/rules/rule-backend.md` | FastAPI 後端架構 |
| `@.claude/rules/rule-frontend.md` | HTML / CSS / JS 規範 |
| `@.claude/rules/rule-database.md` | Firestore 規範 |
| `@.claude/rules/rule-module-isolation.md` | 模組隔離、變更隔離 |
