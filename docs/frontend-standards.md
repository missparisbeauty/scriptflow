> 版本：v1.0 | 日期：2026-05-04

# frontend-standards.md

---

## 前端分工原則

- HTML 負責結構，CSS 負責樣式，JavaScript 負責互動，三者分離為獨立檔案
- 業務邏輯不寫在 HTML inline event handler（`onclick="..."` 禁止）
- CSS 不存放功能狀態（不用 class 名稱隱藏業務規則）
- JavaScript 只操作畫面與互動，不直接承擔業務判斷
- 所有 fetch / API 呼叫集中在 `static/js/api.js`，不散落各頁面

---

## 模組切分原則

每個主要頁面對應一個獨立 JS 模組：

| 頁面 | 模組 |
|---|---|
| 主操作台（爆款候選 + 腳本 + 分鏡 + 分析） | `static/js/dashboard.js` |
| 成效追蹤 | `static/js/tracking.js` |
| 共用邏輯（Tab 切換、排程狀態、通知） | `static/js/common.js` |
| API 呼叫封裝 | `static/js/api.js` |

規則：
- 模組只處理自己頁面的畫面與互動，不跨模組直接操作 DOM
- 共用 UI 邏輯抽到 `common.js`，共用 API 呼叫抽到 `api.js`
- 新功能以獨立模組新增，不插入現有模組中間

---

## API 呼叫規則

- 所有 fetch 統一寫在 `static/js/api.js`，其他 JS 只呼叫此模組的函式
- ✓ `api.fetchCandidates()` → 由 dashboard.js 呼叫
- ✓ 前端呼叫 `/api/v1/candidates`，後端轉發給爬取服務
- ✗ 前端不可直接呼叫 `api.openai.com`、小紅書、抖音、Threads 任何外部 API
- ✗ 前端不可存放 OpenAI API Key 等任何金鑰
- API 回傳錯誤時，前端顯示對應狀態，不把後端 error message 直接暴露給使用者

---

## 畫面狀態規則

每個有資料的區塊必須處理以下狀態：

| 狀態 | 說明 |
|---|---|
| 載入中 | 顯示 spinner 或骨架屏，禁止空白 |
| 成功 | 正常顯示資料 |
| 失敗 | 顯示錯誤提示 + 重試按鈕 |
| 無資料 | 顯示引導文字（如「尚無成效資料，請先發布影片」） |
| 處理中 | 爆款分析中、腳本生成中，顯示進度提示 |
| 合規警告 | 禁詞標橘色，不阻擋操作，但提示改寫 |

- 狀態切換由 JavaScript 控制 CSS class，不直接操作 style 屬性
- 禁止「靜默失敗」——任何 API 錯誤都必須有前端反饋

---

## DOM 與事件管理

- 事件綁定統一在模組初始化時集中綁定，不散落在 HTML 或多個函式中
- ✓ `dashboard.js` 的 `init()` 集中綁定所有 Tab 切換、按鈕點擊事件
- ✗ 不跨模組直接操作別的模組的 DOM 元素
- ✗ 不把資料狀態藏在 DOM attribute（用 JS 變數管理狀態）
- 頁面 Tab 切換時清除舊狀態，不殘留前一個 Tab 的 loading 狀態
- 動態產生的元素（如 CTA 變體卡）用事件委派（event delegation）綁定

---

## 樣式管理

- CSS class 命名以功能描述為主（`.funnel-tag`, `.cta-variant`, `.compliance-bar`）
- 不同頁面模組的樣式以 CSS 變數（`--ink`, `--accent` 等）統一管理色彩
- 模組樣式以 prefix 區分，避免全域污染（`.sb-*` 為分鏡相關，`.cta-*` 為 CTA 相關）
- ✗ 不用 `!important` 強覆蓋，遇到層疊衝突先找根本原因
- ✗ 不把平台品牌色（IG 漸層、Line 綠）寫死在全域 CSS，改為 inline style 或局部 class

---

## 前端不得承擔的責任

- ✗ 不做爬取邏輯的最終判斷（哪些爆款納入、相似度評分）
- ✗ 不做合規禁詞的最終清單維護（只顯示後端傳回的警告結果）
- ✗ 不直接呼叫 OpenAI API（文字 + 圖像）、小紅書 / 抖音 / Threads 任何外部服務
- ✗ 不保存 API Key、用戶 token 在 localStorage 或 JS 變數中（應由後端 session 管理）
- ✗ 不承擔品牌爆款 DNA 的計算邏輯（只顯示後端計算結果）

---

## 可維護原則

- 新增平台（如 YouTube Shorts）只需新增對應的爆款卡樣板和 API 呼叫，不改現有模組
- 新增分類（如「美甲」）只需後端新增分類設定，前端只改分類切換按鈕資料
- 腳本卡、分鏡表、CTA 變體卡使用統一的渲染函式，不各自重複實作
- 改前端畫面不應觸及 API 路由或後端邏輯
- 每個 JS 模組最上方有明確的職責說明（一行 comment）
