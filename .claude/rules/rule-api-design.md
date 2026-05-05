---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py, static/**/*.js
---

# API 設計規範

所有 API 端點開發時套用本規範。

---

## RESTful 慣例

- GET 查詢、POST 新增、PUT 完整替換、PATCH 部分更新、DELETE 刪除
  - PUT：需傳入資源的完整欄位，缺少欄位視為清空
  - PATCH：只傳需要變更的欄位，其餘欄位保持原值
  - 判斷原則：前端只想改「其中幾個欄位」→ 用 PATCH；需要「整筆替換」→ 用 PUT
- URL 用複數名詞：`/users`、`/orders`，不用 `/getUser`、`/deleteOrder`
- 巢狀路由表達資源關係：`/users/{id}/orders`
- API 端點本身不依賴 server 端流程狀態（每個請求自帶足夠資訊判斷處理結果），但**認證使用 Session cookie**
  → 本專案認證機制為 Session cookie + middleware（見 architecture.md、dev-order.md Phase 2），rule-auth.md 的 JWT 條款為備用參考，僅在未來明確決定改用 token-based auth 時才適用
  → Session 簽名密鑰：`SF_SESSION_SECRET`（GCP Secret Manager）
  → Cookie 必須設定 HttpOnly、Secure、SameSite=Strict

## 版本控制

- 路由一律加版本前綴：`/api/v1/...`
- 現有版本禁止移除或重新命名欄位
- 需異動結構 → 開新版本，舊版本保留過渡期（**最短 1 個 sprint，由專案負責人決定移除時間，不自行判斷**）
- 我遇到舊版本端點時，主動詢問是否已可移除，不沉默略過

## Request & Response

- 一律回傳 JSON，標頭加 `Content-Type: application/json`
- 統一 response 結構：
  - 成功：`{"data": ..., "error": null}`
  - 失敗：`{"data": null, "error": {"code": "ERROR_CODE", "message": "..."}}`
- **response 包裝由 `route.py` 負責**，`service.py` 只回傳資料或拋出 Exception，不負責包裝成統一結構
- 標準 HTTP 狀態碼：
  - 200 OK、201 Created（POST 新增成功）、204 No Content（DELETE 成功、無回傳內容的 PATCH）
  - 400 輸入錯誤、401 未驗證、403 無權限、404 找不到
  - 409 資料衝突、422 無法處理、500 伺服器錯誤
- 204 使用條件：操作成功但不需要回傳資料（DELETE、部分 PATCH）；有回傳內容一律用 200

## 分頁

- 列表型 API 一律使用 **limit / offset** 分頁
- 參數命名：`?limit=20&offset=0`
- `limit` 最大值 100，超過直接 400
- response 附上總筆數：`{"data": {"items": [...], "total": 150}, "error": null}`

✓ `GET /api/v1/posts?limit=20&offset=40`
✗ cursor-based 分頁（除非專案規格明確指定）

## 輸入驗證

- 所有 input 在進入 business logic 前，必須在 route 層完成驗證
- 驗證失敗回傳 400，附上欄位層級錯誤說明
- 禁止回傳籠統錯誤訊息（「輸入有誤」這種不行）

## 錯誤處理

- 禁止將 stack trace 或內部錯誤細節回傳給 client
- 使用集中式 error handler，在 `app/main.py` 統一掛載，不在各 route 散落 try/catch
- 內部完整記錄 log，對外只回傳 error code

## 禁止

- 未事先告知不可新增 HTTP 相關套件
- 不得在未開新版本的情況下更動現有 response 結構
- 即使「內部」端點也不可繞過 validation
