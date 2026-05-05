---
paths: "**/*"
---

# Vibe Coding 安全防護規則

> 你（Claude Code）在產生程式碼時，經常會犯以下錯誤。
> 這些不是理論，是 AI 輔助開發（Vibe Coding）最常見的真實漏洞。
> 每次寫程式碼時自動檢查，不要等人提醒。

---

## 你常犯的不安全程式碼模式

| 你可能會寫的 | 為什麼危險 | 應該改成 |
|-------------|-----------|---------|
| `eval(user_input)` | 使用者輸入被當成程式碼執行，攻擊者可以在你的伺服器上跑任意指令 | 永遠不要 eval 使用者輸入 |
| `os.system(f"ping {ip}")` | 使用者在 ip 欄位輸入 `; rm -rf /` 就會刪除整台伺服器的檔案 | `subprocess.run(["ping", ip])` |
| `f"SELECT * FROM users WHERE id = {id}"` | 使用者輸入 `1 OR 1=1` 就能看到所有人的資料 | 用 ORM 或參數化查詢 |
| `pickle.loads(user_data)` | 攻擊者可以透過 pickle 資料在伺服器上執行任意程式碼 | 用 JSON 或 protobuf |
| `yaml.load(data)` | 跟 pickle 一樣危險，可以執行任意程式碼 | `yaml.safe_load(data)` |
| `jwt.decode(token, options={"verify_signature": False})` | 等於不驗證 Token，任何人都能偽造身份 | 永遠驗證簽名 |
| `render_template_string(user_input)` | 使用者輸入 `{{config}}` 就能看到伺服器所有設定和密鑰 | `render_template()` |
| `CORS(app, origins="*", supports_credentials=True)` | 任何網站都能以使用者身份呼叫你的 API，偷取使用者資料 | 限定允許的 Origin |
| `app.run(debug=True)` 在生產環境 | 任何人觸發錯誤就能看到完整程式碼、環境變數、甚至直接執行指令 | `debug=False` |
| `open(f"/uploads/{filename}")` 無路徑檢查 | 使用者傳 `../../etc/passwd` 就能讀取伺服器密碼檔 | `secure_filename()` + 路徑驗證 |
| `password = hashlib.md5(pwd).hexdigest()` | MD5 幾秒鐘就能被破解，等於明文儲存密碼 | `bcrypt.hashpw()` |
| `SECRET_KEY = "mysecret"` 硬編碼 | 推上 GitHub 全世界都能看到，攻擊者可以偽造所有 Token | 用環境變數 `os.environ["SECRET_KEY"]` |
| `requests.get(user_url)` 無 IP 限制 | 攻擊者傳內部 IP 就能偷取雲端金鑰或存取內網 | 驗證 URL 不指向：`169.254.169.254`、`localhost`、`127.0.0.1`、`0.0.0.0`、`10.x`、`172.16.x`、`192.168.x`、IPv6 的 `::1` 和 `::ffff:*` |
| `innerHTML = userContent` | 使用者輸入的 HTML/JS 會直接執行，可以偷走所有人的登入狀態 | `textContent` 或用 DOMPurify 淨化 |
| `dangerouslySetInnerHTML={{__html: data}}` | 跟 innerHTML 一樣危險，React 特意命名「dangerously」就是在警告你 | 避免使用，必要時先用 DOMPurify |
| `v-html="userContent"` | Vue 版本的 innerHTML，一樣危險 | 用 `{{ }}` 插值（自動 escape） |

---

## 你安裝套件時必須做的事

- **安裝前確認套件名稱拼寫正確**，攻擊者會發布拼錯名的惡意套件（如 `reqeusts`、`djano`）
- 安裝前用 PyPI 官網確認：發布者是否可信、版本數量是否合理、README 是否正常
- 不安裝功能重疊的替代套件，先確認已有套件無法滿足需求再新增
- **新增套件前告知使用者，等確認再安裝**（對應 CLAUDE.md 工作原則）

---

## 你寫 API 時必須做的事

- **每個對外公開的 API 端點都要有 Rate Limiting**，登入、密碼重設、OTP 驗證端點尤其必須
  - Rate Limiting 計數器存在 server 端，不信任 client 傳來的 IP header（X-Forwarded-For 可偽造）
  - 沒有 Rate Limiting → 攻擊者無限次暴力破解或耗盡 LLM API 費用
