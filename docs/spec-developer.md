> 版本：v1.0 | 日期：2026-05-04

# spec-developer.md — ScriptFlow 技術功能規格

---

## 系統總覽

**技術棧：** Python 3.12 + FastAPI | HTML + CSS + JS（前端）| Firestore | GCP Cloud Run | OpenAI API（GPT-5-mini 文字 + gpt-image-1 圖像）

| 層級 | 職責 |
|---|---|
| route（入口層） | 接收請求、session 驗證、呼叫 service、回傳統一格式 |
| service（業務邏輯層） | 爬取協調、候選評分、腳本生成、成效計算 |
| infra（整合層） | Firestore 讀寫、OpenAI 文字 API、OpenAI 圖像 API、爬取 client |
| domain（共用規則層） | 分類設定、合規禁詞清單、Prompt 樣板、相似度規則 |
| scheduler | 09:00 定時觸發 CrawlerService |

**外部服務：**

| 服務 | infra 檔案 | 用途 |
|---|---|---|
| OpenAI GPT-5-mini | `infra/llm_client.py` | 腳本生成、合規掃描、DNA 計算 |
| OpenAI gpt-image-1 | `infra/image_gen_client.py` | 分鏡示意圖（與文字共用同一把 API key） |
| 爬取輔助 | `infra/crawler_client.py` | 小紅書 / 抖音 / Threads 熱門內容 |
| Firestore | `infra/firestore.py` | 所有資料持久化 |

---

## 專案結構

```
scriptflow/
├── main.py                         ← FastAPI 啟動點
├── scheduler.py                    ← 09:00 APScheduler 排程
├── modules/
│   ├── crawler/
│   │   ├── route.py                ← POST /api/v1/crawler/trigger
│   │   └── service.py              ← CrawlerService
│   ├── candidates/
│   │   ├── route.py                ← GET /api/v1/candidates
│   │   └── service.py              ← CandidateService
│   ├── script/
│   │   ├── route.py                ← POST /api/v1/script/generate
│   │   └── service.py              ← ScriptService
│   ├── storyboard/
│   │   ├── route.py                ← POST /api/v1/storyboard/generate
│   │   └── service.py              ← StoryboardService
│   ├── tracking/
│   │   ├── route.py                ← POST/GET /api/v1/tracking
│   │   └── service.py              ← TrackingService
│   └── auth/
│       └── middleware.py           ← session 驗證 middleware
├── infra/
│   ├── llm_client.py
│   ├── image_gen_client.py
│   ├── crawler_client.py
│   └── firestore.py
├── domain/
│   ├── categories.py               ← 分類設定（美妝/美食/髮品）
│   ├── compliance_rules.py         ← 合規禁詞清單
│   ├── prompts.py                  ← OpenAI Prompt 樣板
│   └── rules.py                    ← 跨模組共用業務規則
└── static/
    ├── index.html
    ├── css/
    │   └── main.css
    └── js/
        ├── api.js                  ← 所有 fetch 集中管理
        ├── dashboard.js
        ├── tracking.js
        └── common.js
```

---

## 技術功能規格

### F1：每日爬取候選（09:00 自動排程）

```
觸發：APScheduler 09:00 (GMT+8)
輸入：分類設定（domain/categories.py）、B 軌相似度門檻（≥ 0.8）
輸出：今日候選清單寫入 Firestore candidates collection
成功：candidates collection 更新，今日主題與集中度寫入
失敗：單一平台爬取失敗 → 記錄失敗平台，繼續其他平台，最終候選可能少於 3 個
```

`CrawlerService.run_daily_crawl(category: str) → CrawlResult`

| 欄位 | 型別 | 說明 |
|---|---|---|
| topic | str | 今日主題（如「受損髮質修護」） |
| topic_concentration | float | 主題集中度（0-1） |
| candidates | list[Candidate] | 篩出的 3 個候選（可能少於 3） |
| failed_platforms | list[str] | 失敗的平台名稱 |

---

### F2：取得今日候選

