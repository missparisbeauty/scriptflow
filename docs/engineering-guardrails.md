> 版本：v1.0 | 日期：2026-05-04

# engineering-guardrails.md

---

## 禁止捷徑

- ✗ `CrawlerService` 不可直接讀寫 Firestore，必須透過 `infra/firestore.py`
- ✗ `ScriptService` 不可直接讀取 `candidates` collection，必須呼叫 `CandidateService.get_today_candidates()`
- ✗ `TrackingService` 不可直接呼叫 OpenAI API，必須透過 `infra/llm_client.py`
- ✗ 不可在 route function 直接寫業務判斷（`if similarity_score >= 0.8` 這類邏輯屬於 service 層）
- ✗ 不可用臨時 hardcode 取代正式的設定檔讀取（如把今日主題直接寫死在 CandidateService）
- ✗ 不可用全域變數在模組間傳遞今日候選狀態，必須透過 Firestore 讀取

---

## AI / Vibe Coding 規則

- AI 產出的 route function 超過 20 行必須重構，超出的邏輯移到 service
- AI 產出的 service 必須確認沒有直接 import `google.cloud.firestore` 或任何 infra 模組（只能 import 同層 service 或 domain）
- AI 產出的前端 fetch 必須確認目標是後端 API（`/api/v1/...`），不可直接打外部服務
- AI 產出的程式碼若有 `OPENAI_API_KEY = "sk-proj-..."` 的硬編碼立即刪除，改為環境變數
- AI 產出的新函式若功能與現有函式重複，以現有為準，不留兩套
- AI 產出的爬取邏輯若使用 `eval()` 或 `yaml.load()` 立即替換

---

## Bug 修復規則

- 修 bug 前先確認根因，不只修表面症狀（如「腳本產出慢」→ 先查是 OpenAI API latency 還是 Firestore 讀取）
- 不可為了快速修復而讓 `ScriptService` 直接讀 Firestore（應修正 `CandidateService` 的查詢方式）
- 修 bug 不得新增跨模組的直接依賴來繞過原有介面
- 修 bug 後補最小必要的測試或日誌，確認修復有效
- 不可把 bug 修復的特例 if-else 放在 route 層，應在正確責任層處理

---

## 重複邏輯規則

- 同一邏輯（如「計算導購意圖密度」）出現兩次必須抽出到 `domain/rules.py`
- 相似度評分邏輯只在 `CrawlerService` 維護，不在 `CandidateService` 各自複製一版
- 合規禁詞掃描邏輯只在 `ScriptService` 維護，前端不維護獨立版本
- 不可複製現有 service 改名後新增，應在原有 service 新增方法

---

## 變更影響控制

- 修改 `CandidateService.get_today_candidates()` 的回傳格式前，先確認 `ScriptService` 和前端的消費方式
- 新增爬取平台（如 YouTube Shorts）只改 `infra/crawler_client.py`，不動 `CandidateService` 核心邏輯
- 修改合規禁詞清單只改 `domain/compliance_rules.py`，不改 `ScriptService` 流程
- 任何改動影響超過兩個 service 時，先確認是否邊界放錯了

---

## 技術債警訊清單

出現以下跡象時必須停下來重構：

- ✗ service 層直接出現 `from google.cloud import firestore`
- ✗ 同一個 Firestore collection 名稱（如 `"candidates"`）出現在兩個以上的 service
- ✗ route function 超過 30 行
- ✗ 一個 service 同時承擔爬取、評分、腳本生成三種責任
- ✗ 修改「今日主題判定邏輯」需要同時修改 `CrawlerService` 和 `CandidateService`
- ✗ 前端 JS 出現直接打 OpenAI API 的 fetch 呼叫
- ✗ 合規禁詞清單以 hardcode 方式散落在多個地方

---

## 重構觸發條件

- 同一邏輯出現兩次 → 立即抽出到 `domain/`
- 單一 service 超過 300 行 → 審查是否承擔了不屬於自己的責任
- 新增功能需要同時修改超過 3 個 service → 邊界設計有問題
- 某段程式碼一動就不知道會影響哪裡 → 必須先補依賴關係說明再修改
- `domain/prompts.py` 的 prompt 樣板超過 10 個且難以維護 → 考慮拆分為每個場景獨立模組

---

## 最低品質底線

- 不破壞既有模組邊界（任何新增都必須放在正確層）
- 不新增隱藏副作用（service 的 public 方法不應有未文件化的 side effect）
- 不吞錯誤（所有 try/except 必須有明確的錯誤處理或 log）
- 不留 dead code（AI 產出但未使用的函式立即刪除）
- 不留測試用 hardcode 或 bypass 在正式環境
- 命名清晰：`get_today_candidates()` 而非 `get_data()`
- 新增的功能可以在不修改其他模組的情況下獨立測試
