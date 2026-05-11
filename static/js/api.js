// ScriptFlow — 所有 fetch 唯一入口 (rule-frontend)
//
// 規則：
//   - 一般 API timeout 10 秒；LLM 端點不設 timeout（rule-frontend）
//   - 統一 response 解析：成功回 data，失敗拋 ApiError(error.code, error.message)
//   - 401 統一拋 AuthRequiredError，common.js 攔截後彈登入

const DEFAULT_TIMEOUT_MS = 10_000;
const LLM_TIMEOUT_MS = 0; // 0 = no timeout

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export class AuthRequiredError extends ApiError {
  constructor(message = "authentication required") {
    super("UNAUTHORIZED", message, 401);
  }
}

async function _fetch(method, url, { body = null, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;

  let res;
  try {
    res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : null,
      credentials: "same-origin", // 帶 session cookie
      signal: controller ? controller.signal : undefined,
    });
  } catch (e) {
    if (timer) clearTimeout(timer);
    if (e.name === "AbortError") {
      throw new ApiError("TIMEOUT", "request timed out", 0);
    }
    throw new ApiError("NETWORK_ERROR", e.message || "network error", 0);
  }
  if (timer) clearTimeout(timer);

  let payload = null;
  try {
    payload = await res.json();
  } catch {
    // 非 JSON（如 storyboard export 的 docx）— 直接回 raw response
    if (res.ok) return res;
  }

  if (!res.ok) {
    const code = payload?.error?.code || `HTTP_${res.status}`;
    const msg = payload?.error?.message || res.statusText;
    if (res.status === 401) throw new AuthRequiredError(msg);
    throw new ApiError(code, msg, res.status);
  }
  // 成功 response 統一是 {data: ..., error: null}
  return payload?.data ?? payload;
}

// --- Auth ---
export const login = (password) => _fetch("POST", "/api/v1/auth/login", { body: { password } });
export const logout = () => _fetch("POST", "/api/v1/auth/logout");
export const healthAuth = () => _fetch("GET", "/api/v1/health");

// --- Candidates ---
export const getCandidates = ({ category, strategy = "balanced" } = {}) => {
  const qs = new URLSearchParams({ strategy });
  if (category) qs.set("category", category);
  return _fetch("GET", `/api/v1/candidates?${qs}`);
};

export const getRecentCandidates = ({ days = 5, category, strategy = "balanced" } = {}) => {
  const qs = new URLSearchParams({ days: String(days), strategy });
  if (category) qs.set("category", category);
  return _fetch("GET", `/api/v1/candidates/recent?${qs}`);
};

export const addManualCandidate = ({ platform, category, title, url, engagement = 0 }) =>
  _fetch("POST", "/api/v1/candidates/manual", {
    body: { platform, category, title, url, engagement },
  });

// --- Crawler ---
export const triggerCrawler = ({ category, strategy = "balanced", hours = 24 }) =>
  _fetch("POST", "/api/v1/crawler/trigger", { body: { category, strategy, hours }, timeoutMs: 60_000 });

// --- Script (LLM 端點，無 timeout) ---
export const generateScript = ({
  candidate_ids,
  category,
  script_type = "traffic",
  selected_item_index = null,
}) => {
  const body = { candidate_ids, category, script_type };
  if (selected_item_index !== null && selected_item_index !== undefined) {
    body.selected_item_index = selected_item_index;
  }
  return _fetch("POST", "/api/v1/script/generate", {
    body,
    timeoutMs: LLM_TIMEOUT_MS,
  });
};

// --- Storyboard (LLM 端點，無 timeout) ---
export const generateStoryboard = ({ script_id, platform }) =>
  _fetch("POST", "/api/v1/storyboard/generate", { body: { script_id, platform }, timeoutMs: LLM_TIMEOUT_MS });

// --- Tracking ---
export const saveTracking = ({ script_id, platform, publish_url }) =>
  _fetch("POST", "/api/v1/tracking", { body: { script_id, platform, publish_url } });

export const getMetrics = (tracking_id) =>
  _fetch("GET", `/api/v1/tracking/${encodeURIComponent(tracking_id)}/metrics`);

export const updateMetrics = ({ tracking_id, metrics_field, metrics }) =>
  _fetch("POST", `/api/v1/tracking/${encodeURIComponent(tracking_id)}/metrics`, {
    body: { metrics_field, metrics },
  });

// AI 看數據給建議（LLM 端點，無 timeout）
export const getFeedback = (tracking_id) =>
  _fetch("POST", `/api/v1/tracking/${encodeURIComponent(tracking_id)}/feedback`, {
    timeoutMs: LLM_TIMEOUT_MS,
  });

export const getDna = () => _fetch("GET", "/api/v1/tracking/dna");

// --- Scheduler ---
export const getSchedulerStatus = () => _fetch("GET", "/api/v1/scheduler/status");
