> 版本：v1.0 | 日期：2026-05-04

# architecture.md — ScriptFlow

---

## 架構總覽

```
┌────────────────────────────────────────────────────────┐
│                   前端（靜態 HTML/JS）                   │
│  dashboard.js  tracking.js  common.js  api.js          │
└────────────────────┬───────────────────────────────────┘
                     │ HTTP（/api/v1/...）
┌────────────────────▼───────────────────────────────────┐
│              FastAPI（GCP Cloud Run）                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  入口層（route + middleware）                     │   │
│  │  candidates / crawler / script /                │   │
│  │  storyboard / tracking / auth                   │   │
│  └──────────────────┬──────────────────────────────┘   │
│  ┌───────────────────▼─────────────────────────────┐   │
│  │  業務邏輯層（service）                             │   │
│  │  CrawlerService  CandidateService  ScriptService │   │
│  │  StoryboardService  TrackingService              │   │
│  └──────┬──────────────────────────┬───────────────┘   │
│  ┌──────▼──────┐        ┌──────────▼───────────────┐   │
│  │  domain/    │        │  infra/                   │   │
│  │  categories │        │  llm_client               │   │
│  │  prompts    │        │  image_gen_client         │   │
│  │  compliance │        │  crawler_client           │   │
│  │  rules      │        │  firestore                │   │
│  └─────────────┘        └──────────┬────────────────┘   │
│  ┌──────────────┐                  │                    │
│  │  scheduler   │        外部服務   │                    │
│  │  (09:00 UTC+8)│  OpenAI API（文字 + 圖像）/ 爬取 / Firestore  │
│  └──────────────┘                                       │
└────────────────────────────────────────────────────────┘
```

---

## 模組清單與責任

| 模組 | 層級 | 責任 | 擁有的資料 |
|---|---|---|---|
| `auth.middleware` | 入口 | Session 驗證，所有路由的 gatekeeper | Session cookie |
| `candidates.route` | 入口 | 接收候選查詢請求，回傳今日候選 | 無 |
| `crawler.route` | 入口 | 接收手動觸發爬取請求 | 無 |
| `script.route` | 入口 | 接收腳本生成請求 | 無 |
| `storyboard.route` | 入口 | 接收分鏡生成、匯出請求 | 無 |
| `tracking.route` | 入口 | 接收成效新增、查詢請求 | 無 |
| `CrawlerService` | service | 協調三平台爬取；計算主題集中度、B 軌相似度、導購意圖密度 | 今日爬取結果（暫時，寫入後釋放） |
| `CandidateService` | service | 管理今日候選；依策略篩選；回傳候選清單 | candidates collection |
| `ScriptService` | service | 呼叫 OpenAI 文字 API 生成三版本腳本；執行合規掃描；生成 CTA 三變體 | scripts collection |
| `StoryboardService` | service | 產分鏡列；協調圖像生成；產匯出檔 | storyboard 關聯到 scripts |
| `TrackingService` | service | 儲存發布連結；回收成效；計算品牌爆款 DNA | tracking、brand_dna collection |
| `domain/categories` | domain | 分類定義（美妝/美食/髮品）與 B 軌類型設定 | 靜態設定 |
| `domain/compliance_rules` | domain | 合規禁詞清單（按平台） | 靜態設定 |
| `domain/prompts` | domain | OpenAI API 的 prompt 樣板 | 靜態設定 |
| `domain/rules` | domain | 跨模組共用業務規則（相似度門檻、漏斗分類邏輯） | 無狀態 |
| `infra/llm_client` | infra | 封裝 OpenAI 文字 API（GPT-5-mini） | API Key（環境變數） |
| `infra/image_gen_client` | infra | 封裝 OpenAI 圖像 API（gpt-image-1） | 同上（共用同一把 key） |
| `infra/crawler_client` | infra | 封裝三平台爬取輔助呼叫 | Credential（環境變數） |
| `infra/firestore` | infra | 封裝 Firestore CRUD | GCP Service Account |
| `scheduler` | 排程 | 09:00 APScheduler 觸發 CrawlerService | 無 |

---

## 模組邊界規則

**禁止的跨層行為：**

| 禁止行為 | 正確做法 |
|---|---|
| `ScriptService` 直接讀 Firestore | 透過 `CandidateService.get_today_candidates()` |
| route function 呼叫 `llm_client.py` | 透過 `ScriptService.generate()` |
| `CrawlerService` 直接寫 `scripts` collection | 只能寫 `candidates` collection，由各自 service 管理自己的 collection |
| domain 模組 import 任何 service 或 infra | domain 只被依賴，不依賴任何層 |
| 前端 JS 直接呼叫 OpenAI API / 爬取服務 | 前端只呼叫 `/api/v1/...` 後端路由 |

---

## 資料流

**Flow A：09:00 每日爬取**
```
APScheduler → scheduler.py
  → CrawlerService.run_daily_crawl(category)
    → infra/crawler_client → 小紅書 / 抖音 / Threads
    → domain/rules（相似度評分、漏斗分類）
    → infra/firestore（寫入 candidates collection）
```

**Flow B：小編查看今日候選**
```
前端 dashboard.js → GET /api/v1/candidates
  → auth.middleware（session 驗證）
  → candidates.route
    → CandidateService.get_today_candidates(strategy)
      → infra/firestore（讀 candidates collection）
  → 回傳候選清單 JSON
```

