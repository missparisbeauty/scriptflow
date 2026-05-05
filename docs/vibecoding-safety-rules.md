> 版本：v1.0 | 日期：2026-05-04

# vibecoding-safety-rules.md

> 你（Claude Code）在產生 ScriptFlow 程式碼時，必須自動避開以下錯誤。每次寫程式碼時自動對照，不要等人提醒。

---

## 你常犯的不安全程式碼模式（ScriptFlow 適用）

| 你可能會寫的 | 為什麼危險 | 應該改成 |
|-------------|-----------|---------|
| `eval(爬取內容)` | 爬取回來的內容被當成程式碼執行，攻擊者可在伺服器上跑任意指令 | 永遠不要 eval 任何外部資料 |
| `yaml.load(data)` | 可以執行任意程式碼 | `yaml.safe_load(data)` |
| `pickle.loads(user_data)` | 攻擊者可透過 pickle 在伺服器執行任意程式碼 | 用 JSON |
| `os.system(f"curl {url}")` | 爬取 URL 被注入指令時可破壞伺服器 | `subprocess.run(["curl", url], ...)` |
| `app.run(debug=True)` | 觸發錯誤就能看到完整程式碼和環境變數，包含 OpenAI API Key | `debug=False`，生產環境關閉 |
| `/docs`、`/redoc` 在生產環境 | 外部可直接看到所有 API 規格，掃描漏洞更容易 | 生產環境關閉 FastAPI 文件路由 |
| `CORS(app, origins="*", supports_credentials=True)` | 任何網站都能代替小編呼叫你的 API | 限定前端實際域名 |
| `OPENAI_API_KEY = "sk-proj-..."` 硬編碼 | 推上 GitHub 就洩漏，OpenAI 的帳單你來付 | `os.environ["OPENAI_API_KEY"]` |
| `innerHTML = llmOutput` | OpenAI 回傳的內容如果含 HTML/JS 會直接執行，可能竊取 session | `textContent` 或 DOMPurify 淨化後才渲染 |

---

## 你寫 ScriptFlow API 時必須做的事

- 每個 API endpoint 都要有 FastAPI middleware 的 session 驗證，不能只靠前端判斷登入狀態
  - 錯誤示範：前端不顯示按鈕，但 `/api/v1/script/generate` 沒有驗證 session
  - 後果：任何人用 curl 就能呼叫腳本生成 API，消耗 OpenAI API 費用
- CORS 限定為小編實際使用的前端域名，不寫 `*`
- 所有來自前端的輸入（爆款連結 URL、手動補充連結）在後端驗證格式，不信任前端傳來的資料
- 爬取來的外部內容（小紅書 / 抖音 / Threads）不直接傳回前端，只回傳 AI 萃取後的摘要

---

## 你處理 ScriptFlow 機密資料時必須做的事

- `OPENAI_API_KEY`、`CRAWLER_CREDENTIAL` 只用環境變數，不寫程式碼
- `.env` 加入 `.gitignore`，不推上 Git
- OpenAI API Key 只在後端 `infra/llm_client.py` 與 `infra/image_gen_client.py` 使用，前端 JS 完全看不到
- Log 不記錄任何 API Key，錯誤訊息不包含金鑰內容
- 爬取到的帳號 ID 等個人資訊不寫入 log

---

## 你部署 ScriptFlow 到 GCP Cloud Run 時必須做的事

- `DEBUG=False`，不在生產環境啟動 debug 模式
- FastAPI 的 `/docs`、`/redoc`、`/openapi.json` 在生產環境關閉
- Cloud Run Service Account 只授予 Firestore 讀寫、Secret Manager 讀取、Cloud Storage 讀寫，不給 owner 或 editor 權限
- Secret Manager 存 API Key，不用 Cloud Run 的環境變數明文存金鑰
- `HTTPS 強制啟用`（Cloud Run 預設提供，但確認沒有 HTTP 後門）

---

## 你處理 LLM 輸出時必須做的事

- OpenAI API 回傳的腳本內容在前端渲染時，用 `textContent` 不用 `innerHTML`
  - 若需要保留部分格式（粗體、換行），用 DOMPurify 淨化後才插入 DOM
- OpenAI API 的 input 設 token 上限，避免爬取到超長內容時單次呼叫費用暴增
- OpenAI API 呼叫失敗時回傳 retry 上限錯誤（最多 2 次），不無限重試消耗費用
- 合規禁詞掃描結果從後端傳回，前端只顯示結果，不在前端跑掃描邏輯

---

## 交付前自檢清單（ScriptFlow 適用）

```
□ 所有 API endpoint 都有 session 驗證 middleware
□ CORS 限定為實際前端域名，不是 *
□ OPENAI_API_KEY 使用環境變數，不在程式碼中
□ .env 已加入 .gitignore
□ DEBUG=False，生產環境確認
□ /docs、/redoc 在生產環境已關閉
□ OpenAI API input token 有設上限
□ LLM 輸出在前端用 textContent 渲染，不用 innerHTML
□ Cloud Run Service Account 最小權限確認
□ 爬取到的外部內容不直接回傳前端（只傳 AI 摘要）
□ Log 中不含任何 API Key 或敏感憑證
```
