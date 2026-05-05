---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py, static/**/*.js
---

# 認證、授權、Session 安全規則

寫任何涉及登入、帳號、Token、Session、Cookie、JWT、OAuth、SAML、權限控制的程式碼時套用本規則。

---

## 登入 API

可能被攻擊：暴力破解、密碼噴灑、帳號列舉

防禦準則：
- 失敗次數計數必須在 server 端，不能信任 client
- 連續失敗必須有鎖定機制
- 所有失敗回應訊息統一，不能區分「帳號不存在」和「密碼錯誤」

應對措施：
- Rate Limiting 計數器存在 DB 或 cache，登入功能完成的同一個 phase 就要加上
- 登入失敗一律回傳同樣的訊息、同樣的 HTTP 狀態碼、同樣的回應時間

---

## 密碼重設

可能被攻擊：Token 預測、Token 重放、Host Header 注入

防禦準則：
- Token 必須用密碼學安全隨機函式生成，不能用 uuid 或時間戳
- Token 必須有過期時間，存在 server 端
- Token 驗證與標記已使用必須是原子操作，不能分兩步

應對措施：
- 用語言內建的 CSPRNG（Python: secrets.token_urlsafe、Node: crypto.randomBytes）
- 過期時間和 used 狀態存在 DB，驗證時用 transaction 一次讀寫
- 重設連結的 domain 寫死在設定檔，不從 request header 讀取

---

## Session 管理

可能被攻擊：Session 固定、Session 重放、登出未失效

防禦準則：
- 登入成功後必須產生新的 Session Token，不能沿用登入前的 Token
- 登出後 Session 必須在 server 端立即銷毀
- Session Token 必須用 CSPRNG 生成，長度足夠（128 bits 以上）

應對措施：
- 登入時呼叫 session.regenerate()，不手動複製舊 session 資料
- 登出時從 DB / cache 刪除 session 記錄，不只是清除 client cookie
- Session 設定閒置超時（30 分鐘）和絕對超時（8 小時）

---

## Cookie 安全屬性

可能被攻擊：XSS 竊取 Cookie、中間人攔截、跨站請求

防禦準則：
- 所有認證 Cookie 必須設定 HttpOnly、Secure、SameSite

應對措施：
- HttpOnly：防止 JavaScript 讀取
- Secure：只透過 HTTPS 傳送
- SameSite=Lax（最低標準），涉及敏感操作改用 Strict

---

## CSRF 防護

可能被攻擊：跨站請求偽造，攻擊者誘導使用者觸發狀態變更操作

防禦準則：
- 所有狀態變更操作（POST / PUT / PATCH / DELETE）必須有 CSRF 防護
- 使用 Bearer Token 的 API 天然抵抗 CSRF，但仍需驗證 Origin header

應對措施：
- Cookie-based session：每個請求帶 CSRF Token，server 端驗證
- SPA + Bearer Token：驗證 Origin / Referer header 是否來自允許的 domain
- 不接受只靠 Cookie 的狀態變更請求

---

## JWT

可能被攻擊：None Algorithm、弱密鑰破解、Key Confusion（RS256→HS256）、kid 注入

防禦準則：
- 必須明確指定允許的 algorithm，不接受 none
- 使用非對稱加密時（RS256），不能用 public key 當 HMAC secret
- kid 欄位不能直接拿來查詢 DB 或讀取檔案

應對措施：
- 驗證時白名單指定 algorithm（只接受 RS256 或 HS256，二選一）
- kid 值必須對照白名單，不能直接用於檔案路徑或 Firestore 查詢
- JWT 過期時間必須設定（max 1 小時），不能是永久有效
- JWT 簽名金鑰存在 GCP Secret Manager，透過環境變數注入，不寫死在程式碼中
- Access Token 過期後透過 Refresh Token 換發，Refresh Token 存在 Firestore，登出時立即刪除

---

## IDOR / 水平越權

可能被攻擊：攻擊者修改 ID 參數存取他人資源

防禦準則：
- 每次存取資源前必須確認該資源屬於當前登入的使用者
- 不能只靠 ID 參數判斷權限，必須對照 DB 中的 owner

應對措施：
- 查詢時加入 WHERE user_id = current_user.id 條件
- 不在回應中暴露可預測的連續 ID，改用 UUID 或 hash ID
- 回傳 404 而非 403，避免洩漏資源存在與否

---

## 垂直越權 / 角色控管

可能被攻擊：一般使用者呼叫管理員 API

防禦準則：
- 每個端點必須明確宣告所需角色，不能只靠前端隱藏
- 角色驗證必須在 middleware 層，不能散落在各 controller

應對措施：
- 管理員端點一律加上 `require_role("admin")` decorator，定義在 `app/main.py` 並在各 route 引用
- 角色清單存在 server 端（Firestore），不信任 JWT payload 裡的 role 欄位（需對照 DB）

---

## Mass Assignment

可能被攻擊：攻擊者在 request body 加入非預期欄位提升權限

防禦準則：
- 接受 JSON body 的端點必須明確白名單允許的欄位
- 不能直接把 request body 映射到 DB model

應對措施：
- 用 schema 驗證（Pydantic / Zod）明確定義允許欄位
- role、isAdmin、balance 等敏感欄位永遠不出現在可接受的 input schema

---

## OAuth / OIDC

可能被攻擊：redirect_uri 竄改、CSRF、PKCE 繞過、Client Secret 外洩

防禦準則：
- redirect_uri 必須完全相符白名單，不接受 pattern matching
- 每個請求必須有 state 參數，server 端驗證
- 必須強制 PKCE
- Client Secret 只能存在 server 端

應對措施：
- 白名單存設定檔，部署時注入，不寫在程式碼裡
- state 用 CSPRNG 生成，存 session，回調時比對
- 不帶 code_challenge 的請求直接 400

---

## SAML / SSO

可能被攻擊：XML 簽章繞過、Assertion 重放、Comment Injection

防禦準則：
- 必須驗證 XML 簽章完整性
- 必須驗證 Recipient、Audience、NotOnOrAfter
- 不能在簽章驗證前讀取任何欄位

應對措施：
- 用有主動維護的 SAML library，不自行實作 XML 簽章驗證
- 驗證流程：簽章 → 時效 → Recipient → 才讀 NameID