**Flow C：生成腳本**
```
前端 → POST /api/v1/script/generate {candidate_ids, category}
  → auth.middleware
  → script.route
    → ScriptService.generate(candidate_ids, category)
      → CandidateService.get_candidates(ids)（取候選摘要）
      → domain/prompts（組合 prompt 樣板）
      → infra/llm_client（呼叫 OpenAI API）
      → domain/compliance_rules（合規掃描）
      → infra/firestore（寫入 scripts collection）
  → 回傳三版本腳本 + CTA 變體 + 合規結果
```

**Flow D：生成分鏡**
```
前端 → POST /api/v1/storyboard/generate {script_id, platform}
  → auth.middleware
  → storyboard.route
    → StoryboardService.generate(script_id, platform)
      → infra/firestore（讀 scripts collection 取腳本）
      → infra/llm_client（產分鏡文字）
      → infra/image_gen_client（產示意圖，失敗不中斷）
  → 回傳分鏡列（5 欄）
```

**Flow E：成效回收**
```
前端 → POST /api/v1/tracking {script_id, platform, publish_url}
  → TrackingService.save_tracking(...)
    → infra/firestore（寫 tracking collection）
GET /api/v1/tracking/{id}/metrics → 手動觸發
  → TrackingService.collect_metrics(tracking_id)
    → 外部平台 API（未來實作，目前手動貼回）
    → infra/firestore（更新 metrics_7d / metrics_14d）
GET /api/v1/tracking/dna
  → TrackingService.compute_dna()
    → infra/firestore（讀 tracking + scripts collection 聚合計算）
    → infra/firestore（寫 brand_dna collection）
```

---

## 前端/後端/外部服務落點

**前端（static/）負責：**
- 畫面渲染、Tab 切換、漏斗視覺化條、腳本卡顯示
- 呼叫後端 `/api/v1/...`（透過 `api.js` 集中管理）
- 顯示合規掃描結果（不執行掃描）
- 不保存 API Key、不呼叫外部服務

**後端（FastAPI / Cloud Run）負責：**
- 所有業務邏輯、資料存取、外部服務呼叫
- session 驗證（middleware）
- 合規掃描（ScriptService）
- 腳本、分鏡、DNA 計算

**外部服務落點：**
- OpenAI API（文字 + 圖像）/ 爬取 → 只在 `infra/` 層呼叫
- Firestore → 只透過 `infra/firestore.py` 存取
- GCP Secret Manager → 啟動時讀取環境變數，不在執行時動態讀取

---

## 依賴方向

```
入口層（route）
    ↓
業務邏輯層（service）
    ↓              ↑
infra 層 ←→  domain 層（被依賴，不依賴任何層）
```

- domain 是最底層，不 import 任何 service 或 infra
- infra 只 import domain（型別定義），不 import service
- service 可 import domain 和 infra，不可 import 入口層
- 入口層只 import service，不可 import infra 或 domain
- DI 組裝位置：`main.py`（FastAPI app 初始化時注入 infra 到 service）

---

## 變更隔離場景

| 變更 | 只影響 | 不影響 |
|---|---|---|
| 換掉圖像生成 API 供應商 | `infra/image_gen_client.py` | StoryboardService、前端 |
| 修改 OpenAI Prompt 樣板 | `domain/prompts.py` | ScriptService 流程邏輯、前端 |
| 新增平台（如 YouTube Shorts） | `infra/crawler_client.py`、`domain/categories.py` | ScriptService、StoryboardService |
| 修改 B 軌相似度門檻（0.8 → 0.85） | `domain/rules.py` | CrawlerService 呼叫邏輯不變 |
| 新增分類（如「美甲」） | `domain/categories.py` | 所有 service 不需改動 |
| 前端新增 UI 元素（如新按鈕） | `static/` 前端程式碼 | 後端所有 service 和 infra |
| 修改合規禁詞清單 | `domain/compliance_rules.py` | ScriptService 流程邏輯不變 |

---

## 部署架構

```
[小編瀏覽器]
     │ HTTPS
     ▼
[GCP Cloud Run]（FastAPI）
     │              │
     ▼              ▼
[GCP Firestore] [GCP Secret Manager]
                    │
              OpenAI API（外部，文字 + 圖像）
              爬取輔助服務（外部）
```

- Cloud Run：自動擴縮，最小 0 個 instance（低頻使用適合）
- Firestore：NoSQL，按用量計費
- Secret Manager：存放所有 API Key
- 靜態前端：由 Cloud Run 提供服務（`static/` 目錄）

---

## 資料夾結構

```
scriptflow/
├── main.py                     ← FastAPI app 啟動點，DI 組裝
├── scheduler.py                ← APScheduler，09:00 觸發爬取
├── modules/
│   ├── auth/middleware.py      ← session 驗證 middleware
│   ├── candidates/             ← 候選爆款模組
│   ├── crawler/                ← 爬取協調模組
│   ├── script/                 ← 腳本生成模組
│   ├── storyboard/             ← 分鏡生成模組
│   └── tracking/               ← 成效追蹤模組
├── infra/                      ← 外部整合層（只被 service 呼叫）
│   ├── llm_client.py
│   ├── image_gen_client.py
│   ├── crawler_client.py
│   └── firestore.py
├── domain/                     ← 共用規則（不依賴任何層）
│   ├── categories.py
│   ├── compliance_rules.py
│   ├── prompts.py
│   └── rules.py
├── static/                     ← 前端靜態資源
│   ├── index.html
│   ├── css/main.css
│   └── js/
│       ├── api.js
│       ├── dashboard.js
│       ├── tracking.js
│       └── common.js
├── Dockerfile
└── requirements.txt
```
