// ScriptFlow — Tab 1 候選 + Tab 2 腳本/分鏡

import {
  addManualCandidate,
  generateScript,
  generateStoryboard,
  getCandidates,
  getLatestScript,
  getRecentCandidates,
  getXhsPreview,
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

const XHS_FALLBACK_BY_CATEGORY = {
  "髮品": "頭髮乾燥毛躁？這款髮膜我用了 3 週真的有感",
  "美妝": "敏感肌的救星精華｜我的暗沉變化",
  "美食": "減脂便當這樣做｜不挨餓還能瘦",
};

function _ensureXhsDisplaySlot(doc) {
  const sourceItems = Array.isArray(doc?.items) ? doc.items : [];
  const items = sourceItems.slice(0, 3);
  const hasUsableXhs = items.some((item) => {
    const source = item?.source_url || item?.url || "";
    return item?.platform === "xiaohongshu" && !source.includes("example.com");
  });
  if (hasUsableXhs) return items;

  const manualXhs = sourceItems.find((item) => {
    const source = item?.source_url || item?.url || "";
    return item?.is_manual === true
      && item?.platform === "xiaohongshu"
      && source.includes("xiaohongshu.com/explore/")
      && !source.includes("example.com");
  });
  if (manualXhs) {
    if (items.length >= 3) {
      items[2] = manualXhs;
    } else {
      items.push(manualXhs);
    }
    return items.map((item, idx) => ({ ...item, rank: idx + 1 }));
  }

  const category = doc?.category || "";
  const title = XHS_FALLBACK_BY_CATEGORY[category] || `小紅書 ${category || "熱門"} 備援候選`;
  const keyword = `${category} ${title}`.trim();
  const fallback = {
    platform: "xiaohongshu",
    url: `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`,
    source_url: `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`,
    title,
    engagement: 0,
    topic_match: category === "髮品" ? 0.1 : 0,
    purchase_intent_density: 0,
    funnel_role: "evaluation",
    is_fallback: true,
    fallback_reason: "xiaohongshu_actor_empty",
    search_keyword: keyword,
    rank: Math.min(3, items.length + 1),
  };

  const existingXhsIndex = items.findIndex((item) => item?.platform === "xiaohongshu");
  if (existingXhsIndex >= 0) {
    items[existingXhsIndex] = fallback;
  } else if (items.length >= 3) {
    items[2] = fallback;
  } else {
    items.push(fallback);
  }
  return items.map((item, idx) => ({ ...item, rank: idx + 1 }));
}


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

  // 偵測是否在 mock 模式：只有「所有 item 都是 mock」才顯示警告
  // （部分平台沒有 Actor 會 fallback mock，但只要有任何一筆真實資料就不顯示 banner）
  const allItems = payload.buckets.flatMap(b => b.docs || []).flatMap(d => d.items || []);
  const isMockMode = allItems.length > 0 &&
    allItems.every(item => (item?.source_url || item?.url || "").includes("example.com"));

  if (isMockMode) {
    const banner = el("div", "mock-banner");
    banner.textContent = "⚠️ 目前是 Mock 測試資料 — 標題、互動數、原文連結皆為假資料。要看真實爬取結果需配置爬蟲服務（CRAWLER_BACKEND env）";
    meta.appendChild(banner);
  }

  const strategyLabel = payload.strategy === "hotness" ? "熱門優先（純看互動數）" : "平衡型（互動×主題符合度）";
  meta.appendChild(el("span", null,
    `顯示最近 ${payload.days} 天的候選 ｜ 排序：${strategyLabel} ｜ 每天保留，超過 ${payload.days} 天自動清除`
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
      const displayItems = _ensureXhsDisplaySlot(doc);
      displayItems.forEach((item, idx) => {
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

  // 動作列：原文連結 + 用此篇生成
  const actionRow = el("div", "cand__actions");

  // 原文連結（mock 時顯示為 disabled，真資料才能點）
  const sourceUrl = item.source_url || item.url;
  if (sourceUrl) {
    const isMock = sourceUrl.includes("example.com");
    if (isMock && item.platform === "xiaohongshu") {
      const keyword = item.search_keyword || `${doc?.category || ""} ${item.title || ""}`.trim();
      const searchUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`;
      const a = document.createElement("a");
      a.className = "cand__url";
      a.href = searchUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "🔎 搜尋小紅書";
      a.title = "這是小紅書保底候選，沒有真實原文 URL；改用標題關鍵字搜尋";
      actionRow.appendChild(a);
    } else if (isMock) {
      const a = el("span", "cand__url cand__url--mock", "🔒 原文連結（mock）");
      a.title = sourceUrl;
      actionRow.appendChild(a);
    } else {
      const urlRow = el("div", "cand__url-row");
      // platform 欄位優先，URL 含 xiaohongshu.com 為備援
      // （zhorex 有時回傳 xhslink.com 短網址，URL 判斷不夠可靠）
      const isXhs = item.platform === "xiaohongshu" || sourceUrl.includes("xiaohongshu.com");

      if (isXhs) {
        // 小紅書在台灣 IP 有 SSL 封鎖，無法直接開啟，只顯示徽章 + 預覽按鈕
        const badge = el("span", "cand__url cand__url--geo", "🇨🇳 小紅書");
        badge.title = "小紅書在台灣 IP 無法直接開啟（TCP 地區封鎖）\n複製連結後透過中國大陸 IP 或 VPN 存取";
        urlRow.appendChild(badge);

        // 🔗 前往原文 — 直連小紅書，使用者自備中國大陸 IP / VPN 即可查看
        // 只對真實貼文（/explore/）顯示；保底搜尋頁（/search_result）不掛按鈕避免誤導
        if (sourceUrl.includes("xiaohongshu.com/explore/")) {
          const goLink = document.createElement("a");
          goLink.className = "cand__url cand__url--go";
          goLink.href = sourceUrl;
          goLink.target = "_blank";
          goLink.rel = "noopener noreferrer";
          goLink.textContent = "🔗 前往原文";
          goLink.title = "在新分頁開啟小紅書原文。小紅書在台灣遭 DNS 封鎖（警政署反詐）＋中國地理封鎖，需開啟「全隧道」中國大陸 VPN（DNS 也走中國）才能正常開啟";
          urlRow.appendChild(goLink);
        }

        // 📖 預覽按鈕 — 透過後端 Apify proxy 抓取內容
        const previewBtn = el("button", "cand__preview-btn", "📖 預覽");
        previewBtn.type = "button";
        previewBtn.title = "透過後端 Apify 代理預覽內容（每次約 $0.01，15~30 秒）";
        previewBtn.addEventListener("click", () => {
          previewBtn.disabled = true;
          previewBtn.textContent = "⏳";
          // 正規化 URL：保留 xsec_token / xsec_source（Apify actor auth 用），去掉其餘 params
          // 若是 xhslink.com 等舊格式，_normalizeXhsUrl 回傳 null，modal 顯示備用資料
          openXhsModal(_normalizeXhsUrl(sourceUrl), item);
          // 等 modal 關閉後恢復（監聽 hidden 屬性）
          const observer = new MutationObserver(() => {
            if (_xhsModalEl("xhs-modal").hidden) {
              previewBtn.disabled = false;
              previewBtn.textContent = "📖 預覽";
              observer.disconnect();
            }
          });
          observer.observe(_xhsModalEl("xhs-modal"), { attributes: true });
        });
        urlRow.appendChild(previewBtn);
      } else {
        // TikTok 等：提供直連（可能需登入）
        const a = document.createElement("a");
        a.className = "cand__url";
        a.href = sourceUrl;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = "🔗 看原文";
        a.title = `${platformZh} 原文連結；若無法開啟請使用「複製連結」`;
        urlRow.appendChild(a);
      }

      const copyBtn = el("button", "cand__copy-url", "📋 複製");
      copyBtn.type = "button";
      copyBtn.title = sourceUrl;
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(sourceUrl);
          copyBtn.textContent = "✓ 已複製";
          setTimeout(() => { copyBtn.textContent = "📋 複製"; }, 2000);
        } catch (_) {
          // clipboard API 不可用時降級提示
          copyBtn.title = sourceUrl;
        }
      });
      urlRow.appendChild(copyBtn);

      actionRow.appendChild(urlRow);
    }
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
  actionRow.appendChild(btn);

  card.appendChild(actionRow);
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
  const strategy = document.getElementById("candidates-strategy").value;
  setStatus("candidates-status", "loading", "載入中…");
  try {
    const payload = await getRecentCandidates({ days: 5, category, strategy });
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

async function doLoadLatestScript() {
  const btn = document.getElementById("script-load-latest");
  if (btn) btn.disabled = true;
  setStatus("script-status", "loading", "拉最近一次腳本…");
  try {
    const data = await getLatestScript();
    lastScript = data;
    renderScript(data);
    const dt = data.date ? `（${data.date}）` : "";
    setStatus("script-status", "success", `已載入 ${data.script_id}${dt}`);
    document.getElementById("storyboard-card").hidden = false;
    toast("已載入最近腳本", "success");
  } catch (e) {
    if (e.code === "HTTP_404") {
      setStatus("script-status", "error", "目前還沒有生成過腳本");
    } else {
      handleApiError(e);
      setStatus("script-status", "error", e.message || "載入失敗");
    }
  } finally {
    if (btn) btn.disabled = false;
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
  document.getElementById("script-load-latest")?.addEventListener("click", doLoadLatestScript);
  document.querySelectorAll(".storyboard-platform").forEach((btn) => {
    btn.addEventListener("click", () => doGenerateStoryboard(btn.dataset.platform));
  });
  // 切分類或策略 → 自動重新載入候選
  document.getElementById("candidates-category")?.addEventListener("change", loadCandidates);
  document.getElementById("candidates-strategy")?.addEventListener("change", loadCandidates);

  // 手動補爆款表單
  const manualBtn = document.getElementById("candidates-manual-btn");
  const manualPanel = document.getElementById("manual-form-panel");
  const manualCancel = document.getElementById("manual-cancel");
  const manualForm = document.getElementById("manual-form");
  manualBtn?.addEventListener("click", () => {
    if (manualPanel) manualPanel.hidden = !manualPanel.hidden;
  });
  manualCancel?.addEventListener("click", () => {
    if (manualPanel) manualPanel.hidden = true;
  });
  manualForm?.addEventListener("submit", onManualSubmit);
}

async function onManualSubmit(e) {
  e.preventDefault();
  const platform = document.getElementById("manual-platform").value;
  const category = document.getElementById("manual-category").value;
  const title = document.getElementById("manual-title").value.trim();
  const url = document.getElementById("manual-url").value.trim();
  const engagementRaw = document.getElementById("manual-engagement").value.trim();
  const engagement = engagementRaw ? Number(engagementRaw) : 0;

  if (!title || !url) {
    setStatus("manual-status", "error", "標題和網址必填");
    return;
  }
  const submit = e.target.querySelector("button[type=submit]");
  if (submit) submit.disabled = true;
  setStatus("manual-status", "loading", "儲存中…");
  try {
    await addManualCandidate({ platform, category, title, url, engagement });
    setStatus("manual-status", "success", "已加入今日候選");
    toast("已加入今日候選", "success");
    e.target.reset();
    // 自動重新載入候選列表
    await loadCandidates();
    // 收起表單面板
    const panel = document.getElementById("manual-form-panel");
    if (panel) panel.hidden = true;
  } catch (err) {
    handleApiError(err);
    setStatus("manual-status", "error", err.message || "新增失敗");
  } finally {
    if (submit) submit.disabled = false;
  }
}

// ─── 小紅書預覽 Modal ────────────────────────────────────────────────────────

function _xhsModalEl(id) { return document.getElementById(id); }

/**
 * 把任意小紅書 URL 正規化成後端能接受的格式：
 *   https://www.xiaohongshu.com/explore/{hex_id}（無 query params）
 *
 * 若 URL 是 xhslink.com 短網址或其他格式，回傳 null（後端無法預覽）。
 * 注意：此函式純做 URL 字串處理，不發網路請求。
 */
function _normalizeXhsUrl(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (u.hostname === "www.xiaohongshu.com" && u.pathname.startsWith("/explore/")) {
      // 保留預覽需要的 xsec_token / xsec_source，其餘 query params 由後端再白名單過濾
      const clean = new URL(`https://www.xiaohongshu.com${u.pathname}`);
      ["xsec_token", "xsec_source"].forEach((key) => {
        const value = u.searchParams.get(key);
        if (value) clean.searchParams.set(key, value);
      });
      return clean.toString();
    }
  } catch { /* invalid URL，略過 */ }
  return null; // xhslink.com 短網址或其他格式，後端無法接受
}

/**
 * 當 Apify 無法取得完整內容時（返回空或 404），
 * 用已爬取的 candidate item 資料填入 modal 作為備用顯示。
 * 用 textContent，符合 rule-frontend XSS 防護。
 */
function _renderXhsFallback(item) {
  const imgBox = _xhsModalEl("xhs-modal-images");
  imgBox.textContent = "";

  const preview = item?.preview || null;
  const previewImages = Array.isArray(preview?.images) ? preview.images : [];
  previewImages.slice(0, 4).forEach((src) => {
    const img = document.createElement("img");
    img.src = src;
    img.loading = "lazy";
    img.alt = "小紅書圖片";
    imgBox.appendChild(img);
  });
  if (imgBox.childElementCount === 0) {
    // 無圖片時的乾淨備用呈現
    const sourceUrl = item?.source_url || "";
    const linkWrap = document.createElement("div");
    linkWrap.className = "modal__link-action";
    if (sourceUrl.startsWith("https://www.xiaohongshu.com/")) {
      // 有原文連結 → 顯示「前往原文」按鈕
      const a = document.createElement("a");
      a.href = sourceUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "modal__link-btn";
      a.textContent = "🔗 前往小紅書查看原文";
      const note = document.createElement("p");
      note.className = "modal__link-note";
      note.textContent = "需使用中國大陸 IP 或 VPN 才能正常開啟";
      linkWrap.appendChild(a);
      linkWrap.appendChild(note);
    } else {
      // 無原文連結（舊候選未存）→ 顯示說明，不留空白、不顯示技術錯誤
      const note = document.createElement("p");
      note.className = "modal__link-note";
      note.textContent = "此來源暫無預覽內容（小紅書資料擷取額度每月 26 日重置後，新候選將自動帶入圖文預覽）。";
      linkWrap.appendChild(note);
    }
    imgBox.appendChild(linkWrap);
  }

  _xhsModalEl("xhs-modal-author").textContent = preview?.author ? `👤 ${preview.author}` : "";

  const statsEl = _xhsModalEl("xhs-modal-stats");
  statsEl.textContent = "";
  if (preview?.likes != null) statsEl.append(`❤️ ${Number(preview.likes).toLocaleString()}  `);
  if (preview?.comments != null) statsEl.append(`💬 ${Number(preview.comments).toLocaleString()}  `);
  if (preview?.collects != null) statsEl.append(`⭐ ${Number(preview.collects).toLocaleString()}`);
  if (statsEl.textContent === "" && item && item.engagement != null) {
    statsEl.append(`📊 爬取時互動數 ${Number(item.engagement).toLocaleString()}`);
  }

  _xhsModalEl("xhs-modal-post-title").textContent = preview?.title || item?.title || "";
  _xhsModalEl("xhs-modal-text").textContent = preview?.content || "";
}

function _hasEmbeddedXhsPreview(item) {
  const preview = item?.preview;
  return Boolean(
    preview &&
    (
      preview.content ||
      (Array.isArray(preview.images) && preview.images.length > 0)
    )
  );
}

function openXhsModal(noteUrl, item = null) {
  const modal   = _xhsModalEl("xhs-modal");
  const loading = _xhsModalEl("xhs-modal-loading");
  const errEl   = _xhsModalEl("xhs-modal-error");
  const content = _xhsModalEl("xhs-modal-content");

  // 重置狀態
  loading.hidden = false;
  errEl.hidden   = true;
  content.hidden = true;
  modal.hidden   = false;
  document.body.style.overflow = "hidden";

  if (_hasEmbeddedXhsPreview(item)) {
    loading.hidden = true;
    _renderXhsFallback(item);
    content.hidden = false;
    return;
  }

  // 無可用的 note URL（舊候選未存原文連結，或短網址無法正規化）
  // → 不顯示技術錯誤，直接走乾淨的備用呈現（_renderXhsFallback 會給適當訊息）
  if (!noteUrl) {
    loading.hidden = true;
    _renderXhsFallback(item || {});
    content.hidden = false;
    return;
  }

  getXhsPreview(noteUrl)
    .then((data) => {
      loading.hidden = true;

      // 圖片（最多 4 張）—— 用 createElement，不用 innerHTML
      const imgBox = _xhsModalEl("xhs-modal-images");
      imgBox.textContent = "";
      (data.images || []).slice(0, 4).forEach((src) => {
        const img = document.createElement("img");
        img.src = src;
        img.loading = "lazy";
        img.alt = "小紅書圖片";
        imgBox.appendChild(img);
      });

      // 作者
      _xhsModalEl("xhs-modal-author").textContent = data.author ? `👤 ${data.author}` : "";

      // 互動數
      const statsEl = _xhsModalEl("xhs-modal-stats");
      statsEl.textContent = "";
      if (data.likes   != null) statsEl.append(`❤️ ${data.likes.toLocaleString()}  `);
      if (data.comments != null) statsEl.append(`💬 ${data.comments.toLocaleString()}  `);
      if (data.collects != null) statsEl.append(`⭐ ${data.collects.toLocaleString()}`);

      // 標題 + 內文
      _xhsModalEl("xhs-modal-post-title").textContent = data.title || "";
      _xhsModalEl("xhs-modal-text").textContent       = data.content || "";

      content.hidden = false;
    })
    .catch((err) => {
      loading.hidden = true;
      if (item) {
        // 預覽資料暫不可用（小紅書地理封鎖）→ 直接顯示爬取時已知資訊，不顯示技術錯誤
        _renderXhsFallback(item);
        content.hidden = false;
      } else {
        errEl.textContent = `預覽失敗：${err.message || "未知錯誤"}`;
        errEl.hidden = false;
      }
    });
}

function closeXhsModal() {
  const modal = _xhsModalEl("xhs-modal");
  modal.hidden = true;
  document.body.style.overflow = "";
}

// ─── DOMContentLoaded ────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  setup();

  // Modal 關閉事件
  const closeBtn = _xhsModalEl("xhs-modal-close");
  if (closeBtn) closeBtn.addEventListener("click", closeXhsModal);
  const backdrop = document.querySelector("#xhs-modal .modal__backdrop");
  if (backdrop) backdrop.addEventListener("click", closeXhsModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !_xhsModalEl("xhs-modal").hidden) closeXhsModal();
  });

  // 登入後自動載入候選
  onAuthChange(async (authed) => {
    if (authed) {
      try { await loadCandidates(); } catch { /* 沒資料無妨 */ }
    }
  });
  if (isAuthed()) loadCandidates();
});
