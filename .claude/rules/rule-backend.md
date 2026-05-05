---
paths: app/**/*.py, modules/**/*.py, infra/**/*.py, domain/**/*.py
---

# FastAPI 後端開發規範

所有後端 Python 程式碼開發時套用本規範。

---

## 責任分層

- `modules/{功能}/route.py`：只負責接收請求、基本驗證、呼叫 service、回傳結果
- `modules/{功能}/service.py`：業務邏輯，只負責自己模組的責任
- `infra/`：外部服務初始化與對接（Firestore、OpenAI API、GCS 等）
- `domain/`：共用業務規則與資料型別

✓ route → service → infra（單向依賴）
✗ route 直接塞業務邏輯
✗ service 直接呼叫外部 API（應透過 infra）

## FastAPI 使用邊界

- route function 只做：驗證 input、呼叫 service、回傳 response
- 禁止在 route 裡寫 if/else 業務判斷
- 禁止在 route 裡直接初始化外部服務 client
- Auth middleware 在 `app/main.py` 統一掛載，不散落在各 route

✓ `user = await user_service.get_user(user_id)`
✗ `user = await db.collection("users").document(user_id).get()`（寫在 route 裡）

## Service 層規則

- 每個 service 只負責自己的模組責任
- service 之間需要互動時，只能呼叫對方的 public function，不直接存取對方資料
- 共用規則抽到 `domain/rules.py`，不複製貼上
- service 不可直接 import 另一個 service 的內部資料結構

## Schema 定義位置

- Request / Response 的 Pydantic schema 定義在 `modules/{功能}/schema.py`，不放在 `route.py` 或 `service.py` 內
- 跨模組共用的資料型別定義在 `domain/` 下，不重複定義在各模組的 `schema.py`
- `service.py` 的回傳型別使用 `domain/` 的型別或 Python 原生型別，不 import 其他模組的 `schema.py`

```python
# ✓ 正確
# modules/users/schema.py
class UserResponse(BaseModel):
    id: str
    name: str

# modules/users/route.py
from modules.users.schema import UserResponse

# ✗ 錯誤：schema 定義在 route 裡
@router.get("/users/{id}")
async def get_user(id: str):
    class UserResponse(BaseModel):  # 不應放在這裡
        ...
```

## 外部服務整合

- 每個外部服務一個 infra 檔案（`infra/firestore.py`、`infra/llm_client.py`）
- client 初始化在 infra 層，不在 service 或 route
- secret / API key 從環境變數讀取，不寫死
- 更換外部服務時，只改 infra 層，不影響 service

## 環境變數管理

- 用 Pydantic `BaseSettings` 集中管理所有環境變數
- 統一放在 `app/config.py`（必要欄位清單見 `docs/spec-developer.md`）
- 禁止在各處散落 `os.environ.get("KEY")`

✓ `from app.config import settings; settings.OPENAI_API_KEY`
✗ `os.environ.get("OPENAI_API_KEY")`（散落在各處）

## 錯誤處理

- 集中式 error handler 在 `app/main.py` 統一掛載
- 自訂 Exception class 定義在 `app/exceptions.py`，繼承自統一 base class（base class 結構見 `docs/spec-developer.md`）
- `service.py` 遇到業務錯誤時**一律拋出 Exception**，不回傳 `None` 或 tuple（如 `(data, error)`）
- `route.py` 不寫 try/catch，讓 Exception 往上交給集中式 error handler 處理
- 禁止吞掉例外（空 except 或只 pass）
- 所有預期外的錯誤必須記錄 log

```python
# ✓ 正確：service 拋出 Exception
# app/exceptions.py
class UserNotFoundError(AppBaseException): ...

# modules/users/service.py
def get_user(user_id: str):
    user = infra.firestore.get_user(user_id)
    if not user:
        raise UserNotFoundError(user_id)
    return user

# ✗ 錯誤：service 回傳 None 或 tuple
def get_user(user_id: str):
    user = infra.firestore.get_user(user_id)
    return user, "not found" if not user else None
```

## Logging 規範

- 使用 Python 標準 `logging` 模組，在 `app/main.py` 集中初始化，不在各模組各自設定
- 統一 log 格式：`who（user_id）| what（操作名稱）| when（timestamp）| result（success/failure）`
- Log level 用法：
  - `INFO`：正常業務操作（登入成功、資料寫入）
  - `WARNING`：異常但可繼續（重試、降級）
  - `ERROR`：需要人介入的錯誤（外部服務失敗、未預期例外）
- 寫入 log 前必須過濾以下欄位，以 `***` 遮蔽：`password`、`token`、`api_key`、`secret`、`credit_card`
- 稽核類 log（登入失敗、權限拒絕、資料刪除）必須記錄，不可省略

✓ `logger.info("user=%s action=delete_post result=success", user_id)`
✗ `logger.info("token=%s", token)`（敏感資料入 log）

---

## 禁止

- route 超過 20 行（超過代表邏輯塞錯地方）
- service 直接存取 Firestore（應透過 infra）
- 跨模組直接讀寫彼此資料
- 在多個地方初始化同一個外部服務 client
- 在各模組各自呼叫 `logging.basicConfig()`
