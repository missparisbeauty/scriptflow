"""一次性 Firestore collection 初始化 helper。

執行方式：
    # 本機需先 gcloud auth application-default login
    python scripts/init_firestore.py

行為：
    對每個 collection 寫入再刪掉一筆 _placeholder doc，確認可讀寫權限。
    Firestore collection 在第一次寫入時會自動建立，所以這個 script
    主要是「煙霧測試」，不會在線上資料中留下痕跡。
"""

from __future__ import annotations

import os
import sys

from google.cloud import firestore

COLLECTIONS = ("candidates", "scripts", "tracking", "brand_dna")


def main() -> int:
    project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("ERROR: 請設定 GCP_PROJECT_ID 或 GOOGLE_CLOUD_PROJECT", file=sys.stderr)
        return 1

    db = firestore.Client(project=project)
    for col in COLLECTIONS:
        ref = db.collection(col).document("_placeholder")
        ref.set({"_init": True})
        ref.delete()
        print(f"  [OK] {col}")

    print("\nFirestore 4 collections 初始化完成 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
