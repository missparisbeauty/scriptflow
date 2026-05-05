---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py, static/**/*.js
---

# API、注入、檔案上傳、業務邏輯、加密安全規則

寫任何涉及 API 端點、使用者輸入、檔案處理、資料加密、業務流程的程式碼時套用本規則。

---

## API 文件與端點

可能被攻擊：API 文件洩漏、端點列舉、Schema 暴露

防禦準則：
- 正式環境不能暴露 Swagger / OpenAPI / GraphQL Introspection
- API 文件端點必須在 production build 時關閉

應對措施：
- Swagger UI 只在 DEBUG=True 時啟用
- GraphQL 生產環境關閉 Introspection
- 不在回應中暴露 stack trace 或內部路徑

---

## API 過度暴露

可能被攻擊：API 回傳不必要的欄位，攻擊者取得密碼雜湊、內部 ID、其他使用者資料

防禦準則：
- API 回應必須明確定義輸出欄位，不能直接序列化整個 DB model
- 敏感欄位不能出現在任何 API 回應中

應對措施：
- 用 response schema（Pydantic / Zod）明確定義回傳欄位
- password_hash、internal_id、其他使用者的資料永遠不出現在回應裡

---

## Rate Limiting

可能被攻擊：無限次請求、暴力破解、資源耗盡

防禦準則：
- 所有對外公開的端點必須有 Rate Limiting
- Rate Limiting 計數器必須在 server 端，不能信任 client 的 IP header

應對措施：
- FastAPI 使用 `slowapi` 套件實作 Rate Limiting，在 `app/main.py` 掛載 `Limiter`
- 一般端點限制：`@limiter.limit("60/minute")`
- 登入、密碼重設、OTP 驗證端點：`@limiter.limit("5/minute")`
- LLM API 端點：`@limiter.limit("10/minute")`（防費用耗盡攻擊）
- X-Forwarded-For 等 IP 相關 header 不能直接用於識別，使用 `slowapi` 預設的 `get_remote_address`

---

## GraphQL 特有風險
適用條件：spec-user 使用 GraphQL

可能被攻擊：Batch Query 暴力破解、Deep Query DoS、Alias 繞過 Rate Limiting

防禦準則：
- 必須限制查詢深度和複雜度
- Batch Query 必須有數量上限

應對措施：
- 設定 max_depth（建議 5）和 max_complexity
- 同一請求的 alias 數量限制（建議 10）
- 生產環境關閉 Introspection

---

## SQL 注入
適用條件：有資料庫查詢且接受使用者輸入

可能被攻擊：攻擊者透過輸入欄位執行任意 SQL，竊取或刪除資料

防禦準則：
- 所有 DB 查詢必須用參數化查詢或 ORM，不能用字串拼接

應對措施：
- 禁止 f-string 或 + 拼接 SQL 字串
- ORM 的 raw() 和 execute() 必須用 params 參數傳值，不能嵌入變數

---

## XSS
適用條件：有前端顯示使用者輸入或 API 回傳內容

可能被攻擊：攻擊者注入惡意腳本，竊取 Cookie 或執行任意操作

防禦準則：
- 所有使用者輸入在輸出到 HTML 前必須 escape
- 不能用 innerHTML 或 dangerouslySetInnerHTML 直接插入使用者輸入

應對措施：
- 設定 Content-Security-Policy header
- 使用框架的 template engine，不手動拼接 HTML

---

## 命令注入
適用條件：有執行系統指令、呼叫子程序的功能

可能被攻擊：攻擊者透過輸入執行任意系統指令

防禦準則：
- 不能把使用者輸入直接拼入 shell 指令
- 避免使用 shell=True（Python subprocess）

應對措施：
- 用 subprocess 傳 list 而非字串：subprocess.run(["cmd", arg], shell=False)
- 必要時對輸入做嚴格白名單驗證

---

## SSRF
適用條件：有 URL 取得、代理、webhook 功能

可能被攻擊：攻擊者讓 server 請求內部服務，存取 GCP metadata、內網資源

防禦準則：
- 不能直接用使用者提供的 URL 發出 server 端請求
- 必須驗證目標 URL 不是內部 IP 或保留位址
- 用 DNS 解析後的 IP 驗證，不用字串比對（字串比對可被 `http://169.254.169.254.evil.com` 繞過）

