// ScriptFlow — 跨頁共用：登入態、Tab 切換、排程狀態、Toast
//
// rule-frontend：
//   - 不用 innerHTML 渲染使用者輸入或 API 內容（用 textContent / 元件函式）
//   - 不在 scroll/resize 做重計算
//   - 用 alert() 取代為 toast()

import {
  ApiError,
  AuthRequiredError,
  getSchedulerStatus,
  healthAuth,
  logout,
} from "/static/js/api.js";

// --- Toast ---

export function toast(message, kind = "info", durationMs = 3000) {
  const root = document.getElementById("toast-container");
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast toast--${kind}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), durationMs);
}

// --- 全域錯誤攔截：未登入彈出登入畫面 ---

export function handleApiError(e, fallbackMsg = "操作失敗") {
  if (e instanceof AuthRequiredError) {
    showLogin();
    toast("請重新登入", "error");
    return;
  }
  const msg = e instanceof ApiError ? `${e.code}: ${e.message}` : (e.message || fallbackMsg);
  toast(msg, "error", 5000);
  console.error("API error", e);
}

// --- Status helper ---

export function setStatus(elId, kind, message) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `status status--${kind}`;
  el.textContent = message || "";
}

export function clearStatus(elId) {
  const el = document.getElementById(elId);
  if (el) {
    el.className = "status";
    el.textContent = "";
  }
}

// --- 登入 / 登出 ---

const _listeners = new Set();
let _isAuthed = false;

export function onAuthChange(fn) { _listeners.add(fn); }
export function isAuthed() { return _isAuthed; }

function _notifyAuth(authed) {
  _isAuthed = authed;
  _listeners.forEach((fn) => { try { fn(authed); } catch (e) { console.error(e); } });
}

function showLogin() {
  document.getElementById("login-modal")?.removeAttribute("hidden");
  document.getElementById("main")?.setAttribute("hidden", "");
  _notifyAuth(false);
}

function showApp() {
  document.getElementById("login-modal")?.setAttribute("hidden", "");
  document.getElementById("main")?.removeAttribute("hidden");
  _notifyAuth(true);
}

// 從 URL ?auth_error=xxx 讀錯誤代碼，顯示給使用者
function _showAuthErrorFromUrl() {
  const url = new URL(window.location.href);
  const err = url.searchParams.get("auth_error");
  if (!err) return;
  const errorEl = document.getElementById("login-error");
  if (!errorEl) return;
  const labels = {
    not_authorized: "你的 GitHub 帳號沒有登入權限。請聯絡管理員加入白名單。",
    state_mismatch: "登入流程被中斷（state 不匹配）。請重試。",
    state_cookie_missing: "瀏覽器 cookie 被擋。請允許 cookie 後重試。",
    missing_code_or_state: "登入流程不完整。請重試。",
    token_exchange_failed: "GitHub token 換取失敗。請稍後再試。",
    fetch_user_failed: "無法取得 GitHub 使用者資料。請重試。",
    github_denied: "你拒絕了 GitHub 授權。",
    github_not_configured: "後台尚未設定 GitHub OAuth。",
    no_username: "GitHub 沒回傳 username。",
  };
  errorEl.textContent = labels[err] || `登入失敗：${err}`;
  errorEl.hidden = false;
  // 清掉 query string，避免重新整理時又顯示
  url.searchParams.delete("auth_error");
  window.history.replaceState({}, document.title, url.pathname + url.hash);
}

async function doLogout() {
  try { await logout(); } catch { /* 即使失敗也清狀態 */ }
  showLogin();
  toast("已登出", "info");
}

async function checkSession() {
  try {
    await healthAuth();
    showApp();
    return true;
  } catch (e) {
    showLogin();
    return false;
  }
}

// --- Tab 切換 ---

function setupTabs() {
  const buttons = document.querySelectorAll(".tabs__btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      buttons.forEach((b) => b.classList.toggle("tabs__btn--active", b === btn));
      document.querySelectorAll(".tab").forEach((sec) => {
        sec.classList.toggle("tab--active", sec.id === `tab-${target}`);
      });
    });
  });
}

// --- 排程狀態 (右上角)  ---

async function refreshSchedulerStatus() {
  const el = document.getElementById("scheduler-status");
  if (!el) return;
  try {
    const data = await getSchedulerStatus();
    if (!data.enabled) {
      el.textContent = "排程：未啟用";
      return;
    }
    if (!data.running) {
      el.textContent = "排程：未運行";
      return;
    }
    const next = data.next_run ? new Date(data.next_run) : null;
    el.textContent = next
      ? `下次爬取：${next.toLocaleString("zh-TW", { hour12: false })}`
      : "排程：運行中";
  } catch {
    // 未登入時不顯示
    el.textContent = "";
  }
}

// --- Init ---

function setupForms() {
  document.getElementById("logout-btn")?.addEventListener("click", doLogout);
}

document.addEventListener("DOMContentLoaded", async () => {
  setupForms();
  setupTabs();
  _showAuthErrorFromUrl();
  const authed = await checkSession();
  if (authed) {
    refreshSchedulerStatus();
    // 每 60 秒輕量更新一次
    setInterval(refreshSchedulerStatus, 60_000);
  }
});

// 提供給其他模組
export { showLogin, showApp };
