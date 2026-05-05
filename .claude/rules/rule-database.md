---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py
---

# Firestore 使用規範

所有涉及 Firestore 讀寫的程式碼開發時套用本規範。

---

## 存取位置

- Firestore 讀寫只在 `infra/` 層，禁止在 service、route 直接存取
- 所有 Firestore 讀寫集中在 `infra/firestore.py`，不按 collection 拆獨立檔案
- 非 owner 模組不可直接讀寫其他模組的 collection
- 各 collection 的 owner 模組定義在 `docs/spec-developer.md`，開工前必讀確認歸屬

✓ `from infra.firestore import get_user`
✗ `db.collection("users").document(uid).get()`（寫在 service 或 route 裡）

## 讀取規範

- 所有查詢必須有 `limit()`，禁止無限制讀取整個 collection
- 用 `select()` 只取需要的欄位，不讀整份 document
- 複雜查詢建立 composite index，不用 client-side filter 補救

✓ `db.collection("logs").where("user_id", "==", uid).limit(50).stream()`
✗ `db.collection("logs").stream()`（無 limit）

## 寫入規範

- 多筆寫入用 `batch` 或 `transaction`，禁止 loop 逐筆寫入
- 需要原子性的操作（讀後寫）必須用 `transaction`
- document ID 用 UUID，不用可預測的遞增 ID 或使用者輸入

✓ `batch = db.batch(); batch.set(...); batch.set(...); batch.commit()`
✗ `for item in items: db.collection("x").add(item)`（loop 逐筆）

## 資料結構

- collection 名稱用小寫 snake_case（`user_sessions`，不是 `UserSessions`）
- document 內的欄位名稱用 snake_case
- 時間戳記統一用 `firestore.SERVER_TIMESTAMP`，不用本地時間
- 不在 document 裡存巢狀陣列超過一層（查詢困難）

## 軟刪除

- 軟刪除統一用 `is_deleted: bool` 欄位，不實際刪除 document
- **`infra/firestore.py` 負責過濾**：所有讀取函式預設加上 `.where("is_deleted", "==", False)`，呼叫方不需要自行過濾
- 需要讀取已刪除資料時（如管理後台），使用明確命名的獨立函式（如 `get_deleted_users()`），不修改預設行為

✓ `db.collection("users").where("is_deleted", "==", False).where("user_id", "==", uid).get()`（在 infra 層統一處理）
✗ 在 service 層各自加 `is_deleted` 過濾條件

## Schema 遷移

Firestore 無強制 schema，欄位變更時遵守以下規則：

- **新增欄位**：直接新增，舊 document 缺少該欄位時程式碼必須有預設值處理，不可假設欄位一定存在
- **欄位改名**：禁止直接改名，改用「新增新欄位 → 雙寫過渡 → 確認全部遷移後移除舊欄位」流程，不自行決定移除時間點
- **型別變更**：同上，走雙寫過渡，不直接覆蓋舊型別
- 遷移進行中必須告知，不沉默執行

## 安全規則

- Firestore Security Rules 預設拒絕所有存取
- 只開放後端 Service Account 的存取，禁止前端直接存取
- 不在 client 端（前端 JS）初始化 Firestore

## 費用控制

- 避免在迴圈裡做 document read（N+1 問題）
- listener（`on_snapshot`）用完記得 unsubscribe
- 大量資料用 pagination，不一次撈全部

## 禁止

- `db.collection("x").get()`（無條件讀整個 collection）
- 在前端 JS 直接存取 Firestore
- document ID 使用使用者提供的值（路徑注入風險）
- 用 `delete` 欄位做軟刪除以外的場景（改用 `is_deleted` bool 欄位）
