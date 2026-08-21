/* 化学结构速查助手 - 前端逻辑 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtNum(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (Number.isNaN(n)) return String(v);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }

  const HOMO = { "噁": "恶", "䓬": "卓", "碸": "砜", "羥": "羟", "甙": "苷", "醯": "酰" };
  function normZh(s) {
    return String(s || "").split("").map((ch) => HOMO[ch] || ch).join("");
  }

  const NET_MSG = "无法连接本地服务（fail to fetch）。请先运行“启动工具.bat”启动服务，然后刷新页面。";

  function api(path, data) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    }).then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `请求失败 (${r.status})`);
      return d;
    }).catch((e) => {
      if (e instanceof TypeError) throw new Error(NET_MSG);
      throw e;
    });
  }

  /* 流式请求：读取 NDJSON 分块，onEvent 收到 {type:"progress",...}，最后返回 result 或抛错 */
  async function apiStream(path, data, onEvent) {
    let resp;
    try {
      resp = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {}),
      });
    } catch (e) {
      throw new Error(NET_MSG);
    }
    if (!resp.ok || !resp.body) {
      const d = await resp.json().catch(() => ({}));
      throw new Error(d.error || `请求失败 (${resp.status})`);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result = null;
    let err = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch (e) { continue; }
        if (msg.type === "result") result = msg.data;
        else if (msg.type === "error") err = new Error(msg.message || "检索失败");
        else if (msg.type === "progress" && onEvent) onEvent(msg);
      }
    }
    if (err) throw err;
    if (!result) throw new Error("服务返回了无法解析的数据");
    return result;
  }

  function setSearchProgress(text) {
    const el = $("#search-progress");
    if (!el) return;
    if (!text) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.textContent = text;
    el.classList.remove("hidden");
  }

  function getJSON(path) {
    return fetch(path).then(async (r) => {
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `请求失败 (${r.status})`);
      return d;
    }).catch((e) => {
      if (e instanceof TypeError) throw new Error(NET_MSG);
      throw e;
    });
  }

  function showMessage(text, kind) {
    const box = $("#message");
    if (!text) { box.innerHTML = ""; return; }
    box.innerHTML = `<div class="msg ${kind || "info"}">${esc(text)}</div>`;
  }

  /* ---------------- 结构图渲染队列（并发限制 + 缓存） ---------------- */
  const imgCache = new Map();
  const pending = new Map();
  const renderQueue = [];
  const CONCURRENT = 3;
  let activeRenders = 0;

  function pumpRender() {
    while (activeRenders < CONCURRENT && renderQueue.length) {
      const job = renderQueue.shift();
      activeRenders++;
      api("/api/render", { smiles: job.smiles, online: state.online })
        .then((d) => { imgCache.set(job.smiles, d); job.resolve(d); })
        .catch((e) => job.reject(e))
        .finally(() => { activeRenders--; pumpRender(); });
    }
  }

  function renderSmiles(smiles) {
    if (!smiles) return Promise.reject(new Error("无 SMILES"));
    if (imgCache.has(smiles)) return Promise.resolve(imgCache.get(smiles));
    if (pending.has(smiles)) return pending.get(smiles);
    const p = new Promise((resolve, reject) => {
      renderQueue.push({ smiles, resolve, reject });
    });
    pending.set(smiles, p);
    p.catch(() => {}).finally(() => pending.delete(smiles));
    pumpRender();
    return p;
  }

  function fillStructBox(box, smiles) {
    if (!box || !smiles) {
      if (box) box.innerHTML = `<div class="placeholder">无 SMILES</div>`;
      return;
    }
    box.innerHTML = `<div class="spinner"></div>`;
    renderSmiles(smiles).then((d) => {
      box.innerHTML = `<img src="${esc(d.image)}" alt="结构式" loading="lazy">`;
      const img = box.querySelector("img");
      img.onerror = () => {
        box.innerHTML = `<div class="placeholder">结构图加载失败<br>${esc(smiles)}</div>`;
      };
    }).catch(() => {
      box.innerHTML = `<div class="placeholder">结构图不可用</div>`;
    });
  }

  /* ---------------- 全局状态 ---------------- */
  const SOURCE_LABEL = {
    dict: "中文词典", name: "名称匹配", autocomplete: "名称联想",
    formula: "分子式", smiles: "SMILES", cas: "CAS", similar: "相似", substructure: "子结构",
    category: "教材分类",
  };
  const state = {
    candidates: [],
    shown: 0,
    pageSize: 24,
    query: "",
    type: "auto",
    online: localStorage.getItem("ch_online") !== "0",
    pinned: [],
    groupsData: [],
    groupsById: {},
  };
  let io = null;

  function ensureIO() {
    if (io) return io;
    io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) {
          const el = en.target;
          io.unobserve(el);
          fillStructBox(el, el.dataset.smiles);
        }
      });
    }, { rootMargin: "300px" });
    return io;
  }

  /* ---------------- 固定对比栏 ---------------- */
  let pinZ = 100;   // 浮窗层级计数（目录 150 常显，聚焦/拖动置顶 1000+）

  function pinKey(p) {
    return p.type === "group" ? "g:" + p.gid : "d:" + p.cid;
  }

  function getPinWinPos(key) {
    try {
      const m = JSON.parse(localStorage.getItem("ch_pinwin_pos_v1") || "{}");
      return m[key] || null;
    } catch (e) { return null; }
  }

  function setPinWinPos(key, pos) {
    try {
      const m = JSON.parse(localStorage.getItem("ch_pinwin_pos_v1") || "{}");
      m[key] = pos;
      localStorage.setItem("ch_pinwin_pos_v1", JSON.stringify(m));
    } catch (e) { /* ignore */ }
  }

  function savePinned() {
    localStorage.setItem("ch_pinned_v1", JSON.stringify(state.pinned.slice(0, 10)));
  }

  function isPinnedDrug(cid) {
    return state.pinned.some((p) => p.type !== "group" && String(p.cid) === String(cid));
  }

  function isPinnedGroup(gid) {
    return state.pinned.some((p) => p.type === "group" && String(p.gid) === String(gid));
  }

  function togglePin(c) {
    if (isPinnedDrug(c.cid)) {
      state.pinned = state.pinned.filter((p) => String(p.cid) !== String(c.cid));
    } else {
      if (state.pinned.length >= 10) {
        showMessage("对比栏最多固定 10 个，请先移除部分条目。", "warn");
        return;
      }
      state.pinned.push({
        type: "drug",
        cid: c.cid, zh: c.zh || "", iupac: c.iupac || "", smiles: c.smiles || "",
        formula: c.formula || "", category: c.category || "",
        parent: c.parent || "", pharmacophore: c.pharmacophore || "", target: c.target || "",
        action: c.action || "", similar: c.similar || [], groups: c.groups || [],
      });
    }
    savePinned();
    renderPinned();
    renderPinWindows();
    refreshPinButtons();
  }

  function togglePinGroup(g) {
    if (isPinnedGroup(g.id)) {
      state.pinned = state.pinned.filter((p) => !(p.type === "group" && String(p.gid) === String(g.id)));
    } else {
      if (state.pinned.length >= 10) {
        showMessage("对比栏最多固定 10 个，请先移除部分条目。", "warn");
        return;
      }
      state.pinned.push(Object.assign({ type: "group", gid: g.id }, g));
    }
    savePinned();
    renderPinned();
    renderPinWindows();
    refreshPinButtons();
  }

  function refreshPinButtons() {
    $$(".pin-btn").forEach((b) => {
      const cid = b.dataset.cid;
      const on = isPinnedDrug(cid);
      b.textContent = on ? "📌 已固定" : "📌 固定";
      b.classList.toggle("pinned", on);
    });
    $$("[data-act='pin-group']").forEach((b) => {
      const on = isPinnedGroup(b.dataset.gid);
      b.textContent = on ? "📌 已固定" : "📌 固定";
      b.classList.toggle("pinned", on);
    });
  }

  function pinnedDrugHtml(c) {
    const groups = (c.groups || []).map((g) =>
      `<button class="g-chip" data-gid="${esc(g.id)}" title="${esc(g.en || "")}">${esc(g.symbol || g.zh)}</button>`
    ).join("");
    return `
      <div class="pinned-item">
        <div class="card-item" data-cid="${esc(c.cid)}">
          <div class="card-head">
            <div class="card-title">
              ${c.zh ? `<span class="zh">${esc(c.zh)}</span>` : esc(c.iupac || "化合物")}
              ${c.category ? `<span class="badge cat">${esc(c.category)}</span>` : ""}
            </div>
            <div class="card-iupac">${esc(c.iupac || "")}</div>
          </div>
          <div class="struct" data-smiles="${esc(c.smiles || "")}"><div class="spinner"></div></div>
          <div class="card-body">
            ${pharmBlockHtml(c)}
            ${c.smiles ? `<div class="smiles-line"><span>${esc(c.smiles)}</span><button class="copy-btn" data-copy="${esc(c.smiles)}">⧉</button></div>` : ""}
            ${groups ? `<div class="groups-row">${groups}</div>` : ""}
            <div class="card-actions">
              <button class="btn-mini" data-act="detail">详情</button>
              <button class="btn-mini" data-act="similar">相似化合物</button>
              ${c.cid ? `<button class="btn-mini" data-act="pubchem" data-cid="${esc(c.cid)}">PubChem ↗</button>` : ""}
              <button class="btn-mini" data-p-remove="${esc(c.cid)}">移除</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  function pinnedGroupHtml(g) {
    const reps = (g.representatives || []).map((r) =>
      `<button class="chip" data-rep-name="${esc(r.name)}" data-rep-en="${esc(r.en)}">${esc(r.name)}</button>`
    ).join("");
    const reactions = (g.reactions || []).map((r) => `<span class="r-chip">${esc(r)}</span>`).join("");
    const ph = g.pharmacophore || {};
    const phDrugs = (ph.drugs || []).map((d) =>
      `<button class="chip" data-rep-name="${esc(d.name)}" data-rep-en="${esc(d.en)}">${esc(d.name)}</button>`).join("");
    let phBox = "";
    if (ph.drug_class) {
      phBox = `<div class="pharm-box">
        <div class="label">🔑 药效基团信息</div>
        <div><b>对应药物类别：</b>${esc(ph.drug_class)}</div>
        ${ph.target ? `<div><b>作用靶点：</b>${esc(ph.target)}</div>` : ""}
        ${ph.sar ? `<div><b>构效关系：</b>${esc(ph.sar)}</div>` : ""}
        ${phDrugs ? `<div><b>代表药物：</b><div class="similar-chips">${phDrugs}</div></div>` : ""}
      </div>`;
    }
    return `
      <div class="pinned-item">
        <div class="group-card" data-group-id="${esc(g.id)}">
          <div class="group-top">
            <div class="group-img" data-group-img="${esc(g.id)}" data-smiles="${esc(g.smiles_example || "")}"><div class="spinner"></div></div>
            <div>
              <div class="g-head"><h3>${esc(g.zh)} <span class="g-symbol">${esc(g.symbol || "")}</span></h3></div>
              <div class="g-en">${esc(g.en || "")}</div>
              <p class="g-short">${esc(g.short || "")}</p>
            </div>
          </div>
          <details class="g-details">
            <summary>特点 / 性质 / 药效基团 / 代表药物</summary>
            <div class="g-desc">${esc(g.description || "")}</div>
            ${phBox}
            ${reactions ? `<div class="g-reactions">${reactions}</div>` : ""}
            ${g.hint ? `<div class="g-hint">💡 ${esc(g.hint)}</div>` : ""}
            ${reps ? `<div class="g-reps"><span class="label">代表化合物：</span>${reps}</div>` : ""}
          </details>
          <div class="g-actions">
            <button class="btn-mini" data-sub-smiles="${esc(g.substructure_smiles || g.smiles_example || "")}" data-group-zh="${esc(g.zh)}">查找含此基团的化合物</button>
            <button class="btn-mini" data-p-remove="g:${esc(g.id)}">移除</button>
          </div>
        </div>
      </div>`;
  }

  function renderPinned() {
    const list = $("#pinned-list");
    $("#pinned-count").textContent = state.pinned.length;
    if (!state.pinned.length) {
      list.innerHTML = `<div class="pinned-empty">还没有固定条目。在结果卡片或官能团卡片上点“📌 固定”，即会以独立资料卡浮窗显示，并在右侧目录列出。</div>`;
      return;
    }
    list.innerHTML = state.pinned.map((p) => {
      const key = pinKey(p);
      const name = p.type === "group"
        ? (p.zh || p.en || "官能团")
        : (p.zh || p.iupac || "化合物");
      const badge = p.type === "group" ? "基团" : (p.category || "药物");
      return `<div class="pin-dir-item" data-dir-key="${esc(key)}" title="点击展开/聚焦该窗口">
        <span class="dir-name">${esc(name)}</span>
        <span class="dir-badge">${esc(badge)}</span>
        <button class="btn-mini" data-p-remove="${esc(key)}" title="移除">×</button>
      </div>`;
    }).join("");
  }

  function pinName(p) {
    return p.type === "group"
      ? (p.zh || p.en || "官能团")
      : (p.zh || p.iupac || "化合物");
  }

  function renderPinWindows() {
    const layer = $("#pinned-windows");
    const keys = new Set(state.pinned.map(pinKey));
    Array.from(layer.children).forEach((el) => {
      if (!keys.has(el.dataset.key)) el.remove();
    });
    let cascade = 0;
    state.pinned.forEach((p) => {
      ensurePinWindow(p, cascade++);
    });
  }

  function ensurePinWindow(p, cascade) {
    const layer = $("#pinned-windows");
    const key = pinKey(p);
    let el = null;
    Array.from(layer.children).forEach((c) => { if (c.dataset.key === key) el = c; });
    if (!el) {
      el = document.createElement("div");
      el.className = "pin-window";
      el.dataset.key = key;
      el.innerHTML = `
        <div class="pin-win-head">
          <span class="pin-win-title"></span>
          <button class="btn-mini pin-win-collapse" title="收起/展开">收起</button>
          <button class="btn-mini pin-win-remove" title="移除">×</button>
        </div>
        <div class="pin-win-body"></div>`;
      el.style.zIndex = pinZ++;
      layer.appendChild(el);
      bindPinWindow(el, key);
    }
    const pos = getPinWinPos(key);
    if (pos && typeof pos.x === "number" && typeof pos.y === "number") {
      el.style.left = pos.x + "px";
      el.style.top = pos.y + "px";
      el.classList.toggle("collapsed", !!pos.collapsed);
      el.querySelector(".pin-win-collapse").textContent = pos.collapsed ? "展开" : "收起";
    } else {
      const x = 48 + (cascade % 6) * 30;
      const y = 72 + (cascade % 6) * 34;
      el.style.left = x + "px";
      el.style.top = y + "px";
    }
    el.querySelector(".pin-win-title").textContent = pinName(p);
    el.querySelector(".pin-win-body").innerHTML = p.type === "group" ? pinnedGroupHtml(p) : pinnedDrugHtml(p);
    el.querySelectorAll(".struct[data-smiles]").forEach((img) => {
      if (img.dataset.smiles) ensureIO().observe(img);
      else img.innerHTML = `<div class="placeholder">无 SMILES</div>`;
    });
    el.querySelectorAll("[data-group-img][data-smiles]").forEach((img) => {
      if (img.dataset.smiles) ensureIO().observe(img);
      else img.innerHTML = `<div class="placeholder">无 SMILES</div>`;
    });
  }

  function bindPinWindow(el, key) {
    const head = el.querySelector(".pin-win-head");
    head.addEventListener("mousedown", (e) => {
      if (e.target.closest("button")) return;
      el.style.zIndex = 1000 + (pinZ++ % 200);
      const rect = el.getBoundingClientRect();
      window._pinDrag = { el, dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      e.preventDefault();
    });
    el.querySelector(".pin-win-collapse").addEventListener("click", (e) => {
      e.stopPropagation();
      const collapsed = el.classList.toggle("collapsed");
      el.querySelector(".pin-win-collapse").textContent = collapsed ? "展开" : "收起";
      const pos = getPinWinPos(key) || {};
      pos.collapsed = collapsed;
      setPinWinPos(key, pos);
    });
    el.querySelector(".pin-win-remove").addEventListener("click", (e) => {
      e.stopPropagation();
      removePinByKey(key);
    });
  }

  function focusPinWindow(key) {
    const layer = $("#pinned-windows");
    let el = null;
    Array.from(layer.children).forEach((c) => { if (c.dataset.key === key) el = c; });
    if (!el) return;
    el.classList.remove("collapsed");
    el.querySelector(".pin-win-collapse").textContent = "收起";
    const pos = getPinWinPos(key) || {};
    pos.collapsed = false;
    setPinWinPos(key, pos);
    el.style.zIndex = 1000 + (pinZ++ % 200);
  }

  function removePinByKey(key) {
    if (String(key).startsWith("g:")) {
      const gid = String(key).slice(2);
      state.pinned = state.pinned.filter((x) => !(x.type === "group" && String(x.gid) === gid));
    } else {
      const cid = String(key).startsWith("d:") ? String(key).slice(2) : String(key);
      state.pinned = state.pinned.filter((x) => String(x.cid) !== cid);
    }
    savePinned();
    renderPinned();
    renderPinWindows();
    refreshPinButtons();
  }

  document.addEventListener("mousemove", (e) => {
    const drag = window._pinDrag;
    if (!drag) return;
    const x = Math.min(Math.max(e.clientX - drag.dx, 0), window.innerWidth - 90);
    const y = Math.min(Math.max(e.clientY - drag.dy, 0), window.innerHeight - 44);
    drag.el.style.left = x + "px";
    drag.el.style.top = y + "px";
  });
  document.addEventListener("mouseup", () => {
    const drag = window._pinDrag;
    if (!drag) return;
    window._pinDrag = null;
    const rect = drag.el.getBoundingClientRect();
    const key = drag.el.dataset.key;
    const pos = getPinWinPos(key) || {};
    pos.x = Math.round(rect.left);
    pos.y = Math.round(rect.top);
    setPinWinPos(key, pos);
  });

  /* ---------------- 结果卡片 ---------------- */
  function sourceHtml(src) {
    if (!Array.isArray(src) || !src.length) return "";
    const parts = src.slice(0, 2).map((s) => {
      if (!s || typeof s !== "object") return "";
      if (s.book === "PubChem") return "PubChem 中文整理";
      if (s.book === "人工整理") return "人工精编";
      return `${s.book}${s.chapter ? "《" + s.chapter + "》" : ""}${s.page ? "（p" + s.page + "）" : ""}`;
    }).filter(Boolean);
    if (!parts.length) return "";
    return `<div class="pharm-src">来源：${parts.join("；")}</div>`;
  }

  function pharmBlockHtml(c) {
    const rows = [];
    if (c.parent) rows.push(`<div class="pharm-row"><span class="k">母体</span><span>${esc(c.parent)}</span></div>`);
    if (c.pharmacophore) rows.push(`<div class="pharm-row"><span class="k">药效基团</span><span>${esc(c.pharmacophore)}</span></div>`);
    if (c.target) rows.push(`<div class="pharm-row"><span class="k">靶点</span><span>${esc(c.target)}</span></div>`);
    const act = String(c.action || "").replace(/\s+/g, "");
    if (act) rows.push(`<div class="pharm-row"><span class="k">药理</span><span class="pharm-action" title="${esc(c.action)}">${esc(act.length > 100 ? act.slice(0, 100) + "…" : act)}</span></div>`);
    const sims = (c.similar || []).slice(0, 5)
      .map((s) => `<button class="chip" data-sim-name="${esc(s)}">${esc(s)}</button>`).join("");
    const src = sourceHtml(c.source);
    if (rows.length || sims) {
      return `<div class="pharm-block">
        ${rows.join("")}
        ${sims ? `<div class="pharm-row"><span class="k">相似药</span><span class="similar-chips">${sims}</span></div>` : ""}
        ${src}
      </div>`;
    }
    return `<div class="no-pharm">（暂无药理资料，点击“详情”可查看 PubChem 药理信息）</div>`;
  }

  function cardHtml(c) {
    const zh = c.zh ? `<span class="zh">${esc(c.zh)}</span>` : "";
    const srcLabel = SOURCE_LABEL[c.source] || "";
    const groups = (c.groups || []).map((g) =>
      `<button class="g-chip" data-gid="${esc(g.id)}" title="${esc(g.en)}">${esc(g.symbol || g.zh)}</button>`
    ).join("");
    return `
      <div class="card-item" data-cid="${esc(c.cid)}">
        <div class="card-head">
          <div class="card-title">
            ${zh || esc(c.iupac || "化合物")}
            ${srcLabel ? `<span class="badge">${esc(srcLabel)}</span>` : ""}
            ${c.category ? `<span class="badge cat">${esc(c.category)}</span>` : ""}
          </div>
          <div class="card-iupac">${esc(c.iupac || "")}</div>
        </div>
        <div class="struct" data-smiles="${esc(c.smiles || "")}"><div class="spinner"></div></div>
        <div class="card-body">
          ${pharmBlockHtml(c)}
          ${c.smiles ? `<div class="smiles-line"><span>${esc(c.smiles)}</span><button class="copy-btn" data-copy="${esc(c.smiles)}">⧉</button></div>` : ""}
          ${groups ? `<div class="groups-row">${groups}</div>` : ""}
          <div class="card-actions">
            <button class="btn-mini pin-btn" data-act="pin" data-cid="${esc(c.cid)}">📌 固定</button>
            <button class="btn-mini" data-act="detail">详情</button>
            <button class="btn-mini" data-act="similar">相似化合物</button>
            <button class="btn-mini" data-act="pubchem">PubChem ↗</button>
          </div>
        </div>
      </div>`;
  }

  function renderCandidateCards(list, container, small) {
    list.forEach((c) => {
      const wrap = document.createElement("div");
      wrap.innerHTML = cardHtml(c).trim();
      const node = wrap.firstElementChild;
      container.appendChild(node);
      const struct = node.querySelector(".struct");
      if (struct && c.smiles) {
        ensureIO().observe(struct);
      } else if (struct) {
        struct.innerHTML = `<div class="placeholder">无 SMILES</div>`;
      }
    });
    refreshPinButtons();
  }

  function showMore() {
    const more = state.candidates.slice(state.shown, state.shown + state.pageSize);
    state.shown += more.length;
    renderCandidateCards(more, $("#results"), false);
    $("#more-wrap").classList.toggle("hidden", state.shown >= state.candidates.length);
    $("#more-btn").textContent = `加载更多（已显示 ${state.shown}/${state.candidates.length}）`;
  }

  function clearResults() {
    $("#results").innerHTML = "";
    $("#results-header").classList.add("hidden");
    $("#group-match-panel").classList.add("hidden");
    $("#group-match-grid").innerHTML = "";
    $("#category-panel").classList.add("hidden");
    $("#category-tree").innerHTML = "";
    $("#category-sar").innerHTML = "";
    $("#more-wrap").classList.add("hidden");
    $("#similar-panel").classList.add("hidden");
    state.candidates = [];
    state.shown = 0;
  }

  function switchTab(name) {
    $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  }

  function renderGroupMatches(groups) {
    const panel = $("#group-match-panel");
    const grid = $("#group-match-grid");
    if (!groups.length) {
      panel.classList.add("hidden");
      return;
    }
    $("#group-match-title").textContent = `🧪 官能团匹配（${groups.length}）`;
    grid.innerHTML = groups.map(groupCardHtml).join("");
    grid.querySelectorAll("[data-group-img][data-smiles]").forEach((el) => {
      if (el.dataset.smiles) ensureIO().observe(el);
      else el.innerHTML = `<div class="placeholder">无 SMILES</div>`;
    });
    panel.classList.remove("hidden");
    refreshPinButtons();
  }

  function categoryNodeHtml(node, depth) {
    const children = node.children || [];
    const drugs = node.drugs || [];
    const body = `
      ${node.description ? `<p class="category-desc">${esc(node.description)}</p>` : ""}
      ${drugs.length ? `<div class="category-drugs">${drugs.map((name) =>
        `<button class="drug-link" data-search-q="${esc(name)}">${esc(name)}</button>`).join("")}</div>` : ""}
      ${children.length ? `<div class="category-children">${children.map((child) => categoryNodeHtml(child, depth + 1)).join("")}</div>` : ""}
      ${node.source ? `<div class="category-source">教材依据：${esc(node.source)}</div>` : ""}`;
    return `<details class="category-node depth-${depth}" ${depth < 2 ? "open" : ""}>
      <summary><span>${esc(node.name)}</span><span class="category-count">${esc(node.drug_count || drugs.length)} 种药</span></summary>
      <div class="category-node-body">${body}</div>
    </details>`;
  }

  function renderCategoryMatches(matches, sar, basis) {
    const panel = $("#category-panel");
    if (!matches.length) {
      panel.classList.add("hidden");
      return;
    }
    $("#category-title").textContent = `📚 教材药物分类（${matches.length} 个匹配分支）`;
    $("#category-basis").textContent = basis || "";
    $("#category-tree").innerHTML = matches.map((node) => categoryNodeHtml(node, 0)).join("");
    $("#category-sar").innerHTML = sar.length ? `
      <h3 class="sar-section-title">构效关系（教材明确列出的类别）</h3>
      <div class="sar-grid">${sar.map((item) => `
        <article class="sar-card">
          <img src="${esc(item.image)}" alt="${esc(item.title)}母体结构式与位点编号" loading="lazy">
          <div class="sar-card-body">
            <h4>${esc(item.title)}</h4>
            <p>${esc(item.summary)}</p>
            <ol>${(item.points || []).map((point) => `<li>${esc(point)}</li>`).join("")}</ol>
            <div class="category-source">${esc(item.source || "")}</div>
          </div>
        </article>`).join("")}</div>` : "";
    panel.classList.remove("hidden");
  }

  function doSearch(q, type) {
    state.query = q;
    state.type = type;
    clearResults();
    showMessage(`正在检索“${esc(q)}”…`, "info");
    setSearchProgress("正在连接检索服务…");
    const btn = $("#search-form button[type=submit]");
    btn.disabled = true;
    let matchedCount = null;
    apiStream("/api/search", { q, type, online: state.online, stream: true }, (ev) => {
      if (ev.stage === "cids") {
        matchedCount = ev.count;
        setSearchProgress(`已匹配 ${ev.count} 种候选化合物，正在加载资料…`);
      } else if (ev.stage === "props") {
        const base = matchedCount != null
          ? `已匹配 ${matchedCount} 种候选化合物，正在加载资料（${ev.loaded}/${ev.total}）…`
          : `正在加载资料（${ev.loaded}/${ev.total}）…`;
        setSearchProgress(base);
      }
    })
      .then((res) => {
        showMessage("");
        setSearchProgress("");
        const gm = (res.groups_match || [])
          .map((m) => (m && typeof m === "object" ? state.groupsById[m.id] : state.groupsById[m]))
          .filter(Boolean);
        const categoryMatches = res.category_matches || [];
        const sar = res.sar || [];
        state.candidates = res.candidates || [];
        state.shown = 0;
        const typeLabel = SOURCE_LABEL[res.type] || res.type || "自动识别";
        let header = `共 <strong>${res.total}</strong> 个候选（按 ${esc(typeLabel)}）`;
        if (res.matched_zh) header += ` · 匹配“${esc(res.matched_zh)}”`;
        if (res.truncated) header += ` · 已显示前 ${state.candidates.length} 个`;
        if (res.offline) header += ` · 离线模式`;
        if (!state.candidates.length && !gm.length && !categoryMatches.length) {
          $("#results-header").innerHTML = header;
          $("#results-header").classList.remove("hidden");
          showMessage("未找到匹配的化合物或官能团，请尝试更精确的名称、分子式或 SMILES。", "warn");
          return;
        }
        renderCategoryMatches(categoryMatches, sar, res.category_basis || "");
        renderGroupMatches(gm);
        if (categoryMatches.length) {
          $("#results-header").innerHTML = `按教材分类命中 <strong>${categoryMatches.length}</strong> 个分支，共列出 <strong>${res.total}</strong> 个药物条目`;
          $("#results-header").classList.remove("hidden");
        } else if (state.candidates.length) {
          $("#results-header").innerHTML = header;
          $("#results-header").classList.remove("hidden");
          showMore();
        } else if (gm.length) {
          $("#results-header").innerHTML = `共 <strong>${gm.length}</strong> 个官能团匹配：${gm.map((g) => esc(g.zh)).join("、")}`;
          $("#results-header").classList.remove("hidden");
        }
      })
      .catch((e) => {
        setSearchProgress("");
        showMessage(e.message, "err");
        $("#results-header").classList.add("hidden");
      })
      .finally(() => { btn.disabled = false; });
  }

  /* ---------------- 详情弹窗 ---------------- */
  function openDetail(cid, smiles, knownZh) {
    const modal = $("#modal");
    const body = $("#modal-body");
    body.innerHTML = `<div class="m-title">加载中…</div><div class="m-sub">CID ${esc(cid)}</div>`;
    modal.classList.remove("hidden");
    api("/api/compound", { cid })
      .then((d) => {
        const zh = d.zh || knownZh || "";
        const groups = (d.groups || []).map((g) =>
          `<button class="g-chip" data-gid="${esc(g.id)}">${esc(g.symbol || g.zh)}</button>`
        ).join("");
        const sims = (d.similar || []).map((s) =>
          `<button class="chip" data-sim-name="${esc(s)}">${esc(s)}</button>`).join("");
        const names = (d.names || []).slice(0, 6).map((n) => esc(n)).join("；");
        const smi = d.smiles || smiles || "";
        body.innerHTML = `
          <div class="m-title">${zh ? esc(zh) : esc(d.iupac || "化合物")}
            ${d.cid ? `<span class="badge">CID ${esc(d.cid)}</span>` : ""}
            ${d.category ? `<span class="badge cat">${esc(d.category)}</span>` : ""}
          </div>
          <div class="m-sub">${esc(d.iupac || "")}${d.cas ? ` · CAS ${esc(d.cas)}` : ""}</div>
          <div class="m-layout">
            <div class="m-img" data-m-smiles="${esc(smi)}"><div class="spinner"></div></div>
            <div class="m-info">
              ${d.parent ? `<div class="m-block"><h4>药物母体</h4><p>${esc(d.parent)}</p></div>` : ""}
              ${d.pharmacophore ? `<div class="m-block"><h4>药效基团</h4><p>${esc(d.pharmacophore)}</p></div>` : ""}
              ${d.target ? `<div class="m-block"><h4>作用靶点</h4><p>${esc(d.target)}</p></div>` : ""}
              <div class="m-block"><h4>药理作用</h4><p id="m-action">${esc(d.action || "加载中…")}</p></div>
              <div class="m-block"><h4>代谢与毒理</h4><p id="m-mt">${esc(d.mt || "加载中…")}</p></div>
              ${d.source && d.source.length ? `<div class="m-block">${sourceHtml(d.source)}</div>` : ""}
              ${d.sar ? `<div class="m-block"><h4>构效关系（SAR）</h4><p>${esc(d.sar)}</p></div>` : ""}
              ${sims ? `<div class="m-block"><h4>相似药物</h4><div class="similar-chips">${sims}</div></div>` : ""}
              ${groups ? `<div class="m-block"><h4>检出的官能团</h4><div class="groups-row">${groups}</div></div>` : ""}
              <details class="m-details">
                <summary>理化性质（分子量 / LogP / TPSA / 氢键 / 环数）</summary>
                <table class="m-table">
                  <tr><td>分子式</td><td>${esc(d.formula || "—")}</td></tr>
                  <tr><td>分子量</td><td>${esc(d.mw || "—")} g/mol</td></tr>
                  <tr><td>精确质量</td><td>${esc(d.exact_mass || "—")}</td></tr>
                  <tr><td>LogP</td><td>${esc(d.xlogp != null ? d.xlogp : "—")}</td></tr>
                  <tr><td>TPSA (Å²)</td><td>${esc(d.tpsa != null ? d.tpsa : "—")}</td></tr>
                  <tr><td>氢键供体/受体</td><td>${esc(d.hbd != null ? d.hbd : "—")} / ${esc(d.hba != null ? d.hba : "—")}</td></tr>
                  <tr><td>可旋转键</td><td>${esc(d.rotb != null ? d.rotb : "—")}</td></tr>
                  <tr><td>InChIKey</td><td>${esc(d.inchikey || "—")}</td></tr>
                </table>
              </details>
              ${names ? `<div class="names-line">别名：${names}</div>` : ""}
            </div>
          </div>
          <div class="m-actions">
            <button class="btn-mini alt" id="m-pin">📌 固定</button>
            <button class="btn-mini" id="m-similar">🧬 相似化合物</button>
            ${d.cid ? `<button class="btn-mini" data-act="pubchem" data-cid="${esc(d.cid)}">PubChem ↗</button>` : ""}
            <button class="btn-mini" id="m-close">关闭</button>
          </div>`;
        const mimg = body.querySelector("[data-m-smiles]");
        fillStructBox(mimg, smi);
        $("#m-close").onclick = () => modal.classList.add("hidden");
        $("#m-similar").onclick = () => { modal.classList.add("hidden"); loadSimilar(d.cid, zh || d.iupac); };
        $("#m-pin").onclick = () => {
          togglePin({
            cid: d.cid, zh: zh, iupac: d.iupac, smiles: smi,
            formula: d.formula, category: d.category,
            parent: d.parent, pharmacophore: d.pharmacophore, target: d.target,
            action: d.action, similar: d.similar || [], groups: d.groups || [],
          });
        };
        if (!d.action || !d.mt) {
          api("/api/pharm", { cid: d.cid, zh: zh }).then((ph) => {
            if (ph.action) $("#m-action").textContent = ph.action;
            if (ph.mt) $("#m-mt").textContent = ph.mt;
            if (!ph.action && !ph.mt) {
              $("#m-action").textContent = "暂无资料";
              $("#m-mt").textContent = "暂无资料";
            }
          }).catch(() => {
            $("#m-action").textContent = "暂无资料";
            $("#m-mt").textContent = "暂无资料";
          });
        }
      })
      .catch((e) => {
        body.innerHTML = `<div class="m-title">加载失败</div><div class="m-sub">${esc(e.message)}</div>`;
      });
  }

  /* ---------------- 相似化合物 ---------------- */
  function loadSimilar(cid, name) {
    switchTab("search");
    const panel = $("#similar-panel");
    const grid = $("#similar-grid");
    $("#similar-title").textContent = `🧬 与「${name || cid}」2D 结构相似的化合物（≥90%，PubChem Tanimoto）`;
    grid.innerHTML = `<div class="msg info">正在获取相似化合物…</div>`;
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    api("/api/similar", { cid, threshold: 90, max: 12, online: state.online })
      .then((res) => {
        grid.innerHTML = "";
        if (!res.candidates || !res.candidates.length) {
          grid.innerHTML = `<div class="msg warn">没有找到相似化合物。</div>`;
          return;
        }
        res.candidates.forEach((c) => {
          const common = (c.common || []).map((g) => `<span class="r-chip">${esc(g)}</span>`).join("");
          const wrap = document.createElement("div");
          wrap.innerHTML = `
            <div class="card-item" data-cid="${esc(c.cid)}">
              <div class="card-head">
                <div class="card-title"><span class="zh">${esc(c.zh || c.iupac || "化合物")}</span>
                  ${c.category ? `<span class="badge cat">${esc(c.category)}</span>` : ""}
                </div>
                <div class="card-iupac">${esc(c.iupac || "")}</div>
              </div>
              <div class="struct" data-smiles="${esc(c.smiles || "")}"><div class="spinner"></div></div>
              <div class="card-body">
                ${common ? `<div class="facts">共同结构：${common}</div>` : ""}
                <div class="card-actions">
                  <button class="btn-mini" data-act="detail">详情</button>
                  <button class="btn-mini" data-act="pubchem">PubChem ↗</button>
                </div>
              </div>
            </div>`.trim();
          const node = wrap.firstElementChild;
          grid.appendChild(node);
          const struct = node.querySelector(".struct");
          if (struct && c.smiles) ensureIO().observe(struct);
        });
      })
      .catch((e) => {
        grid.innerHTML = `<div class="msg err">${esc(e.message)}</div>`;
      });
  }

  /* ---------------- 官能团速查 ---------------- */
  const CAT_ORDER = ["烃类", "含氧基团", "含氮基团", "含硫·卤素", "杂环"];

  function groupCardHtml(g) {
    const reps = (g.representatives || []).map((r) =>
      `<button class="chip" data-rep-name="${esc(r.name)}" data-rep-en="${esc(r.en)}">${esc(r.name)}</button>`
    ).join("");
    const reactions = (g.reactions || []).map((r) => `<span class="r-chip">${esc(r)}</span>`).join("");
    const ph = g.pharmacophore || {};
    const phDrugs = (ph.drugs || []).map((d) =>
      `<button class="chip" data-rep-name="${esc(d.name)}" data-rep-en="${esc(d.en)}">${esc(d.name)}</button>`).join("");
    let phBox = "";
    if (ph.drug_class) {
      phBox = `<div class="pharm-box">
        <div class="label">🔑 药效基团信息</div>
        <div><b>对应药物类别：</b>${esc(ph.drug_class)}</div>
        ${ph.target ? `<div><b>作用靶点：</b>${esc(ph.target)}</div>` : ""}
        ${ph.sar ? `<div><b>构效关系：</b>${esc(ph.sar)}</div>` : ""}
        ${phDrugs ? `<div><b>代表药物：</b><div class="similar-chips">${phDrugs}</div></div>` : ""}
      </div>`;
    }
    return `
      <div class="group-card" data-group-id="${esc(g.id)}">
        <div class="group-top">
          <div class="group-img" data-group-img="${esc(g.id)}" data-smiles="${esc(g.smiles_example || "")}"><div class="spinner"></div></div>
          <div>
            <div class="g-head"><h3>${esc(g.zh)} <span class="g-symbol">${esc(g.symbol || "")}</span></h3></div>
            <div class="g-en">${esc(g.en || "")}</div>
            <p class="g-short">${esc(g.short || "")}</p>
          </div>
        </div>
        <details class="g-details">
          <summary>特点 / 性质 / 药效基团 / 代表药物</summary>
          <div class="g-desc">${esc(g.description || "")}</div>
          ${phBox}
          ${reactions ? `<div class="g-reactions">${reactions}</div>` : ""}
          ${g.hint ? `<div class="g-hint">💡 ${esc(g.hint)}</div>` : ""}
          ${reps ? `<div class="g-reps"><span class="label">代表化合物：</span>${reps}</div>` : ""}
        </details>
        <div class="g-actions">
          <button class="btn-mini" data-sub-smiles="${esc(g.substructure_smiles || g.smiles_example || "")}" data-group-zh="${esc(g.zh)}">查找含此基团的化合物</button>
          <button class="btn-mini" data-act="pin-group" data-gid="${esc(g.id)}">📌 固定</button>
        </div>
      </div>`;
  }

  function renderGroups() {
    const root = $("#groups-root");
    $("#group-count").textContent = state.groupsData.length;
    root.innerHTML = "";
    const cats = CAT_ORDER.concat(
      state.groupsData.map((g) => g.category).filter((c) => !CAT_ORDER.includes(c))
    ).filter((c, i, a) => a.indexOf(c) === i);
    cats.forEach((cat) => {
      const list = state.groupsData.filter((g) => g.category === cat);
      if (!list.length) return;
      const sec = document.createElement("section");
      sec.innerHTML = `
        <div class="cat-title">${esc(cat)}</div>
        <div class="groups-grid">${list.map(groupCardHtml).join("")}</div>`;
      root.appendChild(sec);
      list.forEach((g) => {
        const imgBox = sec.querySelector(`[data-group-img="${CSS.escape(g.id)}"]`);
        if (imgBox && g.smiles_example) ensureIO().observe(imgBox);
      });
    });
  }

  function filterGroups(text) {
    const t = normZh(text.trim().toLowerCase());
    $$(".group-card").forEach((card) => {
      const hay = normZh((card.textContent || "").toLowerCase());
      card.style.display = (!t || hay.includes(t)) ? "" : "none";
    });
    $$(".cat-title").forEach((ct) => {
      const section = ct.parentElement;
      const anyVisible = Array.from(section.querySelectorAll(".group-card")).some((c) => c.style.display !== "none");
      ct.style.display = anyVisible ? "" : "none";
    });
  }

  function showGroup(id) {
    switchTab("groups");
    const card = document.querySelector(`.group-card[data-group-id="${CSS.escape(id)}"]`);
    if (!card) return;
    const details = card.querySelector("details");
    if (details) details.open = true;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.style.boxShadow = "0 0 0 3px rgba(37,99,235,.35)";
    setTimeout(() => { card.style.boxShadow = ""; }, 1600);
  }

  function runSubstructure(smiles, zh) {
    if (!state.online) {
      showMessage("官能团子结构搜索需要联网，请打开“允许联网搜索”开关。", "err");
      return;
    }
    switchTab("groups");
    const panel = $("#substruct-panel");
    const grid = $("#substruct-grid");
    $("#substruct-title").textContent = `含「${zh || "该官能团"}」的化合物（PubChem 子结构搜索）`;
    grid.innerHTML = `<div class="msg info">正在搜索…（PubChem 子结构检索，可能需要十几秒）</div>`;
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    api("/api/substructure", { smiles, max: 24, online: state.online })
      .then((res) => {
        grid.innerHTML = "";
        if (!res.candidates || !res.candidates.length) {
          grid.innerHTML = `<div class="msg warn">没有找到匹配的化合物，可尝试用更简单的 SMILES。</div>`;
          return;
        }
        renderCandidateCards(res.candidates, grid, true);
      })
      .catch((e) => {
        grid.innerHTML = `<div class="msg err">${esc(e.message)}</div>`;
      });
  }

  /* ---------------- 事件绑定 ---------------- */
  function bindEvents() {
    $$(".tab").forEach((b) => {
      b.addEventListener("click", () => switchTab(b.dataset.tab));
    });

    $("#search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      doSearch($("#q").value, $("#type").value);
    });

    $$(".chip[data-q]").forEach((c) => {
      c.addEventListener("click", () => {
        $("#q").value = c.dataset.q;
        doSearch(c.dataset.q, "auto");
      });
    });

    $("#more-btn").addEventListener("click", showMore);
    $("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
    $("#modal").addEventListener("click", (e) => {
      if (e.target === $("#modal")) $("#modal").classList.add("hidden");
    });

    $("#group-filter").addEventListener("input", (e) => filterGroups(e.target.value));

    $("#online-toggle").addEventListener("change", (e) => {
      state.online = e.target.checked;
      localStorage.setItem("ch_online", state.online ? "1" : "0");
      showMessage(state.online
        ? "已开启联网搜索：可使用 PubChem 全库检索、相似化合物与结构渲染。"
        : "已关闭联网搜索：仅使用本地词典（约 614 种药物）与本地渲染。", "info");
    });

    $("#pinned-clear").addEventListener("click", () => {
      state.pinned = [];
      savePinned();
      renderPinned();
      $("#pinned-windows").innerHTML = "";
      refreshPinButtons();
    });

    document.addEventListener("click", (e) => {
      const copyBtn = e.target.closest("[data-copy]");
      if (copyBtn) {
        navigator.clipboard.writeText(copyBtn.dataset.copy).then(() => {
          const old = copyBtn.textContent;
          copyBtn.textContent = "✓";
          setTimeout(() => { copyBtn.textContent = old; }, 900);
        }).catch(() => {});
        return;
      }
      const gchip = e.target.closest("[data-gid]:not([data-act='pin-group'])");
      if (gchip) {
        showGroup(gchip.dataset.gid);
        return;
      }
      const simName = e.target.closest("[data-sim-name]");
      if (simName) {
        switchTab("search");
        $("#q").value = simName.dataset.simName;
        doSearch(simName.dataset.simName, "name");
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      const categoryDrug = e.target.closest("[data-search-q]");
      if (categoryDrug) {
        const query = categoryDrug.dataset.searchQ;
        $("#q").value = query;
        doSearch(query, "name");
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      const pinBtn = e.target.closest('[data-act="pin"]');
      if (pinBtn) {
        const card = pinBtn.closest(".card-item");
        const cid = card.dataset.cid;
        const full = state.candidates.find((x) => String(x.cid) === String(cid));
        const c = {
          cid: cid,
          zh: card.querySelector(".zh")?.textContent || "",
          iupac: card.querySelector(".card-iupac")?.textContent.split(" · ")[0] || "",
          smiles: card.querySelector(".struct")?.dataset.smiles || "",
          formula: "",
          category: card.querySelector(".badge.cat")?.textContent || "",
        };
        togglePin(Object.assign(c, full || {}));
        return;
      }
      const pinGroupBtn = e.target.closest('[data-act="pin-group"]');
      if (pinGroupBtn) {
        const g = state.groupsById[pinGroupBtn.dataset.gid];
        if (g) togglePinGroup(g);
        return;
      }
      const detailBtn = e.target.closest('[data-act="detail"]');
      if (detailBtn) {
        const card = detailBtn.closest(".card-item");
        if (!card.dataset.cid) {
          showMessage("该化合物没有 PubChem CID，暂无法查看在线详情。", "warn");
          return;
        }
        openDetail(card.dataset.cid, card.querySelector(".struct")?.dataset.smiles || "");
        return;
      }
      const simBtn = e.target.closest('[data-act="similar"]');
      if (simBtn) {
        const card = simBtn.closest(".card-item");
        const name = card.querySelector(".zh")?.textContent || card.querySelector(".card-iupac")?.textContent.split(" · ")[0] || "";
        loadSimilar(card.dataset.cid, name);
        return;
      }
      const pubBtn = e.target.closest('[data-act="pubchem"]');
      if (pubBtn) {
        const cid = pubBtn.dataset.cid || pubBtn.closest(".card-item")?.dataset.cid;
        if (cid) window.open(`https://pubchem.ncbi.nlm.nih.gov/compound/${cid}`, "_blank");
        return;
      }
      const rep = e.target.closest("[data-rep-en]");
      if (rep) {
        switchTab("search");
        $("#q").value = rep.dataset.repName;
        doSearch(rep.dataset.repName, "name");
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      const sub = e.target.closest("[data-sub-smiles]");
      if (sub) {
        runSubstructure(sub.dataset.subSmiles, sub.dataset.groupZh);
        return;
      }
      const pRemove = e.target.closest("[data-p-remove]");
      if (pRemove) {
        removePinByKey(pRemove.dataset.pRemove);
        return;
      }
      const dirItem = e.target.closest("[data-dir-key]");
      if (dirItem) {
        focusPinWindow(dirItem.dataset.dirKey);
        return;
      }
    });
  }

  /* ---------------- 启动 ---------------- */
  function initPinnedPanel() {
    const panel = $("#pinned-panel");
    const head = panel.querySelector(".pinned-head");

    const savedCollapsed = localStorage.getItem("ch_pinned_collapsed") === "1";
    panel.classList.toggle("collapsed", savedCollapsed);
    $("#pinned-collapse").textContent = savedCollapsed ? "展开" : "收起";
    $("#pinned-collapse").addEventListener("click", () => {
      const collapsed = panel.classList.toggle("collapsed");
      localStorage.setItem("ch_pinned_collapsed", collapsed ? "1" : "0");
      $("#pinned-collapse").textContent = collapsed ? "展开" : "收起";
    });

    let savedPos = null;
    try { savedPos = JSON.parse(localStorage.getItem("ch_pinned_pos") || "null"); } catch (e) { savedPos = null; }
    if (savedPos && typeof savedPos.x === "number" && typeof savedPos.y === "number") {
      panel.style.left = savedPos.x + "px";
      panel.style.top = savedPos.y + "px";
      panel.style.right = "auto";
    }

    let drag = null;
    head.addEventListener("mousedown", (e) => {
      if (e.target.closest("button") || e.target.closest("input")) return;
      const rect = panel.getBoundingClientRect();
      drag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!drag) return;
      const x = Math.min(Math.max(e.clientX - drag.dx, 0), window.innerWidth - 180);
      const y = Math.min(Math.max(e.clientY - drag.dy, 0), window.innerHeight - 60);
      panel.style.left = x + "px";
      panel.style.top = y + "px";
      panel.style.right = "auto";
    });
    document.addEventListener("mouseup", () => {
      if (!drag) return;
      drag = null;
      const rect = panel.getBoundingClientRect();
      localStorage.setItem("ch_pinned_pos", JSON.stringify({
        x: Math.round(rect.left),
        y: Math.round(rect.top),
      }));
    });
  }

  async function init() {
    bindEvents();
    initPinnedPanel();
    $("#online-toggle").checked = state.online;
    try {
      const [g] = await Promise.all([
        getJSON("/api/groups").catch(() => null),
      ]);
      if (g && g.groups) {
        state.groupsData = g.groups;
        state.groupsById = Object.fromEntries(g.groups.map((x) => [x.id, x]));
        renderGroups();
      }
    } catch (e) {
      showMessage("初始化数据失败：" + e.message, "err");
    }
    try {
      state.pinned = JSON.parse(localStorage.getItem("ch_pinned_v1") || "[]")
        .filter((p) => p && (p.cid || (p.type === "group" && p.gid)));
    } catch (e) {
      state.pinned = [];
    }
    renderPinned();
    renderPinWindows();
  }

  init();
})();