```
GET /api/v1/candidates?category={美妝|美食|髮品}&strategy={balanced|hotness}
需要登入：是
輸出：今日 3 個爆款候選（含漏斗位置、導購意圖密度、相似度）
失敗：candidates 尚未產生 → 回傳 CANDIDATES_NOT_READY 錯誤
```

---

### F3：生成腳本（三平台版本）

```
POST /api/v1/script/generate
需要登入：是
輸入：{candidate_ids: [id1, id2, id3], category: str}
輸出：{threads_post, threads_reel, ig_reels}，各含腳本內容、CTA 三變體、合規掃描結果
失敗：OpenAI API 失敗 → 最多重試 2 次，超過回傳 SCRIPT_GENERATION_FAILED
```

`ScriptService.generate(candidate_ids, category) → ScriptResult`

| 輸出欄位 | 說明 |
|---|---|
| threads_post | Threads 純文字腳本（含 CTA 三變體） |
| threads_reel | 脆 30s 口播腳本（4 段時間軸，含 CTA） |
| ig_reels | IG 60s 口播腳本（4 段時間軸，含 Caption / Hashtag，含 CTA） |
| compliance | 各版本的違規詞清單（欄位名稱 + 建議替換詞） |
| funnel_roles | 各版本的漏斗角色標記 |

---

### F4：生成分鏡

```
POST /api/v1/storyboard/generate
需要登入：是
輸入：{script_id: str, platform: "threads_reel"|"ig_reels"}
輸出：分鏡列表（含每鏡頭的秒數、畫面、音效、口白、產品露出策略）
圖像生成失敗 → 不中斷流程，回傳 placeholder，前端顯示「示意圖生成中」
匯出：GET /api/v1/storyboard/{id}/export?format=pdf|word
```

---

### F5：新增成效資料

```
POST /api/v1/tracking
需要登入：是
輸入：{script_id: str, platform: str, publish_url: str}
輸出：{tracking_id: str}
```

```
GET /api/v1/tracking/{tracking_id}/metrics
觸發：發布後 7 天、14 天（手動觸發或排程）
輸出：{views, completion_rate, ctr, conversions, collected_at}
```

---

### F6：取得品牌爆款 DNA

```
GET /api/v1/tracking/dna
需要登入：是
輸出：{best_opening, best_cta, best_product_timing}，各含範本文字和數據依據
資料不足（< 5 支）→ 回傳 INSUFFICIENT_DATA，前端提示「需更多作品」
```

---

## 資料結構（Firestore）

### candidates collection

```json
{
  "id": "20251029_美妝",
  "date": "2025-10-29",
  "category": "髮品",
  "topic": "受損髮質修護",
  "topic_concentration": 0.81,
  "strategy": "balanced",
  "items": [
    {
      "rank": 1,
      "platform": "xiaohongshu",
      "url": "https://...",
      "title": "頭髮乾燥毛躁？這款髮膜我用了 3 週真的有感",
      "engagement": 282000,
      "completion_rate": null,
      "purchase_intent_density": 0.12,
      "topic_match": 0.92,
      "funnel_role": "seed",
      "b_track_similarity": null
    }
  ],
  "failed_platforms": [],
  "created_at": "2025-10-29T01:00:00Z"
}
```

### scripts collection

```json
{
  "id": "script_20251029_001",
  "date": "2025-10-29",
  "category": "髮品",
  "topic": "受損髮質修護",
  "source_candidate_ids": ["id1", "id2", "id3"],
  "threads_post": {"content": "...", "cta_variants": [...], "compliance": {...}},
  "threads_reel": {"segments": [...], "cta_variants": [...], "compliance": {...}},
  "ig_reels": {"segments": [...], "caption": "...", "hashtags": [...], "cta_variants": [...], "compliance": {...}},
  "created_at": "2025-10-29T03:00:00Z"
}
```

### tracking collection

