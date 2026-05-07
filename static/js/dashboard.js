// ScriptFlow — Tab 1 候選 + Tab 2 腳本/分鏡

import {
  generateScript,
  generateStoryboard,
  getCandidates,
  getRecentCandidates,
  triggerCrawler,
} from "/static/js/api.js";
import {
  clearStatus,
  handleApiError,
  isAuthed,
  onAuthChange,
  setStatus,
  toast,
} from "/static/js/common.js";

// --- 共用 state（簡單，不用框架） ---

let lastCandidate = null;       // 最近一次 candidates response
let lastScript = null;          // 最近一次生成的 script (含三版本)
let selectedItemContext = null; // {candidate_id, item_index, category, title} - 從卡片點選的單篇


// --- Helpers ---

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function fmtNumber(n) {
  if (typeof n !== "number") return "?";
  return n.toLocaleString();
}

// 漏斗角色中文化（與 domain/rules.py FUNNEL_ROLES 對齊：5 階段購買旅程）
const FUNNEL_ROLE_LABEL = {
  awareness: "認知",          // 純爆款引發注意
  interest: "興趣",           // 觀眾注意此類產品
  evaluation: "評估比價",     // 主題深入但無強購買訊號
  brand_value: "看見品牌價值", // 主題相關 + 中等導購意味
  decision: "決策",           // 強烈購買訊號
  // 舊資料向下相容（Firestore 既有 docs 用 seed/pull/harvest）
  seed: "認知",
  pull: "興趣",
  harvest: "決策",
};

// CTA 類型中文化
const CTA_TYPE_LABEL = {
  story_link: "限動連結",
  dm_keyword: "私訊關鍵字",
  comment_engage: "留言互動",
};

// 平台中文化
const PLATFORM_LABEL = {
  douyin: "抖音",
  xiaohongshu: "小紅書",
  threads: "Threads",
  threads_post: "Threads 純文字",
  threads_reel: "脆 30 秒",
  ig_reels: "IG Reels 60 秒",
};


// --- Candidates Tab ---

function _formatDateZh(iso) {
  // "2026-05-07" → "2026/5/7（週四）"
  if (!iso) return "?";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  const weekday = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}（週${weekday}）`;
}

function _isToday(iso) {
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return iso === todayIso;
}

function renderRecentCandidates(payload) {
  const list = document.getElementById("candidates-list");
  const meta = document.getElementById("candidates-meta");
  clear(list);
  clear(meta);

  if (!payload || !Array.isArray(payload.buckets)) {
    list.appendChild(el("div", null, "(無資料)"));
    return;
  }

  meta.appendChild(el("span", null,
    `顯示最近 ${payload.days} 天的候選（每天保留，超過 ${payload.days} 天會自動清除）`
  ));

  // 把所有 docs 攤平成「最後一次設定 lastCandidate」用，方便舊邏輯相容
  const allDocs = payload.buckets.flatMap((b) => b.docs || []);
  if (allDocs.length === 0) {
    list.appendChild(el("div", null, "(這 5 天還沒爬到候選，按「觸發爬取」開始)"));
    return;
  }
  // 預設 lastCandidate 取最新一天的第一個 doc，方便「重新生成」按鈕仍可用
  lastCandidate = allDocs[0];

  let renderedAny = false;
  for (const bucket of payload.buckets) {
    if (!bucket.docs || bucket.docs.length === 0) continue;
    renderedAny = true;
    const section = el("div", "day-section");
    const header = el("div", "day-section__header");
    header.appendChild(el("span", "day-section__date", _formatDateZh(bucket.date)));
    if (_isToday(bucket.date)) {
      header.appendChild(el("span", "day-section__today", "今天"));
    }
    section.appendChild(header);

    for (const doc of bucket.docs) {
      const docHead = el("div", "day-section__doc-meta");
      docHead.textContent = `分類：${doc.category || "?"}｜主題：${doc.topic || "(無)"}`;
      section.appendChild(docHead);

      const cardsRow = el("div", "cards");
      (doc.items || []).forEach((item, idx) => {
        cardsRow.appendChild(_renderCandidateCard(item, doc, idx));
      });
      section.appendChild(cardsRow);
    }
    list.appendChild(section);
  }
  if (!renderedAny) {
    list.appendChild(el("div", null, "(這 5 天還沒爬到候選)"));
  }

  // 只要有候選就 enable 腳本生成按鈕
  const btn = document.getElementById("script-generate");
  if (btn) {
    btn.disabled = false;
    if (!selectedItemContext) {
      btn.textContent = "用最新候選（全部 3 篇）生成腳本";
    }
  }
}

function _renderCandidateCard(item, doc, idx) {
  const card = el("div", "cand");
  const platformZh = PLATFORM_LABEL[item.platform] || item.platform || "?";
  card.appendChild(el("div", "cand__rank", `#${item.rank ?? idx + 1} · ${platformZh}`));
  card.appendChild(el("div", "cand__title", item.title || "(無標題)"));
  const metaRow = el("div", "cand__meta");
  metaRow.appendChild(el("span", null, `互動數 ${fmtNumber(item.engagement)}`));
  metaRow.appendChild(el("span", null, `主題符合度 ${item.topic_match ?? "?"}`));
  metaRow.appendChild(el("span", null, `購買意圖 ${item.purchase_intent_density ?? "?"}`));
  card.appendChild(metaRow);

  if (item.funnel_role) {
    const roleLabel = FUNNEL_ROLE_LABEL[item.funnel_role] || item.funnel_role;
    card.appendChild(el("span", `cand__role cand__role--${item.funnel_role}`, roleLabel));
  }

  // 「用此篇生成腳本」按鈕
  const btn = el("button", "btn btn--secondary cand__pick", "用此篇生成腳本");
  btn.type = "button";
  btn.addEventListener("click", () => {
    _onPickCandidate({
      candidate_id: doc.id,
      category: doc.category,
      item_index: idx,
      title: item.title,
      date: doc.date,
    });
  });
  card.appendChild(btn);

  return card;
}

