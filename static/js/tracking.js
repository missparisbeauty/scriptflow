// ScriptFlow — Tab 3 成效 + Tab 4 品牌 DNA

import {
  getDna,
  getMetrics,
  saveTracking,
} from "/static/js/api.js";
import {
  handleApiError,
  setStatus,
  toast,
} from "/static/js/common.js";


function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}


// --- 新增發布記錄 ---

async function onTrackingSubmit(e) {
  e.preventDefault();
  const script_id = document.getElementById("tracking-script-id").value.trim();
  const platform = document.getElementById("tracking-platform").value;
  const publish_url = document.getElementById("tracking-url").value.trim();
  const submit = e.target.querySelector("button[type=submit]");
  if (submit) submit.disabled = true;
  setStatus("tracking-status", "loading", "儲存中…");
  try {
    const data = await saveTracking({ script_id, platform, publish_url });
    toast(`已儲存 ${data.tracking_id}`, "success");
    setStatus("tracking-status", "success", `追蹤 ID：${data.tracking_id}`);
    e.target.reset();
  } catch (err) {
    handleApiError(err);
    setStatus("tracking-status", "error", err.message || "儲存失敗");
  } finally {
    if (submit) submit.disabled = false;
  }
}


// --- 查詢成效 ---

// 平台中文化（與 dashboard.js 同步）
const PLATFORM_LABEL_TR = {
  threads_post: "Threads 純文字",
  threads_reel: "脆 30 秒",
  ig_reels: "IG Reels 60 秒",
};

// 成效時間視窗中文化
const WINDOW_LABEL = {
  metrics_7d: "發布後 7 天",
  metrics_14d: "發布後 14 天",
};

// 成效指標中文化
const METRIC_LABEL = {
  views: "觀看數",
  likes: "按讚",
  comments: "留言",
  shares: "分享",
  saves: "收藏",
  reach: "觸及",
  impressions: "曝光",
  ctr: "點擊率",
  click_through_rate: "點擊率",
  completion_rate: "完看率",
  watch_time: "平均觀看秒數",
  engagement_rate: "互動率",
  conversion_rate: "轉換率",
  product_clicks: "產品點擊",
  story_link_clicks: "限動連結點擊",
  dm_count: "私訊次數",
};

function renderMetrics(data) {
  const root = document.getElementById("metrics-result");
  clear(root);
  if (!data) return;

  const platformZh = PLATFORM_LABEL_TR[data.platform] || data.platform;
  const summary = el("div", "meta", `腳本 ID：${data.script_id} ｜ 平台：${platformZh}`);
  root.appendChild(summary);

  for (const window of ["metrics_7d", "metrics_14d"]) {
    const m = data[window];
    const block = el("div", "metrics");
    const head = el("h4", null, WINDOW_LABEL[window] || window);
    head.style.margin = "12px 0 6px";
    head.style.fontSize = "13px";
    block.appendChild(head);
    if (!m) {
      block.appendChild(el("div", "meta", "(尚未收集)"));
    } else {
      for (const [k, v] of Object.entries(m)) {
        const row = el("div", "metrics__row");
        row.appendChild(el("span", "metrics__label", METRIC_LABEL[k] || k));
        row.appendChild(el("span", null, String(v)));
        block.appendChild(row);
      }
    }
    root.appendChild(block);
  }
}

async function onMetricsSubmit(e) {
  e.preventDefault();
  const id = document.getElementById("metrics-tracking-id").value.trim();
  const submit = e.target.querySelector("button[type=submit]");
  if (submit) submit.disabled = true;
  try {
    const data = await getMetrics(id);
    renderMetrics(data);
  } catch (err) {
    handleApiError(err);
    clear(document.getElementById("metrics-result"));
  } finally {
    if (submit) submit.disabled = false;
  }
}


// --- DNA ---

function renderDna(dna) {
  const root = document.getElementById("dna-result");
  clear(root);
  if (!dna) return;

  const sample = el("div", "meta", `樣本數：${dna.sample_count ?? "?"}`);
  root.appendChild(sample);

  const items = [
    ["best_opening", "最佳開場", "avg_completion_rate", "完看率"],
    ["best_cta", "最佳 CTA", "avg_ctr", "點擊率"],
    ["best_product_timing", "最佳產品露出", "conversion_multiplier", "轉換倍率"],
  ];

  const grid = el("div", "dna");
  for (const [key, label, metricKey, metricLabel] of items) {
    const item = dna[key];
    if (!item) continue;
    const card = el("div", "dna__item");
    card.appendChild(el("h3", "dna__h", label));
    card.appendChild(el("div", "dna__template", item.template || item.position || JSON.stringify(item)));
    if (item[metricKey] != null) {
      card.appendChild(el("div", "dna__metric", `${metricLabel}：${item[metricKey]}`));
    }
    if (item.context) {
      card.appendChild(el("div", "dna__metric", `情境：${item.context}`));
    }
    grid.appendChild(card);
  }
  root.appendChild(grid);
}

async function onDnaRefresh() {
  const btn = document.getElementById("dna-refresh");
  if (btn) btn.disabled = true;
  setStatus("dna-status", "loading", "計算中…");
  try {
    const dna = await getDna();
    renderDna(dna);
    setStatus("dna-status", "success", `已產生 ${dna.id}`);
  } catch (err) {
    if (err.code === "INSUFFICIENT_DATA") {
      setStatus("dna-status", "error", "需更多作品（至少 5 支有 7 天成效）");
    } else {
      handleApiError(err);
      setStatus("dna-status", "error", err.message || "計算失敗");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}


// --- Init ---

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("tracking-form")?.addEventListener("submit", onTrackingSubmit);
  document.getElementById("metrics-form")?.addEventListener("submit", onMetricsSubmit);
  document.getElementById("dna-refresh")?.addEventListener("click", onDnaRefresh);
});
