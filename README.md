# ScriptFlow — 短影音變現操盤台

> 從爆款探索 → 腳本生成 → 分鏡示意 → 成效追蹤的一條龍工作流。

## 目前狀態

Phase 0：開發文件籌備完成，尚未進入程式碼實作。

## 文件入口

- 執行入口：[`CLAUDE.md`](./CLAUDE.md)
- 產品需求：[`docs/spec-user.md`](./docs/spec-user.md)
- 開發規格：[`docs/spec-developer.md`](./docs/spec-developer.md)
- 系統架構：[`docs/architecture.md`](./docs/architecture.md)
- 開發順序：[`docs/dev-order.md`](./docs/dev-order.md)

詳細索引見 [`CLAUDE.md`](./CLAUDE.md) 文件索引章節。

## 技術棧

| 層級 | 技術 |
|---|---|
| 前端 | HTML + CSS + 原生 JS |
| 後端 | Python 3.12 + FastAPI |
| 資料庫 | Firestore |
| 部署 | GCP Cloud Run |
| AI | OpenAI GPT-5-mini + gpt-image-1 |

## 安全注意

- 所有 secret 透過環境變數或 GCP Secret Manager 管理，絕不 hardcode
- `.env`、`.claude/settings.local.json` 已加入 `.gitignore`
- 敏感操作走後端 proxy，前端不直接呼叫第三方 API
