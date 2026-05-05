> 版本：v1.0 | 日期：2026-05-04

# backend-standards.md

---

## 責任分工原則

| 層級 | 職責 | 不可做的事 |
|---|---|---|
| 入口層（route） | 接收請求、基本驗證、呼叫 service、回傳結果 | 不寫業務邏輯、不直接呼叫外部服務 |
| 業務邏輯層（service） | 處理業務規則與流程 | 不直接存取資料庫、不直接呼叫外部服務 |
| 資料存取層（infra/repository） | 資料讀寫、外部服務呼叫 | 不做業務判斷 |
| 共用規則層（domain） | 跨模組共用的業務規則 | 不做 I/O 操作 |
| 排程層（scheduler） | 09:00 定時觸發爬取 | 不包含業務邏輯，只觸發 service |

---

## FastAPI 使用邊界

- route function 只做：驗證 input → 呼叫 service → 回傳結果
- route function 超過 20 行代表邏輯放錯地方，移到 service
- ✓ `@router.post("/candidates/generate")` → 呼叫 `CandidateService.generate()`
- ✗ route 不可直接呼叫 `openai.chat.completions.create()`
- ✗ route 不可做 `if candidate.similarity_score >= 0.8:` 業務判斷
- ✗ route 不可直接查 Firestore
- 回傳一律使用統一 Response schema，不各自亂回

---

## Service 層規則

ScriptFlow 的 service 模組對應：

| Service | 職責 |
|---|---|
| `CrawlerService` | 協調三平台爬取，判斷主題集中度、相似度評分 |
| `CandidateService` | 管理今日爆款候選，計算導購意圖密度，維護三平台各抽 1 / 混合策略 |
| `ScriptService` | 呼叫 OpenAI API 產出腳本（三平台版本），執行合規禁詞掃描 |
| `StoryboardService` | 產出分鏡文字，協調 OpenAI 圖像 API 產示意圖 |
| `TrackingService` | 儲存成效資料，計算品牌爆款 DNA |
| `SchedulerService` | 09:00 定時觸發 CrawlerService，不含業務邏輯 |

規則：
- 每個 service 只處理自己模組的責任
- service 之間若需互動，只能呼叫對方的公開方法，不直接讀對方的資料
- ✓ `ScriptService` 呼叫 `CandidateService.get_today_candidates()`
- ✗ `ScriptService` 不可直接查 Firestore 的 candidates collection

---

## 資料存取規則

- Firestore 讀寫統一在 `infra/firestore.py`，不散落在 service
- 每個功能模組只讀寫自己的 collection，不跨 collection 直接存取
- ✓ `CandidateService` 只讀寫 `candidates` collection
- ✗ `ScriptService` 不可直接讀 `candidates` collection，需透過 `CandidateService`
- 寫入前必須有 schema 驗證，不直接寫入 raw dict

---

## 外部整合規則

ScriptFlow 的外部服務集中在 `infra/` 層：

| 檔案 | 對應服務 |
|---|---|
| `infra/llm_client.py` | OpenAI 文字 API（GPT-5-mini，腳本生成、合規掃描、DNA 計算） |
| `infra/image_gen_client.py` | OpenAI 圖像 API（gpt-image-1，分鏡示意圖） |
| `infra/crawler_client.py` | 小紅書 / 抖音 / Threads 爬取輔助 |
| `infra/firestore.py` | Firestore 讀寫 |

規則：
- client 初始化（API key 讀取）只在 infra 層，不在 service 或 route
- 更換外部服務（如換圖像生成供應商）只改對應 infra 檔案，不動 service
- ✗ 不可在多個地方散落呼叫 `openai.chat.completions.create()`

---

## 模組邊界與資料隔離

- 每個功能模組有自己的目錄：`modules/{name}/route.py` + `service.py`
- 跨模組互動只透過 service 公開方法，不直接 import 對方的 repository
- ✓ `ScriptService` import `CandidateService`，呼叫 `get_today_candidates()`
- ✗ `ScriptService` 不可 import `candidate_repository` 直接查資料庫
- ✗ 不可用共享全域變數在模組間傳遞狀態
- B 軌相似度評分邏輯集中在 `CrawlerService`，不散落到 `CandidateService`

---

## 錯誤處理與回傳一致性

- 所有 API 回傳使用統一格式：`{"success": bool, "data": ..., "error": {"code": str, "message": str}}`
- ✓ OpenAI API 超時 → 回傳 `{"success": false, "error": {"code": "AI_TIMEOUT", "message": "腳本生成逾時，請重試"}}`
- ✗ 不可直接把 `openai.APIError` 的 raw message 回傳給前端
- 爬取失敗（單一平台）不中止整體流程，回傳部分結果並標記失敗平台
- 禁詞掃描失敗不阻擋腳本產出，降級顯示「合規檢查暫時無法使用」

---

## 可維護與可擴充

- 新增平台（如 YouTube Shorts）只需新增 `infra/crawler_client.py` 的對應方法，不改 CrawlerService 核心邏輯
- 新增分類（如「美甲」）只需在 `domain/categories.py` 新增設定，不改 service
- 合規禁詞清單抽為獨立設定檔 `domain/compliance_rules.py`，不硬編碼在 ScriptService
- 修改腳本生成 prompt 只改 `domain/prompts.py`，不改 ScriptService 流程邏輯
