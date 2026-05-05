> 版本：v1.0 | 日期：2026-05-04

# dev-order.md — ScriptFlow 開發順序

---

## 開發階段總覽

| Phase | 名稱 | 目標 | 預估 |
|---|---|---|---|
| 0 | 骨架建立 | 專案結構、環境、Firestore 初始化 | 0.5 天 |
| 1 | Domain 層 | 分類設定、合規禁詞、Prompt 樣板、業務規則 | 0.5 天 |
| 2 | Infra 核心 | Firestore + Session middleware | 1 天 |
| 3 | Infra 外部服務 | OpenAI 文字 API + OpenAI 圖像 API + 爬取輔助 | 2-3 天 |
| 4 | Service 層 | 五個 service 模組 | 3-4 天 |
| 5 | 入口層 + 排程 | 所有 route + APScheduler | 1.5 天 |
| 6 | 前端 | dashboard + tracking + api.js | 2-3 天 |
| 7 | 整合測試 + 部署 | E2E 驗證、Cloud Run 部署 | 1.5 天 |

---

## Phase 0：骨架建立

**目標：** 專案跑得起來、資料夾結構正確、Firestore collection 就緒

**交付物：**
- 完整資料夾結構（依 architecture.md 規格）
- `main.py` FastAPI 啟動點（只有 `/health`）
- `Dockerfile`
- Firestore 4 個 collection 初始化（candidates, scripts, tracking, brand_dna）
- `requirements.txt`

**完成條件：**
- `uvicorn main:app --reload` 啟動無錯誤
- `GET /health` 回傳 `{"status": "ok"}`
- Firestore 可讀寫（手動測試一筆 candidates document）

**阻塞條件：** GCP 專案、Firestore、Service Account 必須就緒（見 setup-checklist.md）

---

## Phase 1：Domain 層

**目標：** 所有跨模組共用規則到位，service 層可以直接 import

**交付物：**
- `domain/categories.py`：美妝 / 美食 / 髮品分類設定，含 B 軌允許類型清單
- `domain/compliance_rules.py`：三平台合規禁詞清單（按平台分）
- `domain/prompts.py`：腳本生成 Prompt 樣板（三版本各一個）
- `domain/rules.py`：`classify_funnel_role()`, `compute_similarity()`, `compute_purchase_intent_density()`

**完成條件：**
- 所有函式可單獨 import 測試，無外部依賴
- `classify_funnel_role("seed" / "pull" / "harvest")` 回傳正確標記
- `compute_similarity(content, category)` 回傳 0-1 浮點數

**阻塞條件：** 無（domain 無外部依賴，可第一個開始）

---

## Phase 2：Infra 核心

**目標：** Firestore 讀寫封裝完成，session middleware 就緒

**交付物：**
- `infra/firestore.py`：CRUD 封裝（candidates, scripts, tracking, brand_dna collection）
- `modules/auth/middleware.py`：session 驗證 middleware（所有路由套用）

**完成條件：**
- `infra/firestore.py` 可正確讀寫 candidates collection（整合測試）
- `GET /api/v1/health`（需驗證版）→ 無 session 回 401，有 session 回 200

**阻塞條件：**
- Phase 0 Firestore 初始化完成
- SESSION_SECRET 環境變數就緒

---

## Phase 3：Infra 外部服務

**目標：** 三個外部 client 可正常呼叫，錯誤處理與重試機制就緒

**交付物：**
- `infra/llm_client.py`：`generate_script()`, `scan_compliance()`, `compute_dna()`（OpenAI GPT-5-mini）
- `infra/image_gen_client.py`：`generate_storyboard_image()`（OpenAI gpt-image-1，失敗不拋例外，回傳 None）
- `infra/crawler_client.py`：`fetch_hot_content(platform, category, hours=24)`

**完成條件：**
- OpenAI API 呼叫回傳腳本文字（可用 mock prompt 測試）
- OpenAI gpt-image-1 失敗時回傳 `None`，不中斷流程
- 爬取輔助：至少一個平台可回傳候選清單格式的資料

**阻塞條件：**
- `OPENAI_API_KEY` 從 Secret Manager 掛載完成（文字 + 圖像共用）
- `CRAWLER_CREDENTIAL` 就緒

---

## Phase 4：Service 層

**目標：** 五個 service 完成，業務邏輯可獨立測試

**施工順序（依依賴關係）：**

