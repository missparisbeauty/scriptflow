---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py, static/**/*.js, *.yaml, *.yml, Dockerfile, cloudbuild.yaml
---

# 雲端、組態、資訊洩漏安全規則

寫任何涉及 GCP / 雲端服務、Storage、IAM、Docker、HTTP 回應標頭、CORS、環境設定的程式碼時套用本規則。

---

## GCP IAM 權限

可能被攻擊：過度授權的 Service Account 被攻擊者取得後可存取所有資源

防禦準則：
- Service Account 只給執行任務所需的最小權限
- 不使用 Owner 或 Editor 這類廣泛角色

應對措施：
- Cloud Run service account 只給需要存取的 API 對應的單一角色
- 不同服務用不同 Service Account，不共用
- 禁止在程式碼或環境變數中放 Service Account JSON key，改用 Workload Identity

---

## GCP Metadata API

可能被攻擊：應用程式被 SSRF 攻擊後，攻擊者透過 169.254.169.254 取得 Service Account Token

防禦準則：
- 啟用 GCP Metadata Server 的 v1beta1 屏蔽
- SSRF 防護必須阻擋 metadata IP

應對措施：
- Cloud Run 預設只支援 IMDSv1，需在網路層阻擋 169.254.169.254
- SSRF 防護的 IP 黑名單必須包含：`169.254.169.254`、`metadata.google.internal`、`localhost`、`127.0.0.1`、`0.0.0.0`、`10.x`、`172.16.x`、`192.168.x`、IPv6 的 `::1` 和 `::ffff:*`
- 驗證時用 DNS 解析後的 IP 比對，不用字串比對（見 rule-api.md SSRF 章節的範例程式碼）

---

## GCP Storage / Bucket

可能被攻擊：Bucket 設為公開存取，任何人可讀取或寫入

防禦準則：
- 所有 Bucket 預設為私有，不開放公開存取
- 不用 Bucket 的 ACL 管理權限，改用 IAM

應對措施：
- 建立 Bucket 時明確設定 uniform bucket-level access
- 上傳檔案時不設定 public-read ACL
- 需要公開的靜態資源改用 CDN，不直接開放 Bucket

---

## Cloud Run / 容器設定

可能被攻擊：容器以 root 執行、掛載 Docker socket、Privileged 模式導致容器逃逸

防禦準則：
- 容器不以 root 執行
- 不掛載 /var/run/docker.sock
- 不使用 Privileged 模式

應對措施：
- Dockerfile 加入 USER nonroot 或指定非 root UID
- Cloud Run 不需要 Privileged，不要開啟此設定
- 容器內不安裝不需要的工具（curl、wget、nc）

---

## Secret 管理

可能被攻擊：hardcoded secret 被提交到 git，或出現在 container image 中

防禦準則：
- 所有 secret 必須存在 GCP Secret Manager
- 不能出現在程式碼、Dockerfile、git 歷史中

應對措施：
- Cloud Run 透過 Secret Manager 掛載 secret 為環境變數（程式碼仍用 `os.environ` 讀取，Secret Manager 是來源，不是兩種做法）
- 本地開發用 `.env` 檔案模擬環境變數，`.env` 加入 `.gitignore`，提交前用 git-secrets 或 trufflehog 掃描
- Dockerfile 不用 ARG / ENV 傳入 secret

---

## HTTP 安全標頭

可能被攻擊：缺少安全標頭導致 XSS、Clickjacking、MIME sniffing 攻擊

防禦準則：
- 所有 response 必須包含必要的安全標頭

應對措施：
- 在 `app/main.py` 的 middleware 統一設定以下標頭：
  - Content-Security-Policy
  - X-Frame-Options: DENY
  - X-Content-Type-Options: nosniff
  - Strict-Transport-Security: max-age=31536000; includeSubDomains
  - Referrer-Policy: strict-origin-when-cross-origin
- 敏感頁面加上 Cache-Control: no-store

---

## CORS

可能被攻擊：CORS 設定過於寬鬆，允許任意來源攜帶 Cookie 存取 API

防禦準則：
- Access-Control-Allow-Origin 不能設為 *（當有 credentials 時絕對不行）
- 不能直接反射 request 的 Origin header

應對措施：
- 白名單列出允許的 origin，只回傳白名單內的值
- Access-Control-Allow-Credentials: true 只搭配嚴格的 origin 白名單使用
- 不允許 null origin

---

## 開放重定向
適用條件：有 URL 重定向功能

可能被攻擊：攻擊者構造重定向到惡意網站的 URL，用於釣魚攻擊

防禦準則：
- 重定向目標必須在白名單內，不能使用任意 URL

應對措施：
- 重定向只允許相對路徑或白名單 domain
- 不接受完整 URL 作為重定向目標（除非在白名單內）

---

## 錯誤處理與資訊洩漏

可能被攻擊：stack trace、內部路徑、DB schema 暴露在 error response 中

防禦準則：
- 生產環境不能回傳 stack trace 或內部錯誤細節
- Debug 端點必須在生產環境關閉

應對措施：
- 集中式 error handler 攔截所有例外，對外只回傳 error code 和通用訊息
- FastAPI 的 /docs 和 /redoc 在生產環境關閉（docs_url=None）
- DEBUG=False 在生產環境，透過環境變數控制

---

## 稽核日誌

可能被攻擊：攻擊行為發生後無法追溯，無法偵測入侵

防禦準則：
- 所有敏感操作必須記錄稽核日誌
- 日誌必須包含足夠資訊供事後追溯

應對措施：
- 記錄：who（user_id）、what（操作）、when（timestamp）、result（成功/失敗）
- 登入失敗、權限拒絕、資料刪除必須記錄
- 日誌不能包含密碼、token、信用卡號等敏感資料