```json
{
  "id": "tracking_001",
  "script_id": "script_20251029_001",
  "platform": "ig_reels",
  "publish_url": "https://www.instagram.com/reel/...",
  "metrics_7d": {"views": 82400, "completion_rate": 0.73, "ctr": 0.082, "conversions": 142, "collected_at": "..."},
  "metrics_14d": null,
  "created_at": "2025-10-29T14:00:00Z"
}
```

### brand_dna collection

```json
{
  "id": "brand_dna_001",
  "sample_count": 22,
  "best_opening": {"template": "「以前頭髮 ___ 直到我換了 ___」", "avg_completion_rate": 0.71},
  "best_cta": {"template": "限動連結搶最後 N 組", "avg_ctr": 0.074},
  "best_product_timing": {"position": "50%", "context": "before_after", "conversion_multiplier": 4.5},
  "updated_at": "2025-10-29T00:00:00Z"
}
```

---

## 模組責任

| 模組 | 能力 |
|---|---|
| `CrawlerService` | 協調三平台爬取；計算主題集中度；評估 B 軌相似度；計算導購意圖密度；判斷漏斗位置 |
| `CandidateService` | 管理今日候選；依策略（balanced / hotness）篩選；回傳候選清單 |
| `ScriptService` | 從三個候選萃取流量節奏；呼叫 OpenAI 文字 API 產三版本腳本；執行合規掃描；產 CTA 三變體 |
| `StoryboardService` | 根據腳本產分鏡列（5 欄）；協調 OpenAI 圖像 API；產 PDF / Word 匯出 |
| `TrackingService` | 儲存發布連結；回收成效指標；計算品牌爆款 DNA |

---

## 外部整合需求

| 服務 | 主要操作 | 認證方式 |
|---|---|---|
| OpenAI GPT-5-mini | `generate_script()`, `scan_compliance()`, `compute_dna()` | API Key（Secret Manager） |
| OpenAI gpt-image-1 | `generate_storyboard_image()` | 同上（共用同一把 API key） |
| 爬取輔助 | `fetch_hot_content(platform, category, hours=24)` | Credential（Secret Manager） |
| Firestore | 各 collection 讀寫 | GCP Service Account |

---

## 前後端對接 API 清單

| Method | Path | 功能 | 需要登入 |
|---|---|---|---|
| GET | `/api/v1/candidates` | 取得今日候選 | 是 |
| POST | `/api/v1/crawler/trigger` | 手動觸發爬取 | 是 |
| POST | `/api/v1/script/generate` | 生成三版本腳本 | 是 |
| POST | `/api/v1/storyboard/generate` | 生成分鏡 | 是 |
| GET | `/api/v1/storyboard/{id}/export` | 匯出 PDF/Word | 是 |
| POST | `/api/v1/tracking` | 新增發布連結 | 是 |
| GET | `/api/v1/tracking/{id}/metrics` | 取得成效指標 | 是 |
| GET | `/api/v1/tracking/dna` | 取得品牌爆款 DNA | 是 |
| GET | `/health` | 健康檢查 | 否 |

統一回傳格式：
```json
{"success": true, "data": {...}}
{"success": false, "error": {"code": "ERROR_CODE", "message": "說明"}}
```

前端需辨識的錯誤碼：`CANDIDATES_NOT_READY`、`SCRIPT_GENERATION_FAILED`、`IMAGE_GEN_FAILED`、`INSUFFICIENT_DATA`

---

## 部署

**Dockerfile 要點：**
- Python 3.12-slim，不以 root 執行
- `DEBUG=False`，不安裝 dev 依賴

**環境變數（全部從 Secret Manager 掛載）：**

| 變數名稱 | 用途 |
|---|---|
| `OPENAI_API_KEY` | OpenAI API 認證（文字 + 圖像共用） |
| `CRAWLER_CREDENTIAL` | 爬取輔助服務憑證 |
| `SESSION_SECRET` | Session cookie 簽名 |
| `GCP_PROJECT_ID` | Firestore 專案 ID |
| `FRONTEND_ORIGIN` | CORS 允許的前端 domain |