- **每個 API 端點都要有認證檢查**（middleware / decorator），不是只有前端判斷
  - 錯誤示範：前端隱藏管理員按鈕，但 API 沒有檢查角色
  - 後果：任何人用 curl 就能呼叫管理員 API
- **每個 API 端點都要有授權檢查**，確認「這個使用者有沒有權限操作這筆資料」
  - 錯誤示範：只檢查 Token 有效，沒檢查 user_id 是不是自己的
  - 後果：使用者 A 可以讀取/刪除使用者 B 的資料
- **CORS 設定限定實際的前端域名**，不是 `*`
  - 後果：設 `*` 等於任何網站都能代替使用者呼叫你的 API
- **所有使用者輸入在後端都要驗證和淨化**，不能只靠前端
  - 前端驗證是為了使用者體驗，後端驗證是為了安全
  - 攻擊者會繞過前端直接打 API

---

## 你處理機密資料時必須做的事

- **所有 Secret / API Key 使用環境變數**，不寫在程式碼裡
  - 寫在程式碼裡 → 推上 Git → 全世界都能看到 → 你付帳單
- **.env 檔案加入 .gitignore**
  - 忘記加 → `.env` 被推上 GitHub → 所有密鑰洩漏
- **API Key 只放在後端**，前端不直接呼叫第三方 API
  - 前端 JS 是公開的，任何人都能看到裡面的 Key
- **Log 中不記錄敏感資料**（Token、密碼、API Key）
  - Log 通常權限較寬鬆，洩漏風險高

---

## 你部署時必須做的事

- **關閉 Debug 模式**（`DEBUG=False`、`debug=False`）
- **關閉 API 文件頁面**（FastAPI 的 `/docs`、`/redoc`、`/openapi.json`）
- **移除前端 Source Map**（`.map` 檔案讓人能還原你的完整原始碼）
- **設定安全標頭**（CSP、X-Frame-Options、HSTS、X-Content-Type-Options）
  - 沒設 → XSS 更容易成功、網站可被 iframe 嵌入劫持點擊
- **HTTPS 強制啟用**
- **Docker 不以 root 執行**
  - root 執行 → 容器被攻破就等於伺服器被攻破

---

## 你處理檔案上傳時必須做的事

- **用白名單限制允許的檔案類型**（只接受 jpg/png/gif/webp），不是黑名單
- **檢查實際 MIME type**，不要只看副檔名
  - 攻擊者把 `.html` 改名成 `.png` 就能繞過副檔名檢查
- **設定檔案大小上限**
  - 沒限制 → 攻擊者上傳 1GB 檔案讓你的伺服器記憶體耗盡
- **清理檔名**（用 `secure_filename()` 或自己生成 UUID 檔名）
  - 攻擊者傳 `../../../etc/crontab` 當檔名，可能覆蓋伺服器系統檔案
- **不要把上傳的檔案存在 Web Root 裡面**
  - 存在 Web Root → 攻擊者上傳 PHP/HTML 後直接存取執行

---

## 與 CLAUDE.md 交付前檢查的關係

兩份清單各有側重，**都要跑**：
- **CLAUDE.md 交付前檢查**：架構品質（lint、測試、schema、scope）
- **本清單（下方）**：安全防護（認證、加密、注入、部署）

先跑 CLAUDE.md 清單，再跑本清單。

## 你每次交付前跑一遍的自檢

```
□ 所有 API 端點都有認證檢查
□ 所有 API 端點都有授權檢查（不是只有前端判斷）
□ CORS 設定限定為實際的前端域名，不是 *
□ JWT 使用強密鑰（≥256 bit），有設定過期時間
□ 資料庫查詢使用 ORM 或參數化查詢，無字串拼接
□ 使用者輸入在後端有驗證與淨化
□ 檔案上傳有檢查類型、大小、內容
□ 密碼使用 bcrypt/argon2 雜湊，不是 MD5/SHA1/明文
□ 所有 Secret/API Key 使用環境變數，不在程式碼中
□ .env 已加入 .gitignore
□ DEBUG 模式已關閉
□ API 文件頁面（/docs、/redoc）在生產環境已關閉
□ .git 目錄不暴露在 Web 上
□ Source Map 已移除
□ 安全標頭已設定（CSP、X-Frame-Options、HSTS）
□ HTTPS 已啟用
□ Docker 不以 root 執行
□ pip-audit 無 Critical/High 漏洞
```
