// ScriptFlow — Tab 1 候選 + Tab 2 腳本/分鏡

import {
  generateScript,
  generateStoryboard,
  getCandidates,
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

let lastCandidate = null; // 最近一次 candidates response
let lastScript = null;    // 最近一次生成的 script (含三版本)


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

// 漏斗角色中文化（與 domain/rules.py FUNNEL_ROLES 對齊：3 個角色）
const FUNNEL_ROLE_LABEL = {
  seed: "種子",      // 種草／品牌印象
  pull: "拉新",      // 引流／吸引點擊
  harvest: "變現",   // 收割／轉換成交
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

function renderCandidates(doc) {
  const list = document.getElementById("candidates-list");
  const meta = document.getElementById("candidates-meta");
  clear(list);
  clear(meta);

  if (!doc) return;

  // 兼容兩種 response：依 category 帶會回單筆 doc，否則回 {date, items: [...]}
  const cards = doc.items || [];
  const isCategoryDoc = doc.category != null;
  const items = isCategoryDoc ? cards : (cards[0]?.items || []);

  if (isCategoryDoc) {
    meta.appendChild(el("span", null,
      `主題：${doc.topic || "(無)"} | 集中度：${doc.topic_concentration ?? "?"} | 失敗平台：${(doc.failed_platforms || []).join(",") || "無"}`
    ));
  }

  if (items.length === 0) {
    list.appendChild(el("div", null, "(無候選)"));
    return;
  }

  for (const item of items) {
    const card = el("div", "cand");
    const platformZh = PLATFORM_LABEL[item.platform] || item.platform || "?";
    card.appendChild(el("div", "cand__rank", `#${item.rank ?? "?"} · ${platformZh}`));
    card.appendChild(el("div", "cand__title", item.title || "(無標題)"));
    const metaRow = el("div", "cand__meta");
    metaRow.appendChild(el("span", null, `互動數 ${fmtNumber(item.engagement)}`));
    metaRow.appendChild(el("span", null, `主題符合度 ${item.topic_match ?? "?"}`));
    metaRow.appendChild(el("span", null, `購買意圖 ${item.purchase_intent_density ?? "?"}`));
    card.appendChild(metaRow);

    if (item.funnel_role) {
      const roleLabel = FUNNEL_ROLE_LABEL[item.funnel_role] || item.funnel_role;
      const role = el("span", `cand__role cand__role--${item.funnel_role}`, roleLabel);
      card.appendChild(role);
    }
    list.appendChild(card);
  }

  // enable script generate
  const btn = document.getElementById("script-generate");
  if (btn) {
    btn.disabled = false;
    btn.textContent = "用今日候選生成腳本";
  }
}

async function loadCandidates() {
  const category = document.getElementById("candidates-category").value;
  const strategy = document.getElementById("candidates-strategy").value;
  setStatus("candidates-status", "loading", "載入中…");
  try {
    const data = await getCandidates({ category, strategy });
    lastCandidate = data;
    renderCandidates(data);
    setStatus("candidates-status", "success", "");
  } catch (e) {
    if (e.code === "CANDIDATES_NOT_READY") {
      setStatus("candidates-status", "error", "今日尚未爬取，按「觸發爬取」開始");
    } else {
      handleApiError(e);
      setStatus("candidates-status", "error", e.message || "載入失敗");
    }
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
  if (!lastCandidate) {
    toast("先載入候選", "error");
    return;
  }
  const candidateIds = lastCandidate.id
    ? [lastCandidate.id]
    : (lastCandidate.items || []).map((d) => d.id).filter(Boolean);
  if (candidateIds.length === 0) {
    toast("找不到 candidate id", "error");
    return;
  }
  const category = lastCandidate.category || document.getElementById("candidates-category").value;
  const scriptType = document.getElementById("script-type")?.value || "traffic";

  const btn = document.getElementById("script-generate");
  if (btn) { btn.disabled = true; btn.textContent = "生成中（30-60 秒）…"; }
  setStatus("script-status", "loading", `正在產三版本（脆＝${scriptType}）…`);
  try {
    const data = await generateScript({ candidate_ids: candidateIds, category, script_type: scriptType });
    lastScript = data;
    renderScript(data);
    setStatus("script-status", "success", `已生成 ${data.script_id}`);
    document.getElementById("storyboard-card").hidden = false;
  } catch (e) {
    handleApiError(e);
    setStatus("script-status", "error", e.message || "生成失敗");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "重新生成"; }
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
