> 版本：v1.0 | 日期：2026-05-04

# setup-checklist.md — ScriptFlow 開發前置準備

---

## 阻塞開發的前置條件（先看這裡）

| 前置條件 | 阻塞的 Phase | 優先級 |
|---|---|---|
| GCP 專案建立 + Firestore 初始化 | Phase 0, 2 | 🔴 最高 |
| GCP Service Account 建立（Firestore 權限） | Phase 0, 2 | 🔴 最高 |
| `SESSION_SECRET` 設定 | Phase 2 | 🔴 最高 |
| `OPENAI_API_KEY` 取得並存入 Secret Manager（同一把同時用於文字 + 圖像） | Phase 3 | 🟠 高 |
| `CRAWLER_CREDENTIAL` 取得並設定 | Phase 3 | 🟠 高 |

---

## 外部服務與帳號

### GCP（Google Cloud Platform）

```
□ 建立 GCP 專案（或使用既有專案）
□ 啟用 Firestore API
□ 啟用 Cloud Run API
□ 啟用 Secret Manager API
□ 建立 GCP Service Account
  名稱建議：scriptflow-sa
  授予角色：
    - Cloud Datastore User（Firestore 讀寫）
    - Secret Manager Secret Accessor（Secret 讀取）
□ 下載 Service Account JSON Key（本機開發用）
```

### OpenAI API（文字 + 圖像，同一把 key）

```
□ 前往 platform.openai.com 註冊 / 登入
□ 儲值（建議 $20 起，依使用量）
□ 建立 API Key（Project key 推薦）
□ 在 Settings → Limits 設定 monthly usage limit（建議 $15-20，避免費用暴增）
□ API Key 格式：sk-proj-... 或 sk-...
□ 同一把 key 同時可用於 GPT-5-mini（文字）與 gpt-image-1（圖像）
□ 在 Limits 頁設定 alert（如達 80% 用量寄信通知）
```

### 爬取輔助服務

```
□ 確認小紅書 / 抖音 / Threads 爬取方式（第三方服務或自建）
□ 取得對應 Credential / Token
□ 確認頻率限制與使用條款
```

---

## 權限與 API 開通

```
□ GCP Firestore API 已啟用
□ GCP Cloud Run API 已啟用
□ GCP Secret Manager API 已啟用
□ Cloud Run Service Account 已授予必要角色（見上方）
□ GCP Cloud Build API 已啟用（若使用 Cloud Build 部署）
```

---

## 金鑰與 Secret 管理

### Secret Manager 建立指令

```bash
# 建立所有 Secret（本機執行，需先 gcloud auth login）
gcloud secrets create OPENAI_API_KEY --replication-policy="automatic"
gcloud secrets create CRAWLER_CREDENTIAL --replication-policy="automatic"
gcloud secrets create SESSION_SECRET --replication-policy="automatic"

# 填入值
echo -n "sk-proj-..." | gcloud secrets versions add OPENAI_API_KEY --data-file=-
echo -n "your_crawler_credential" | gcloud secrets versions add CRAWLER_CREDENTIAL --data-file=-
echo -n "your_random_session_secret_min_32_chars" | gcloud secrets versions add SESSION_SECRET --data-file=-
```

### 環境變數表

| 變數名稱 | 用途 | 來源 |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API 認證（文字 + 圖像共用） | OpenAI Platform |
| `CRAWLER_CREDENTIAL` | 爬取輔助服務憑證 | 爬取服務 |
| `SESSION_SECRET` | Session cookie 簽名（≥32字元亂數） | 自行產生 |
| `GCP_PROJECT_ID` | Firestore 專案 ID | GCP 控制台 |
| `FRONTEND_ORIGIN` | CORS 允許的前端 domain | 部署後填入 |

### .env.example（加入 .gitignore）

```
OPENAI_API_KEY=sk-proj-...
CRAWLER_CREDENTIAL=your_crawler_credential_here
SESSION_SECRET=your_random_secret_min_32_chars
GCP_PROJECT_ID=your_gcp_project_id
FRONTEND_ORIGIN=http://localhost:8080
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
```

---

## 本機開發環境

### 需要安裝的工具

| 工具 | 版本 | 說明 |
|---|---|---|
| Python | 3.12+ | 後端語言 |
| pip | 最新 | 套件管理 |
| gcloud CLI | 最新 | GCP 操作 |
| Docker | 最新 | 容器建置（部署用） |

### 首次啟動指令

```bash
# 1. Clone 專案
git clone {repo_url}
cd scriptflow

# 2. 建立虛擬環境
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 複製 .env 並填入金鑰
cp .env.example .env
# 編輯 .env 填入實際值

# 5. 設定 GCP 認證（本機）
export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account.json"

# 6. 啟動開發伺服器
uvicorn main:app --reload --port 8080

# 7. 確認健康狀態
curl http://localhost:8080/health
```

---

## 雲端與部署前置條件

```
□ Cloud Run 服務建立（或使用 gcloud run deploy 首次部署時自動建立）
□ Secret Manager 所有 Secret 已建立並填值
□ Cloud Run Service Account 已授予 Secret Accessor 角色
□ Firestore 資料庫建立（Native mode，asia-east1 區域建議）
□ 靜態前端由 Cloud Run 提供服務（不需要 Cloud Storage）
□ HTTPS：Cloud Run 預設提供，確認無 HTTP 後門
```

### 部署指令

```bash
# 建置並部署
gcloud run deploy scriptflow \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-secrets="OPENAI_API_KEY=OPENAI_API_KEY:latest,CRAWLER_CREDENTIAL=CRAWLER_CREDENTIAL:latest,SESSION_SECRET=SESSION_SECRET:latest" \
  --set-env-vars="GCP_PROJECT_ID=your_project_id,FRONTEND_ORIGIN=https://your-service.run.app"
```

---

## 資料與測試前置條件

```
□ Firestore 4 個 Collection 初始化（見 Phase 0）：
  - candidates
  - scripts
  - tracking
  - brand_dna
□ 手動測試：寫入一筆 candidates 文件，確認 Firestore 可正常讀寫
□ 本機可手動觸發爬取測試（至少一個平台）
```

---

## 安全與權限確認

```
□ .env 已加入 .gitignore
□ service-account.json 已加入 .gitignore
□ 不將任何 Secret 寫入程式碼
□ GCP Service Account 只有必要角色（不給 Editor / Owner）
□ 部署後確認 /docs 和 /redoc 回傳 404
□ 部署後確認 debug=False
```

---

## 快速確認清單（開始 Phase 0 前）

```
□ GCP 專案建立
□ Firestore 啟用（Native mode）
□ Service Account 建立並授權
□ gcloud CLI 登入完成
□ Python 3.12 安裝
□ .env 填寫完成（至少 SESSION_SECRET + GCP_PROJECT_ID）
□ uvicorn main:app --reload 啟動無錯誤
□ GET /health 回傳 {"status": "ok"}
□ Firestore 手動寫入測試通過

完成以上所有項目後，進入 dev-order.md 的 Phase 0。
```
