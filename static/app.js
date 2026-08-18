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
  function savePinned() {
    localStorage.setItem("ch_pinned_v1", JSON.stringify(state.pinned.slice(0, 12)));
  }

  function isPinned(cid) {
    return state.pinned.some((p) => String(p.cid) === String(cid));
  }

  function togglePin(c) {
    if (isPinned(c.cid)) {
      state.pinned = state.pinned.filter((p) => String(p.cid) !== String(c.cid));
    } else {
      if (state.pinned.length >= 12) {
        showMessage("对比栏最多固定 12 个，请先移除部分条目。", "warn");
        return;
      }
      state.pinned.push({
        cid: c.cid, zh: c.zh || "", iupac: c.iupac || "",
        smiles: c.smiles || "", formula: c.formula || "", category: c.category || "",
      });
    }
    savePinned();
    renderPinned();
    refreshPinButtons();
  }

  function refreshPinButtons() {
    $$(".pin-btn").forEach((b) => {
      const cid = b.dataset.cid;
      const on = isPinned(cid);
      b.textContent = on ? "📌 已固定" : "📌 固定";
      b.classList.toggle("pinned", on);
    });
  }

  function renderPinned() {
    const list = $("#pinned-list");
    $("#pinned-count").textContent = state.pinned.length;
    if (!state.pinned.length) {
      list.innerHTML = `<div class="pinned-empty">还没有固定条目。在结果卡片上点“📌 固定”，即可把结构留在旁边与下一个检索结果比对。</div>`;
      return;
    }
    list.innerHTML = state.pinned.map((p, i) => `
      <div class="pinned-item" data-i="${i}">
        <div class="p-img" data-p-smiles="${esc(p.smiles)}"><div class="spinner"></div></div>
        <div class="p-info">
          <div class="p-name">${esc(p.zh || p.iupac || "化合物")}</div>
          <div class="p-sub">${esc(p.category || p.formula || p.iupac || "")}</div>
          <div class="p-actions">
            <button class="btn-mini" data-p-act="detail">详情</button>
            <button class="btn-mini" data-p-act="remove">移除</button>
          </div>
        </div>
      </div>`).join("");
    list.querySelectorAll("[data-p-smiles]").forEach((b) => fillStructBox(b, b.dataset.pSmiles));
  }

  /* ---------------- 结果卡片 ---------------- */
  function pharmBlockHtml(c) {
    const rows = [];
    if (c.parent) rows.push(`<div class="pharm-row"><span class="k">母体</span><span>${esc(c.parent)}</span></div>`);
    if (c.pharmacophore) rows.push(`<div class="pharm-row"><span class="k">药效基团</span><span>${esc(c.pharmacophore)}</span></div>`);
    if (c.target) rows.push(`<div class="pharm-row"><span class="k">靶点</span><span>${esc(c.target)}</span></div>`);
    if (c.action) rows.push(`<div class="pharm-row"><span class="k">药理</span><span class="pharm-action" title="${esc(c.action)}">${esc(c.action)}</span></div>`);
    const sims = (c.similar || []).slice(0, 5)
      .map((s) => `<button class="chip" data-sim-name="${esc(s)}">${esc(s)}</button>`).join("");
    if (rows.length || sims) {
      return `<div class="pharm-block">
        ${rows.join("")}
        ${sims ? `<div class="pharm-row"><span class="k">相似药</span><span class="similar-chips">${sims}</span></div>` : ""}
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
    $("#more-wrap").classList.add("hidden");
    $("#similar-panel").classList.add("hidden");
    state.candidates = [];
    state.shown = 0;
  }

  function switchTab(name) {
    $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  }

  function doSearch(q, type) {
    state.query = q;
    state.type = type;
    clearResults();
    showMessage(`正在检索“${esc(q)}”…`, "info");
    const btn = $("#search-form button[type=submit]");
    btn.disabled = true;
    api("/api/search", { q, type, online: state.online })
      .then((res) => {
        showMessage("");
        const gm = res.groups_match || [];
        if ((!res.candidates || !res.candidates.length) && gm.length) {
          switchTab("groups");
          showGroup(gm[0].id);
          showMessage(`“${esc(q)}”匹配到官能团：${gm.map((g) => esc(g.zh)).join("、")}，已为你打开对应的官能团卡片。`, "ok");
          return;
        }
        state.candidates = res.candidates || [];
        state.shown = 0;
        const typeLabel = SOURCE_LABEL[res.type] || res.type || "自动识别";
        let header = `共 <strong>${res.total}</strong> 个候选（按 ${esc(typeLabel)}）`;
        if (res.matched_zh) header += ` · 匹配“${esc(res.matched_zh)}”`;
        if (res.truncated) header += ` · 已显示前 ${state.candidates.length} 个`;
        if (res.offline) header += ` · 离线模式`;
        if (!state.candidates.length) {
          $("#results-header").innerHTML = header;
          $("#results-header").classList.remove("hidden");
          showMessage("找到候选但缺少属性数据，请尝试更精确的查询。", "warn");
          return;
        }
        $("#results-header").innerHTML = header;
        $("#results-header").classList.remove("hidden");
        showMore();
      })
      .catch((e) => {
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
      const gchip = e.target.closest("[data-gid]");
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
      const pinBtn = e.target.closest('[data-act="pin"]');
      if (pinBtn) {
        const card = pinBtn.closest(".card-item");
        const c = {
          cid: card.dataset.cid,
          zh: card.querySelector(".zh")?.textContent || "",
          iupac: card.querySelector(".card-iupac")?.textContent.split(" · ")[0] || "",
          smiles: card.querySelector(".struct")?.dataset.smiles || "",
          formula: "",
          category: card.querySelector(".badge.cat")?.textContent || "",
        };
        togglePin(c);
        return;
      }
      const detailBtn = e.target.closest('[data-act="detail"]');
      if (detailBtn) {
        const card = detailBtn.closest(".card-item");
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
      const pDetail = e.target.closest('[data-p-act="detail"]');
      if (pDetail) {
        const item = pDetail.closest(".pinned-item");
        const p = state.pinned[Number(item.dataset.i)];
        openDetail(p.cid, p.smiles, p.zh);
        return;
      }
      const pRemove = e.target.closest('[data-p-act="remove"]');
      if (pRemove) {
        const item = pRemove.closest(".pinned-item");
        const p = state.pinned[Number(item.dataset.i)];
        state.pinned = state.pinned.filter((x) => String(x.cid) !== String(p.cid));
        savePinned();
        renderPinned();
        refreshPinButtons();
      }
    });
  }

  /* ---------------- 启动 ---------------- */
  async function init() {
    bindEvents();
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
      state.pinned = JSON.parse(localStorage.getItem("ch_pinned_v1") || "[]").filter((p) => p && p.cid);
    } catch (e) {
      state.pinned = [];
    }
    renderPinned();
  }

  init();
})();