1. `CrawlerService`（依賴 crawler_client, domain/rules）
2. `CandidateService`（依賴 CrawlerService, firestore）
3. `ScriptService`（依賴 CandidateService, llm_client, domain/prompts, compliance_rules）
4. `StoryboardService`（依賴 ScriptService, llm_client, image_gen_client）
5. `TrackingService`（依賴 firestore, llm_client 用於 DNA 計算）

**完成條件（每個 service）：**
- `CrawlerService.run_daily_crawl("髮品")` → 寫入 candidates collection
- `CandidateService.get_today_candidates("balanced")` → 回傳 3 個候選
- `ScriptService.generate([id1, id2, id3], "髮品")` → 回傳三版本腳本 + CTA + 合規
- `StoryboardService.generate(script_id, "ig_reels")` → 回傳 5 鏡頭分鏡列
- `TrackingService.compute_dna()` → 回傳 DNA 結構（樣本不足時回傳 INSUFFICIENT_DATA）

**阻塞條件：** Phase 2（Firestore）+ Phase 3（外部 client）均完成

---

## Phase 5：入口層 + 排程

**目標：** 所有 API endpoint 就緒，排程可正常觸發

**交付物：**
- `modules/*/route.py`（8 個 endpoint，見 spec-developer API 清單）
- `scheduler.py`（APScheduler，09:00 GMT+8 觸發 CrawlerService）
- 統一回傳格式：`{"success": bool, "data": ..., "error": {...}}`

**完成條件：**
- 所有 endpoint curl 測試通過（有 session）
- 無 session 時全部回 401
- `POST /api/v1/script/generate` → 回傳三版本腳本
- 排程設定確認（本機可手動觸發測試）

**阻塞條件：** Phase 4 所有 service 完成

---

## Phase 6：前端

**目標：** 小編可完整操作主流程（候選 → 腳本 → 分鏡 → 追蹤）

**交付物：**
- `static/index.html`（主頁面，含 4 個 Tab）
- `static/js/api.js`（所有 fetch 集中）
- `static/js/dashboard.js`（候選、腳本、分鏡、風格分析 Tab）
- `static/js/tracking.js`（成效追蹤、DNA Tab）
- `static/js/common.js`（Tab 切換、排程狀態、通知）
- `static/css/main.css`

**施工順序：**
1. `api.js`（所有 fetch 函式）
2. `dashboard.js`（候選卡、腳本卡、分鏡表）
3. `tracking.js`（成效卡、DNA 顯示）
4. `common.js`（Tab 切換、排程狀態條、漏斗閉環視覺化）

**完成條件：**
- 瀏覽器開啟，可看到今日候選 3 個爆款
- 點「生成腳本」可看到三版本腳本 + CTA 變體 + 合規結果
- Tab 2 分鏡可切換脆 / IG Reels 兩個版本
- Tab 4 可顯示品牌 DNA（需有成效資料）

**阻塞條件：** Phase 5 所有 API endpoint 完成

---

## Phase 7：整合測試 + 部署

**目標：** 完整流程 E2E 驗證，部署到 Cloud Run

**完成條件：**
- E2E：09:00 排程觸發 → 候選出現 → 生成腳本 → 分鏡 → 匯出 Word → 追蹤新增
- Cloud Run 部署成功，`GET /health` 回傳 200
- Secret Manager 所有 Key 確認掛載
- VIBECODING-SAFETY 自檢清單全部通過（`/docs` 關閉、`debug=False`）

---

## 先做與後補界線

**一開始就必須正確（不可後補）：**
- 資料夾結構（Phase 0）
- domain 層所有函式（Phase 1）
- session middleware（Phase 2）
- 統一回傳格式（Phase 5）

**可先簡化、後續優化：**
- OpenAI gpt-image-1：Phase 3 可先用 placeholder，Phase 6 前端完成後再整合
- 合規禁詞清單：初版用 20 個高風險詞，後續持續補充
- 品牌 DNA 計算：初版用簡單平均，後續可加權

---

## Claude Code 指令模板

**開始一個 Phase：**
```
我要開始 Phase {N}：{Phase 名稱}。
請先讀 @docs/spec-developer.md 和 @docs/architecture.md，
然後按 dev-order.md 的交付物清單，從 {第一個交付物} 開始。
```

**Phase 卡住時：**
```
{描述卡住的地方}。
請先確認 @docs/architecture.md 的模組邊界規則，
再確認 @docs/engineering-guardrails.md 是否有相關禁止項。
```

**Phase 結束時：**
```
Phase {N} 完成，請對照 dev-order.md 的完成條件逐項確認，
並檢查是否有跨層直接存取或重複邏輯出現。
```
