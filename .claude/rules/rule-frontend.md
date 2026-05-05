---
paths: "**/*.html", "**/*.css", "**/*.js", "templates/**/*.html"
---

# 前端開發規範

所有 HTML、CSS、JavaScript 開發時套用本規範。

---

## 檔案結構

- CSS 和 JS 必須外連獨立檔案，禁止內嵌在 HTML `<style>` 或 `<script>` 標籤內
- 每個頁面對應一個 JS 檔案，共用邏輯抽到 `static/js/common.js`
- 跨頁共用 UI 元件統一放在 `static/js/components.js`，不在各頁面 JS 各自實作
  - 元件以 **function** 形式定義，接受參數回傳 DOM 節點或 HTML string
  - 元件不持有狀態，狀態由呼叫方管理後傳入
- CSS 統一使用 **BEM 命名**，不使用模組化，不用全域 class 互相污染

✓ `<link rel="stylesheet" href="/static/css/main.css">`
✗ `<style>body { color: red; }</style>`

## API 呼叫

- **所有 fetch 必須統一走 `static/js/api.js`**，不可在其他 JS 檔案直接呼叫 `fetch`
- `api.js` 負責：統一加 header、處理 loading 狀態、解析 error 結構
- timeout 規則：
  - 一般 API：預設 **10 秒**
  - LLM / SSE 串流端點：**不設 timeout**，改用 SSE `EventSource` 或 `fetch` streaming 處理，不走一般 `api.js` 的 timeout 機制
- 所有 API 呼叫透過後端 proxy，禁止前端直接呼叫第三方 API
- API key 不出現在任何前端檔案（HTML、JS、CSS）
- error 處理統一讀 `error.message` 顯示訊息、`error.code` 判斷錯誤類型

```javascript
// ✓ 正確：透過 api.js 呼叫
import { apiGet } from './api.js'
const data = await apiGet('/api/v1/users')

// ✗ 錯誤：在頁面 JS 直接 fetch
const res = await fetch('/api/v1/users')
```

## 表單與使用者輸入

- **前端只做 UX 驗證**（即時提示格式錯誤），不作為安全把關依據，後端 400 回應才是最終驗證
- 禁止用 `innerHTML` 插入使用者輸入或 API 回傳的內容
- 禁止用 `dangerouslySetInnerHTML`
- 需要渲染 HTML 時，用 DOMPurify 淨化後再插入
- 表單送出後立即 disable 按鈕，收到 response 後才恢復，防止重複送出

✓ `element.textContent = userInput`
✗ `element.innerHTML = userInput`

## 分頁處理

- 列表型 API 回傳格式：`{"data": {"items": [...], "total": 150}, "error": null}`
- 下一頁計算：`offset = 當前頁 * limit`
- 從 `data.total` 判斷是否還有下一頁：`offset + limit < total` 才顯示「載入更多」
- `error` 欄位取錯誤訊息統一從 `error.message` 讀取，錯誤代碼從 `error.code` 讀取

✓ `const hasMore = offset + limit < data.total`
✗ 自行判斷「回傳筆數 < limit 就是最後一頁」（items 可能剛好整除）

## 狀態管理

- 每個操作必須有三種狀態：loading、success、error
- loading 時顯示 spinner 或 skeleton，禁止讓畫面空白等待
- error 時顯示具體的錯誤訊息，不只是「發生錯誤」
- 敏感資料（token、個資）不存在 localStorage 或 sessionStorage

## 效能

- 圖片加 `loading="lazy"`
- 非關鍵 JS 加 `defer` 或 `async`
- 不在 scroll、resize 事件裡做重計算（用 debounce）

## Jinja2 Template 安全

- 禁止在 template 中使用 `{{ value | safe }}`，`safe` filter 會關閉 XSS 防護
- 禁止在後端使用 `render_template_string(user_input)`，使用者輸入可覆寫 template 邏輯
- 變數輸出一律用 `{{ value }}`（Jinja2 預設自動 escape），不手動繞過
- 禁止在 template 中拼接 HTML 字串

✓ `{{ user.name }}`
✗ `{{ user.name | safe }}`
✗ `{{ "<script>" + user_input + "</script>" }}`

## 禁止

- Source map 在生產環境暴露（`.map` 檔不部署）
- `console.log` 留在生產環境
- 直接操作 `document.cookie` 存敏感資料
- 用 `alert()` 做錯誤提示