function _onPickCandidate(ctx) {
  selectedItemContext = ctx;
  // 切到 Tab 2
  document.querySelector('.tabs__btn[data-tab="script"]')?.click();

  // 顯示「已選擇」訊息（在腳本 status 區）
  setStatus(
    "script-status",
    "loading",
    `已選擇 ${ctx.date}「${(ctx.title || "").slice(0, 30)}」，自動生成腳本中…`
  );
  const genBtn = document.getElementById("script-generate");
  if (genBtn) {
    genBtn.textContent = `用「${(ctx.title || "").slice(0, 20)}…」重新生成`;
  }

  // 自動觸發生成
  doGenerateScript();
}

async function loadCandidates() {
  const category = document.getElementById("candidates-category").value;
  setStatus("candidates-status", "loading", "載入中…");
  try {
    const payload = await getRecentCandidates({ days: 5, category });
    renderRecentCandidates(payload);
    setStatus("candidates-status", "success", "");
  } catch (e) {
    handleApiError(e);
    setStatus("candidates-status", "error", e.message || "載入失敗");
  }
}

async function triggerCrawlerAndReload() {
  const category = document.getElementById("candidates-category").value;
  const strategy = document.getElementById("candidates-strategy").value;
  const btn = document.getElementById("candidates-trigger");
  if (btn) btn.disabled = true;
  setStatus("candidates-status", "loading", "爬取中（最多 60s）…");
  try {
    await triggerCrawler({ category, strategy });
    toast("爬取完成", "success");
    await loadCandidates();
  } catch (e) {
    handleApiError(e);
    setStatus("candidates-status", "error", e.message || "爬取失敗");
  } finally {
    if (btn) btn.disabled = false;
  }
}


// --- Script Tab ---

function renderScript(script) {
  const root = document.getElementById("script-content");
  clear(root);
  if (!script) return;

  const header = el("div", "meta",
    `腳本 ID：${script.script_id} ｜ 分類：${script.category} ｜ 主題：${script.topic || "(無)"}`);
  root.appendChild(header);

  const versionMap = [
    ["threads_post", "Threads 純文字貼文"],
    ["threads_reel", "脆 30 秒口播"],
    ["ig_reels", "IG Reels 60 秒"],
  ];
  for (const [key, label] of versionMap) {
    const v = script[key];
    if (!v) continue;
    const card = el("div", "script__version");
    card.appendChild(el("h3", "script__h", label));

    // 主要內容（content 或 segments）
    const body = el("div", "script__body");
    if (v.content) {
      body.textContent = v.content;
    } else if (Array.isArray(v.segments)) {
      const lines = v.segments.map((s) =>
        `[${s.time || "?"}] ${s.scene || ""}\n  口白：${s.voiceover || ""}\n  音效：${s.sfx || ""}`
      );
      if (v.caption) lines.push(`\n📝 說明文字：${v.caption}`);
      if (Array.isArray(v.hashtags)) lines.push(`#${v.hashtags.join(" #")}`);
      body.textContent = lines.join("\n\n");
    }
    card.appendChild(body);

    // CTA 三變體
    if (Array.isArray(v.cta_variants) && v.cta_variants.length) {
      const cta = el("div", "script__cta");
      for (const c of v.cta_variants) {
        const typeLabel = CTA_TYPE_LABEL[c.type] || c.type;
        cta.appendChild(el("div", "script__cta-item", `[${typeLabel}] ${c.text}`));
      }
      card.appendChild(cta);
    }

    // 合規結果
    const hits = v.compliance || [];
    const comp = el("div", `script__compliance script__compliance--${hits.length ? "hits" : "clean"}`);
    if (hits.length === 0) {
      comp.textContent = "✓ 合規掃描通過";
    } else {
      comp.appendChild(el("span", null, "⚠ 違規詞："));
      for (const h of hits) {
        const tag = el("span", "script__hit");
        tag.textContent = `${h.word} → ${h.suggest}（${h.reason}）`;
        comp.appendChild(tag);
      }
    }
    card.appendChild(comp);

    root.appendChild(card);
  }
}