應對措施：
```python
import socket
import ipaddress

BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),  # GCP metadata
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),     # localhost
    ipaddress.ip_network("::1/128"),          # IPv6 localhost
]

def is_safe_url(url: str) -> bool:
    host = urlparse(url).hostname
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    return not any(ip in net for net in BLOCKED_NETWORKS)
```
- 白名單允許的 domain，不在白名單的直接拒絕

---

## XXE
適用條件：有接受外部 XML 輸入或解析 XML 文件的功能

可能被攻擊：攻擊者透過 XML 讀取伺服器檔案或發出內部請求

防禦準則：
- XML parser 必須禁用 external entity 處理

應對措施：
- Python lxml：etree.XMLParser(resolve_entities=False)
- 能用 JSON 就不用 XML

---

## 路徑遍歷
適用條件：有接受檔案路徑參數或讀取本機檔案的功能

可能被攻擊：攻擊者用 ../../../etc/passwd 讀取任意檔案

防禦準則：
- 不能把使用者輸入直接拼入檔案路徑
- 必須驗證最終路徑在允許的目錄內

應對措施：
- 用 os.path.realpath() 解析後比對是否在白名單目錄內
- 檔案名稱白名單驗證，不允許 . 和 / 等特殊字元

---

## 檔案上傳
適用條件：有檔案上傳功能

可能被攻擊：上傳 Webshell、執行惡意程式碼

防禦準則：
- 副檔名和 MIME type 都必須驗證，且以白名單為準
- 上傳的檔案不能存在可直接執行的目錄

應對措施：
- 用 python-magic 驗證實際檔案內容，不信任 Content-Type header
- 上傳檔案存到 GCS / S3，不存到 web server 本機
- 檔名重新生成（UUID），不使用使用者提供的檔名

---

## 業務邏輯：支付與金額
適用條件：有支付、結帳或金額計算功能

可能被攻擊：竄改 request body 中的價格或數量

防禦準則：
- 價格和金額必須在 server 端從 DB 讀取，不能信任 client 傳來的金額

應對措施：
- checkout API 只接受 product_id 和 quantity，price 從 DB 查
- 數量必須驗證為正整數，拒絕負數和零

---

## 業務邏輯：Race Condition
適用條件：有餘額扣除、優惠券使用、庫存或任何需要原子性的操作

可能被攻擊：並發請求同時通過檢查，導致超扣或重複使用

防禦準則：
- 所有涉及狀態變更的操作必須用 DB transaction 保證原子性

應對措施：
- 用 SELECT FOR UPDATE 或樂觀鎖（version 欄位）
- 優惠券和庫存操作不能分兩步（先查再寫），必須一步完成

---

## 業務邏輯：多步驟流程
適用條件：有多步驟流程（付款、驗證、設定）

可能被攻擊：跳過中間步驟直接存取後續端點

防禦準則：
- 每個步驟必須在 server 端驗證前一步驟已完成
- 不能只靠 client 的步驟狀態判斷

應對措施：
- 流程狀態存在 server 端 session 或 DB，每個端點驗證狀態

---

## 密碼雜湊

可能被攻擊：MD5 / SHA1 雜湊的密碼可被彩虹表或 GPU 快速破解

防禦準則：
- 密碼必須用專為密碼設計的演算法雜湊，不能用通用 hash 函式

應對措施：
- 使用 bcrypt（cost 12+）或 Argon2id
- 禁止 MD5、SHA1、SHA256 直接用於密碼雜湊
- 必須加 salt（bcrypt 和 Argon2 內建）

---

## 敏感資料傳輸與儲存

可能被攻擊：明文傳輸被攔截、log 洩漏敏感資料、API 過度暴露

防禦準則：
- 所有敏感資料必須透過 HTTPS 傳輸
- 敏感資料不能出現在 URL 參數、log、error message 中

應對措施：
- 強制 HTTPS redirect，不接受 HTTP 傳輸認證資料
- log 記錄前過濾 password、token、credit_card 等欄位
- 信用卡號只存最後四碼，不存完整號碼

---

## 加密金鑰管理

可能被攻擊：hardcoded 金鑰被提交到 git，攻擊者取得後可解密所有資料

防禦準則：
- 加密金鑰、API key、secret 不能 hardcode 在程式碼中
- 不能提交到版本控制

應對措施：
- 生產環境：secret 存在 GCP Secret Manager，Cloud Run 掛載為環境變數，程式碼用 `os.environ` 讀取
- 本地開發：`.env` 檔案模擬環境變數，`.env` 加入 `.gitignore`
- git 歷史如有洩漏必須 rotate，不能只刪除檔案
