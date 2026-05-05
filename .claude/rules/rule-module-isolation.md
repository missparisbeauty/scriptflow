---
paths: modules/**/*.py, domain/**/*.py, infra/**/*.py
---

# 模組隔離規則

> 目標：修改一個功能，不需要連動修改其他模組。

---

## 違反時的處理方式

發現任何違反本規則的程式碼時，**不直接修正，先說明違規位置和原因，等待確認後再動手**。
隔離違規的影響範圍可能超出當下任務，需要人工判斷修正範圍。

---

## 跨模組呼叫

✓ 需要其他模組的資料 → 呼叫對方模組的公開函式
✗ 不可直接 import 其他模組的內部函式（`_` 前綴）
✗ 不可直接查其他模組 owner 的 Firestore collection

```python
# ✓ 正確
from modules.gsc.service import get_page_metrics

# ✗ 錯誤：_format_row 是內部函式
from modules.gsc.service import _format_row

# ✗ 錯誤：rankings 是 gsc 模組 owner 的 collection
db.collection('rankings').get()
```

---

## 共用邏輯

✓ 兩個模組都需要同一段邏輯 → 搬到 `domain/rules.py`
✗ 不可在兩個模組各自複製同一段邏輯

```python
# ✓ 正確：共用邏輯集中在 domain
from domain.rules import score_dimensions

# ✗ 錯誤：audit 和 optimize 各自維護評分邏輯
def _calculate_score(content):  # 出現在兩個模組
    ...
```

---

## 公開介面定義

- 新增跨模組公開函式 → 同步在 `domain/protocols.py` 加 Protocol 定義
- 刪除跨模組公開函式 → 同步從 `domain/protocols.py` 移除對應定義
- 修改函式簽名（參數、回傳型別）→ 同步更新 `domain/protocols.py`，並確認所有呼叫方也已更新
- 內部函式加 `_` 前綴，不需要定義在 protocols.py
- 每個模組通常只有 2–3 個公開函式

```python
# domain/protocols.py
class GscServiceProtocol(Protocol):
    def get_page_metrics(self, url: str) -> PageMetrics: ...  # 公開
    # _format_row 不需要定義，外部不可呼叫
```

---

## schema.py 隔離

- 每個模組的 `schema.py` 只供自己模組的 `route.py` 使用，不開放給其他模組 import
- 其他模組需要相同資料型別 → 將該型別搬到 `domain/` 下定義，不直接 import 對方的 `schema.py`

```python
# ✓ 正確：共用型別定義在 domain
from domain.types import PageMetrics

# ✗ 錯誤：跨模組 import 對方的 schema
from modules.gsc.schema import GscResponse
```

---

## route.py 邊界

- `route.py` 只能呼叫**自己模組**的 `service.py`，不可直接呼叫其他模組的 `route.py`
- 需要其他模組的資料 → 由自己的 `service.py` 呼叫對方模組的公開函式，不在 route 層跨模組

```python
# ✓ 正確：route 只呼叫自己的 service
# modules/optimize/route.py
from modules.optimize.service import get_suggestion

# ✗ 錯誤：route 直接呼叫其他模組的 route 或 service
from modules.gsc.route import fetch_data
from modules.gsc.service import get_page_metrics  # 應由 optimize/service 呼叫
```

---

## infra 邊界

- 外部服務（Firestore、OpenAI API 等）只能在 `infra/` 層初始化
- 模組內部（`route.py`、`service.py`）不可各自初始化外部服務 client

```python
# ✓ 正確：透過 infra 層存取
from infra.firestore import get_user
from infra.llm_client import call_llm

# ✗ 錯誤：在 service 或 route 內各自初始化
import firebase_admin  # 寫在 modules/xxx/service.py 裡
db = firestore.client()
```

---

## 新增功能

✓ 新增功能 → 在該模組資料夾內新增檔案
✓ 改一個模組的內部實作 → 不需要修改其他模組
✗ 不可為了新功能修改其他模組的 service.py