async function doGenerateScript() {
  let candidateIds, category, selectedItemIndex;

  if (selectedItemContext) {
    // 由「用此篇生成腳本」觸發
    candidateIds = [selectedItemContext.candidate_id];
    category = selectedItemContext.category;
    selectedItemIndex = selectedItemContext.item_index;
  } else {
    // 用 lastCandidate（最新一天的 doc）裡的全部 items
    if (!lastCandidate) {
      toast("先載入候選", "error");
      return;
    }
    candidateIds = lastCandidate.id
      ? [lastCandidate.id]
      : (lastCandidate.items || []).map((d) => d.id).filter(Boolean);
    if (candidateIds.length === 0) {
      toast("找不到 candidate id", "error");
      return;
    }
    category = lastCandidate.category || document.getElementById("candidates-category").value;
    selectedItemIndex = null;
  }

  const scriptType = document.getElementById("script-type")?.value || "traffic";

  const btn = document.getElementById("script-generate");
  if (btn) { btn.disabled = true; btn.textContent = "生成中（30-60 秒）…"; }
  const scopeLabel = selectedItemIndex !== null ? "單篇" : "三篇彙整";
  setStatus("script-status", "loading", `正在產三版本（${scopeLabel}，脆＝${scriptType}）…`);
  try {
    const payload = { candidate_ids: candidateIds, category, script_type: scriptType };
    if (selectedItemIndex !== null) payload.selected_item_index = selectedItemIndex;
    const data = await generateScript(payload);
    lastScript = data;
    renderScript(data);
    setStatus("script-status", "success", `已生成 ${data.script_id}`);
    document.getElementById("storyboard-card").hidden = false;
  } catch (e) {
    handleApiError(e);
    setStatus("script-status", "error", e.message || "生成失敗");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = selectedItemContext ? "重新生成（單篇）" : "重新生成（三篇彙整）";
    }
  }
}


// --- Storyboard ---

function renderStoryboard(sb) {
  const root = document.getElementById("storyboard-list");
  clear(root);
  if (!sb || !Array.isArray(sb.scenes)) return;

  for (const s of sb.scenes) {
    const node = el("div", "scene");
    if (s.image_data_url) {
      const img = document.createElement("img");
      img.className = "scene__img";
      img.loading = "lazy"; // rule-frontend
      img.alt = `鏡頭 ${s.index || ""}`;
      img.src = s.image_data_url;
      node.appendChild(img);
    } else {
      node.appendChild(el("div", "scene__img"));
    }
    node.appendChild(el("div", "scene__index", `鏡頭 ${s.index || "?"} · ${s.time || ""}`));
    const text = el("div", "scene__text");
    const sceneP = el("p", null);
    sceneP.appendChild(el("strong", null, "畫面："));
    sceneP.appendChild(document.createTextNode(s.scene || ""));
    text.appendChild(sceneP);
    const voP = el("p", null);
    voP.appendChild(el("strong", null, "口白："));
    voP.appendChild(document.createTextNode(s.voiceover || ""));
    text.appendChild(voP);
    node.appendChild(text);

    if (s.product_exposure) {
      node.appendChild(el("div", "scene__exposure", s.product_exposure));
    }
    root.appendChild(node);
  }
}

async function doGenerateStoryboard(platform) {
  if (!lastScript) {
    toast("先生成腳本", "error");
    return;
  }
  setStatus("storyboard-status", "loading", "產分鏡中（30-90 秒）…");
  try {
    const sb = await generateStoryboard({ script_id: lastScript.script_id, platform });
    renderStoryboard(sb);
    setStatus("storyboard-status", "success", `${sb.scenes.length} 鏡頭就緒`);
  } catch (e) {
    handleApiError(e);
    setStatus("storyboard-status", "error", e.message || "分鏡生成失敗");
  }
}


// --- Init ---

function setup() {
  document.getElementById("candidates-refresh")?.addEventListener("click", loadCandidates);
  document.getElementById("candidates-trigger")?.addEventListener("click", triggerCrawlerAndReload);
  document.getElementById("script-generate")?.addEventListener("click", doGenerateScript);
  document.querySelectorAll(".storyboard-platform").forEach((btn) => {
    btn.addEventListener("click", () => doGenerateStoryboard(btn.dataset.platform));
  });
  // 切分類或策略 → 自動重新載入候選
  document.getElementById("candidates-category")?.addEventListener("change", loadCandidates);
  document.getElementById("candidates-strategy")?.addEventListener("change", loadCandidates);
}

document.addEventListener("DOMContentLoaded", () => {
  setup();
  // 登入後自動載入候選
  onAuthChange(async (authed) => {
    if (authed) {
      try { await loadCandidates(); } catch { /* 沒資料無妨 */ }
    }
  });
  if (isAuthed()) loadCandidates();
});
