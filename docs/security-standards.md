> 版本：v1.0 | 日期：2026-05-04

# security-standards.md

> 本文件只涵蓋全域安全底線原則。具體攻擊防禦（OAuth、JWT、CSRF、注入等）由 `.claude/rules/` 負責。

---

## 認證原則

- ScriptFlow 為品牌內部工具，所有頁面路由須通過身分驗證才能存取
- 認證邏輯集中在 FastAPI middleware，不散落在各 route 或 service
- 僅 `/health`、`/api/v1/health` 不需驗證
- 前端不保存認證 token，以後端 session cookie 管理登入狀態

---

## 授權原則

- ScriptFlow 目前只有一個角色（品牌小編），無多角色授權設計
- 所有操作（爬取、生成腳本、查詢成效）預設需要登入，無公開操作
- 後端是授權的最終控制點，前端隱藏元素不等於授權

---

## 敏感資料處理

敏感欄位清單：OpenAI API Key（文字 + 圖像共用）、Crawler API 憑證

規則：
- 上述敏感欄位不可出現在任何程式碼檔案、log、前端 JS 或 HTTP response
- 爆款候選的原始爬取內容（含個人 ID）不回傳給前端，只回傳 AI 萃取後的摘要
- 小編登入資訊不記錄在業務 log 中

---

## Secret 管理

- 所有 API Key 與憑證存放於 GCP Secret Manager，不寫在 `.env` 文件或程式碼
- 本機開發使用 `.env.local`（加入 `.gitignore`），正式環境由 Cloud Run 掛載 Secret
- ✓ `OPENAI_API_KEY`、`CRAWLER_CREDENTIAL` 存 Secret Manager
- ✗ 任何金鑰不可出現在 git commit 記錄中
- 不同環境（dev / staging / prod）使用獨立的 Secret 版本

---

## 前端安全邊界

- 前端不直接呼叫 OpenAI API（文字 + 圖像）、小紅書 / 抖音 / Threads 任何外部服務
- 前端 JS 檔案不包含任何 API Key 或憑證
- 合規禁詞清單不在前端維護，由後端回傳掃描結果
- ✗ 前端不可用 `localStorage` 或 `sessionStorage` 存放認證 token

---

## 後端安全邊界

- 後端是所有資料操作的最終控制點
- 每個 API endpoint 必須驗證 session，不信任前端傳來的身分宣告
- ✗ 不可因為「內部工具」而省略認證驗證
- ✗ 不可用 URL 參數傳遞 session token 或 API key

---

## Log 原則

應記錄：
- 09:00 排程爬取啟動 / 完成 / 失敗（含平台、爬取筆數）
- 腳本生成請求（timestamp、今日主題）
- 成效資料新增（timestamp，不記錄具體成效數字）
- 系統錯誤（error code，不記錄 API key 或憑證）

不可記錄：
- OpenAI API Key 等任何金鑰
- 爬取原始內容中的帳號 ID 或個人資訊
- 合規掃描的完整禁詞清單

---

## 外部服務安全

- 三個外部服務 client（OpenAI 文字 / OpenAI 圖像 / Crawler）只在 `infra/` 層初始化
- GCP Service Account 權限最小化：只授予 Cloud Run、Secret Manager、Firestore 必要權限
- 爬取服務憑證定期輪換，不使用永久 token
- ✗ 外部服務 client 不可在 route 或 service 層直接初始化

---

## 違規模式（全域禁止）

- **[禁止]** 任何 API Key 出現在程式碼檔案、git commit 或 log
- **[禁止]** 前端 JS 直接呼叫 OpenAI API 或爬取服務
- **[禁止]** 繞過 FastAPI middleware 直接在 route 判斷是否已登入
- **[禁止]** 將完整爬取原始資料（含個人 ID）傳回前端
- **[禁止]** 使用測試用 bypass token 留在任何非 local 環境
- **[禁止]** 不同環境（dev / prod）共用同一組 API Key 或 Secret
