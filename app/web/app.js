/* 민사법 AI (KANTNYANGI) — 채팅 화면.
   서버 API(/api/config, /api/chat)만 부르고, 정답·판정·근거는 응답에 있는 값만 그린다 (목업 데이터 없음). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app"), thread = $("#thread"), scroll = $("#scroll"), input = $("#input"), sendBtn = $("#send");
  const KEY = { convs: "kantnyangi.convs.v1", notes: "kantnyangi.notes.v1", settings: "kantnyangi.settings.v1", groups: "kantnyangi.groups.v1" };

  // ---------------------------------------------------------------- 저장 (이 브라우저에만)
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장 불가여도 화면은 동작 */ } },
  };
  const state = {
    config: null,
    settings: store.get(KEY.settings, {}),
    convs: store.get(KEY.convs, []),
    notes: store.get(KEY.notes, []),
    closedGroups: store.get(KEY.groups, []),
    currentId: null, intent: null, pending: false, view: "chat",
    panel: { i: null, k: null, filter: "all", focus: null },
  };
  state.convs.forEach((c) => {
    c.messages = (c.messages || []).filter((m) => !m.pending);
    c.messages.forEach((m) => { if (m.run && m.run.status === "running") m.run.status = "stopped"; }); // 새로고침 → 멈춤
  });
  state.attachment = null;
  const saveConvs = () => store.set(KEY.convs, state.convs.slice(0, 100));
  const current = () => state.convs.find((c) => c.id === state.currentId) || null;

  // ---------------------------------------------------------------- 유틸
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icons = () => window.lucide && window.lucide.createIcons();
  const icon = (n, cls = "") => `<i data-lucide="${n}"${cls ? ` class="${cls}"` : ""}></i>`;
  const uid = () => Math.random().toString(36).slice(2, 10);
  const short = (s, n) => { s = String(s || "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1800);
  }
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  function prose(text) {
    return String(text || "").trim().split(/\n{2,}/).map((b) => {
      const lines = b.split("\n");
      if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) return "<ul>" + lines.map((l) => `<li>${inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>`).join("") + "</ul>";
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    }).join("");
  }
  // 판단에 쓴 인용 문장을 원문에서 찾아 강조 (공백 차이 무시). 못 찾으면 강조하지 않는다.
  function highlight(text, quotes) {
    const ranges = [], idx = []; let sq = "";
    for (let i = 0; i < text.length; i++) if (!/\s/.test(text[i])) { idx.push(i); sq += text[i]; }
    for (let q of quotes) {
      q = String(q || "").replace(/\s+/g, "");
      for (const part of q.split(/…|\.\.\./).map((p) => p.replace(/^["“”'.]+|["“”'.]+$/g, "")).filter((p) => p.length >= 8)) {
        const at = sq.indexOf(part);
        if (at >= 0) ranges.push([idx[at], idx[at + part.length - 1] + 1]);
      }
    }
    if (!ranges.length) return esc(text);
    ranges.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const r of ranges) { const l = merged[merged.length - 1]; if (l && r[0] <= l[1]) l[1] = Math.max(l[1], r[1]); else merged.push([...r]); }
    let out = "", pos = 0;
    for (const [a, b] of merged) { out += esc(text.slice(pos, a)) + "<mark>" + esc(text.slice(a, b)) + "</mark>"; pos = b; }
    return out + esc(text.slice(pos));
  }
  // 원본 위치·버전 표기를 읽기 좋게 (값 자체는 그대로, 형식만)
  const prettyLoc = (s) => String(s || "").replace(/^§\s*/, "").replace(/\s*\/\s*L\d+(-\d+)?$/, "");
  const prettyVer = (s) => { const m = String(s || "").match(/시행\s*(\d{4})(\d{2})(\d{2})/); return m ? `${m[1]}. ${+m[2]}. ${+m[3]}. 시행` : (s || ""); };
  const docName = (d) => d.kind === "case" ? `대법원 ${d.case_no || d.title}` : `${d.title} ${d.article || ""}${d.article_title ? ` (${d.article_title})` : ""}`.trim();

  // ---------------------------------------------------------------- 모델·검색 설정
  async function loadConfig() {
    try {
      const r = await fetch("/api/config");
      if (!r.ok) throw new Error(r.status);
      state.config = await r.json();
    } catch { $("#pickerLabel").textContent = "서버 연결 안 됨"; return; }
    const c = state.config, s = state.settings;
    if (!c.models.some((m) => m.id === s.model)) s.model = (c.models.find((m) => m.default) || c.models[0]).id;
    if (!c.modes.some((m) => m.id === s.mode)) s.mode = c.modes[0].id;
    if (!c.presets.some((p) => p.id === s.preset)) s.preset = c.default_preset;
    store.set(KEY.settings, s);
    $("#asof span").textContent = c.asof ? `기준일 ${c.asof}` : "";
    renderPicker();
  }
  function renderPicker() {
    const c = state.config; if (!c) return;
    const s = state.settings, m = c.models.find((x) => x.id === s.model);
    $("#pickerLabel").textContent = m ? m.label : "모델";
    const opt = (g, id, title, desc, on) =>
      `<button class="opt ${on ? "on" : ""}" role="menuitemradio" aria-checked="${on}" data-g="${g}" data-id="${esc(id)}"><span><b>${esc(title)}</b>${desc ? `<small>${esc(desc)}</small>` : ""}</span><span class="ck">${icon("check")}</span></button>`;
    $("#menu").innerHTML =
      `<h6>답변 모델</h6>` + c.models.map((x) => opt("model", x.id, x.label, x.note, x.id === s.model)).join("") +
      `<hr><h6>검색 방식</h6>` + c.modes.map((x) => opt("mode", x.id, x.label, x.desc, x.id === s.mode)).join("") +
      `<hr><h6>기출 풀이 방식</h6>` + c.presets.map((x) => opt("preset", x.id, x.id, x.desc, x.id === s.preset)).join("");
    icons();
  }
  function toggleMenu(open) {
    const btn = $("#pickerBtn"), menu = $("#menu");
    open = open ?? menu.hidden;
    menu.hidden = !open; btn.setAttribute("aria-expanded", String(open));
    if (open) (menu.querySelector(".opt.on") || menu.querySelector(".opt"))?.focus();
  }
  $("#pickerBtn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
  $("#btnSettings").addEventListener("click", (e) => { e.stopPropagation(); app.classList.remove("drawer"); toggleMenu(true); });
  $("#menu").addEventListener("click", (e) => {
    const b = e.target.closest(".opt"); if (!b) return;
    state.settings[b.dataset.g] = b.dataset.id; store.set(KEY.settings, state.settings);
    renderPicker(); toggleMenu(false); $("#pickerBtn").focus();
  });
  $("#menu").addEventListener("keydown", (e) => {
    const items = [...$("#menu").querySelectorAll(".opt")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".picker") && !e.target.closest("#btnSettings")) toggleMenu(false); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#team").hidden) return closeTeam();
    if (!$("#menu").hidden) { toggleMenu(false); $("#pickerBtn").focus(); }
    else if (!$("#panel").hidden) closePanel();
    else app.classList.remove("drawer");
  });

  // ---------------------------------------------------------------- 사이드바
  const mobile = () => window.matchMedia("(max-width: 820px)").matches;
  $("#btnCollapse").addEventListener("click", () => app.classList.add("collapsed"));
  $("#btnExpand").addEventListener("click", () => mobile() ? app.classList.add("drawer") : app.classList.remove("collapsed"));
  $("#scrim").addEventListener("click", () => app.classList.remove("drawer"));
  $("#btnNew").addEventListener("click", () => { newChat(); app.classList.remove("drawer"); });
  $("#btnNotes").addEventListener("click", () => { showNotes(); app.classList.remove("drawer"); });
  $("#search").addEventListener("input", renderHistory);

  function groupOf(ts) {
    const d = new Date(ts), now = new Date();
    const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((day(now) - day(d)) / 86400000);
    return diff <= 0 ? "오늘" : diff === 1 ? "어제" : diff < 7 ? "이번 주" : diff < 14 ? "지난주" : "이전";
  }
  function renderHistory() {
    const q = $("#search").value.trim().toLowerCase();
    const list = state.convs.filter((c) => !q || c.title.toLowerCase().includes(q) ||
      c.messages.some((m) => m.role === "user" && m.text.toLowerCase().includes(q)));
    const el = $("#history");
    $("#noteCount").textContent = state.notes.length || "";
    if (!list.length) { el.innerHTML = `<div class="sb-empty">${q ? "검색 결과가 없어요" : "아직 대화가 없어요"}</div>`; return; }
    const groups = [];
    for (const c of list) { const g = groupOf(c.updatedAt); let G = groups.find((x) => x.name === g); if (!G) groups.push(G = { name: g, items: [] }); G.items.push(c); }
    el.innerHTML = groups.map((G) => {
      const closed = !q && state.closedGroups.includes(G.name);
      return `<button class="grp ${closed ? "closed" : ""}" data-grp="${G.name}" aria-expanded="${!closed}">${G.name}${icon("chevron-down")}</button>` +
        (closed ? "" : G.items.map((c) => `<div class="conv ${c.id === state.currentId && state.view === "chat" ? "on" : ""}" data-id="${c.id}">
          <button class="open" title="${esc(c.title)}">${icon("message-square")}<span>${esc(c.title)}</span></button>
          <button class="icon-btn more" title="대화 삭제" aria-label="대화 삭제">${icon("trash-2")}</button></div>`).join(""));
    }).join("");
    icons();
  }
  $("#history").addEventListener("click", (e) => {
    const g = e.target.closest(".grp");
    if (g) {
      const n = g.dataset.grp;
      state.closedGroups = state.closedGroups.includes(n) ? state.closedGroups.filter((x) => x !== n) : [...state.closedGroups, n];
      store.set(KEY.groups, state.closedGroups); return renderHistory();
    }
    const row = e.target.closest(".conv"); if (!row) return;
    if (e.target.closest(".more")) {
      if (!confirm("이 대화를 삭제할까요?")) return;
      state.convs = state.convs.filter((c) => c.id !== row.dataset.id); saveConvs();
      if (state.currentId === row.dataset.id) newChat(); else renderHistory();
      return;
    }
    openConv(row.dataset.id); app.classList.remove("drawer");
  });

  // ---------------------------------------------------------------- 대화
  function newChat() {
    if (state.pending) return toast("답변이 끝난 뒤에 새 대화를 시작할 수 있어요");
    state.currentId = null; state.view = "chat"; closePanel(); setIntent(null);
    thread.innerHTML = ""; app.classList.add("is-empty"); renderHistory(); input.focus();
  }
  function openConv(id) {
    if (state.pending) return toast("답변이 끝난 뒤에 이동할 수 있어요");
    state.currentId = id; state.view = "chat"; closePanel();
    renderThread(); renderHistory();
  }
  function renderThread(animateLast) {
    const c = current();
    app.classList.toggle("is-empty", !c || !c.messages.length);
    thread.innerHTML = "";
    if (!c) return;
    c.messages.forEach((m, i) => {
      const el = m.role === "user" ? userEl(m) : aiEl(m, i);
      if (animateLast && i === c.messages.length - 1) el.classList.add("fade-in");
      thread.appendChild(el);
    });
    icons(); scroll.scrollTop = scroll.scrollHeight;
  }
  function userEl(m) {
    const wrap = document.createElement("div"); wrap.className = "msg-user-wrap";
    const el = document.createElement("div"); el.className = "msg-user"; el.textContent = m.text;
    wrap.appendChild(el);
    if (m.text.length > 500) {
      el.classList.add("long");
      const more = document.createElement("button"); more.className = "expand"; more.textContent = "전체 보기";
      more.onclick = () => { el.classList.toggle("long"); more.textContent = el.classList.contains("long") ? "전체 보기" : "접기"; };
      wrap.appendChild(more);
    }
    return wrap;
  }

  // ---------------------------------------------------------------- 답변
  function aiEl(m, i) {
    const el = document.createElement("div");
    el.className = "msg-ai"; el.dataset.i = i;
    if (m.pending) {
      el.innerHTML = `<div class="loading"><span class="dots"><i></i><i></i><i></i></span><span>판례와 조문을 찾아 판정하는 중이에요</span><span class="elapsed" data-start="${m.startedAt}">0초</span></div>`;
      return el;
    }
    if (m.run) { el.innerHTML = runHtml(m.run, i); return el; }
    const r = m.result || {};
    if (r.type === "error" || (r.type === "mcq_batch" && r.status_kind === "error" && !r.items?.length)) {
      if (r.code === "setup") { // 색인 없음 등 서버 준비 문제 — 엔진이 알려 준 안내를 그대로 보여 준다
        el.innerHTML = noteHtml("err", "database", "검색 색인이 준비되지 않았어요", r.error || "", true);
        return el;
      }
      const timeout = /시간|timed? ?out|Timeout/i.test(r.error || "");
      el.innerHTML = noteHtml("err", timeout ? "timer-off" : "circle-alert", timeout ? "응답 시간이 초과됐어요" : "답변을 만들지 못했어요",
        `${r.error || ""} — 근거가 없다는 뜻이 아니라 시스템 문제예요.`, true);
      return el;
    }
    if (r.type === "qa") el.innerHTML = qaHtml(r, i);
    if (r.type === "mcq_batch") el.innerHTML = r.items.map((it, k) => mcqHtml(it, i, k, r.items.length)).join("") +
      (r.problems?.length ? noteHtml("warn", "info", "인식하지 못한 문항이 있어요", r.problems.join(" · ")) : "");
    el.insertAdjacentHTML("beforeend", actionsHtml(i));
    return el;
  }
  function noteHtml(kind, ic, title, sub, retry) {
    return `<div class="note ${kind}">${icon(ic)}<div><div>${esc(title)}</div>${sub ? `<div class="nsub">${esc(sub)}</div>` : ""}</div>${retry ? `<span class="act"><button class="link-btn" data-act="retry">다시 시도</button></span>` : ""}</div>`;
  }
  const docOrder = (docs, ids) => { const o = []; for (const id of ids) if (docs[id] && !o.includes(id)) o.push(id); return o; };
  function cites(ids, order, i, k) {
    return [...new Set(ids)].filter((id) => order.includes(id))
      .map((id) => `<button class="cite" data-i="${i}" data-k="${k}" data-doc="${esc(id)}" aria-label="근거 ${order.indexOf(id) + 1} 보기">${order.indexOf(id) + 1}</button>`).join("");
  }
  function refsHtml(docs, order, i, k) {
    if (!order.length) return "";
    return `<h3 class="sec-title">${icon("book-open")}관련 판례 및 조문</h3><ul class="refs">${order.map((id, n) => {
      const d = docs[id];
      const sub = d.kind === "case" ? (d.decided ? `${d.decided} 선고` : "") : prettyVer(d.version);
      return `<li><span class="n">[${n + 1}]</span><button class="ref-btn" data-i="${i}" data-k="${k}" data-doc="${esc(id)}">${esc(docName(d))}</button>
        ${sub ? `<span class="d">— ${esc(sub)}</span>` : ""}${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener" aria-label="원문 보기">${icon("external-link")}</a>` : ""}</li>`;
    }).join("")}</ul>`;
  }
  const secs = (t) => { const v = (t?.total || 0) / 1000; return v ? `${v < 10 ? v.toFixed(1) : Math.round(v)}초` : ""; };

  function qaHtml(r, i) {
    if (r.status_kind === "error") return noteHtml("err", "circle-alert", "답변을 만들지 못했어요", `${r.error || ""} — 근거가 없다는 뜻이 아니라 시스템 문제예요.`, true);
    const docs = r.docs || {}, order = docOrder(docs, r.citations || []);
    let h = "";
    if (r.status_kind === "insufficient") {
      h += noteHtml("warn", "search-x", "검색된 근거로는 판단할 수 없어요", "질문을 더 구체적으로 적거나 관련 조문·사건번호를 함께 적어 보세요.");
      if (r.answer) h += `<div class="prose" style="color:var(--text-2)">${prose(r.answer)}</div>`;
    } else {
      h += `<div class="prose">${prose(r.answer)}${order.length ? `<p style="margin-top:6px">${cites(order, order, i, 0)}</p>` : ""}</div>`;
      if (r.status_kind === "partial") h += noteHtml("warn", "info", "검색된 근거로 확인되는 범위까지만 답했어요", "더 정확한 답이 필요하면 조문 번호나 구체적인 사실관계를 함께 적어 보세요.");
      if (r.status === "invalid_citation") h += order.length
        ? noteHtml("warn", "info", "검색 결과에 없는 인용은 표시하지 않았어요")
        : `<div class="meta">판례·조문 근거를 인용하지 않은 답변이에요</div>`;
    }
    h += refsHtml(docs, order, i, 0);
    h += `<div class="meta">${[order.length ? `근거 ${order.length}개` : "", secs(r.timing_ms), r.model].filter(Boolean).map(esc).join(" · ")}</div>`;
    return h;
  }

  function mcqHtml(it, i, k, total) {
    let h = total > 1 ? `<div class="multi-head">문 ${esc(it.number)}</div>` : "";
    if (it.status_kind === "error") return h + noteHtml("err", "circle-alert", "이 문항을 풀지 못했어요", it.error, true);
    const docs = it.docs || {}, order = docOrder(docs, it.statements.flatMap((s) => s.cited));
    // 1. 최종 정답
    if (it.predicted_label) {
      const single = it.form === "single";
      h += `<h2 class="answer-title">정답 ${esc(it.predicted_label)}<span class="sub ${single ? "long" : ""}">${esc(single ? short(it.predicted_text, 60) : it.predicted_text || "")}</span></h2>`;
    } else {
      h += noteHtml("warn", "search-x", "근거로 판정할 수 있는 지문이 없어 정답을 고르지 않았어요", "유보된 지문의 근거를 직접 확인해 보세요.");
    }
    if (it.status === "tie") h += noteHtml("warn", "equal", "점수가 같은 보기가 있어 앞 번호를 골랐어요", "확실하지 않은 답이에요. 유보된 지문을 직접 확인해 보세요.");
    if (it.status === "inconsistent_judgments") h += noteHtml("warn", "info", "지문 판정과 정확히 맞는 보기가 없어 가장 가까운 보기를 골랐어요");
    // 2. 지문별 O/X 판정
    const sym = { O: ["○", "옳음"], X: ["×", "틀림"], "?": ["–", "유보"] };
    h += `<h3 class="sec-title">${icon("list-checks")}지문별 O/X 판정</h3>`;
    h += `<table class="verdicts"><thead><tr><th style="text-align:center">지문</th><th>판정</th><th>지문 내용</th><th style="text-align:right">근거</th></tr></thead><tbody>` +
      it.statements.map((s) => {
        const [mk, word] = sym[s.verdict] || sym["?"];
        const conf = s.confidence != null ? `<span class="conf">확신도 ${Number(s.confidence).toFixed(2)}</span>` : "";
        return `<tr><td class="k">${esc(s.label)}</td><td class="v"><span class="vd ${s.verdict === "?" ? "q" : s.verdict}"><span class="sym" aria-hidden="true">${mk}</span>${word}</span>${conf}</td>
          <td>${esc(short(s.text, 110))}</td>
          <td class="c">${cites(s.cited, order, i, k) || `<span class="conf">없음</span>`}</td></tr>`;
      }).join("") + `</tbody></table>`;
    // 3. 판단 이유
    h += `<h3 class="sec-title">${icon("scroll-text")}판단 이유</h3><ul class="reasons">` +
      it.statements.map((s) => `<li><span class="lb">${esc(s.label)}.</span><span>${s.reason ? inline(s.reason) : `<span class="kn">판정 이유가 없어요</span>`}${cites(s.cited, order, i, k)}${s.source === "knowledge" ? ` <span class="kn">(근거 없이 모델 지식으로 판단)</span>` : ""}</span></li>`).join("") + `</ul>`;
    // 4. 관련 판례 및 조문
    h += refsHtml(docs, order, i, k);
    const withQ = it.statements.filter((s) => s.quote_verified === true || s.quote_verified === false);
    const okQ = withQ.filter((s) => s.quote_verified === true).length;
    const meta = [order.length ? `근거 ${order.length}개` : "", withQ.length ? `인용 원문 대조 ${okQ}/${withQ.length}` : "",
      it.research_changed?.length ? `재검색으로 바뀐 지문 ${it.research_changed.join("·")}` : "",
      secs(it.timing_ms), it.model, it.preset ? `풀이 ${it.preset}` : ""].filter(Boolean);
    h += `<div class="meta">${meta.map(esc).join(" · ")}</div>`;
    return h;
  }
  function actionsHtml(i) {
    const saved = state.notes.some((n) => n.key === `${state.currentId}:${i}`);
    return `<div class="actions">
      <button class="act-btn" data-act="copy">${icon("copy")}복사</button>
      <button class="act-btn ${saved ? "saved" : ""}" data-act="note">${icon(saved ? "bookmark-check" : "bookmark")}${saved ? "오답 노트에 저장됨" : "오답 노트 저장"}</button>
      <button class="act-btn" data-act="regen">${icon("rotate-ccw")}다시 생성</button></div>`;
  }

  // ---------------------------------------------------------------- 근거 패널
  function panelItem(i, k) {
    const m = current()?.messages[i]; if (m?.run) return m.run.results[k] || null;
    const r = m?.result; if (!r) return null;
    return r.type === "mcq_batch" ? r.items[k] : r;
  }
  function openPanel(i, k, focusId) {
    const it = panelItem(i, k); if (!it) return;
    if (state.panel.i !== i || state.panel.k !== k) state.panel.filter = "all";
    Object.assign(state.panel, { i, k, focus: focusId || null });
    if (focusId && state.panel.filter !== "all" && it.docs[focusId]?.kind !== state.panel.filter) state.panel.filter = "all";
    renderPanel();
    $("#panel").hidden = false;
  }
  function renderPanel() {
    const { i, k, filter, focus } = state.panel;
    const it = panelItem(i, k); if (!it) return;
    const docs = it.docs || {};
    const order = it.type === "qa" ? docOrder(docs, it.citations || []) : docOrder(docs, it.statements.flatMap((s) => s.cited));
    const nCase = order.filter((id) => docs[id].kind === "case").length;
    $("#panelCount").textContent = order.length;
    $("#panelTabs").innerHTML = [["all", `전체 (${order.length})`], ["case", `판례 (${nCase})`], ["statute", `조문 (${order.length - nCase})`]]
      .map(([f, label]) => `<button role="tab" aria-selected="${filter === f}" class="${filter === f ? "on" : ""}" data-f="${f}">${label}</button>`).join("");
    const body = $("#panelBody");
    const shown = order.filter((id) => filter === "all" || docs[id].kind === filter);
    body.innerHTML = shown.map((id) => {
      const n = order.indexOf(id) + 1, d = docs[id];
      const users = it.type === "mcq" ? it.statements.filter((s) => s.cited.includes(id)) : [];
      const quotes = users.map((s) => s.quote).filter(Boolean);
      const verified = users.some((s) => s.quote_verified === true);
      const facts = d.kind === "case"
        ? [["사건번호", d.case_no], ["선고일", d.decided], ["항목", prettyLoc(d.location).replace(/^대법원\s+\d{8}\s+\S+\s*/, "")]]
        : [["조문", `${d.title} ${d.article || ""}`], ["제목", d.article_title], ["시행", prettyVer(d.version)]];
      const long = (d.text || "").length > 520;
      const closed = focus && id !== focus;
      return `<article class="doc ${id === focus ? "on" : ""} ${closed ? "closed" : ""}" data-doc="${esc(id)}" id="doc-${n}">
        <button class="doc-head" data-act="fold" aria-expanded="${!closed}"><span class="n">[${n}]</span><span class="kind">${d.kind === "case" ? "판례" : "조문"}</span><span class="t">${esc(docName(d))}</span>${icon("chevron-down", "chev")}</button>
        <div class="doc-body">
          <dl class="facts">${facts.filter(([, v]) => v).map(([a, b]) => `<dt>${a}</dt><dd>${esc(b)}</dd>`).join("")}</dl>
          <div class="doc-label">${d.kind === "case" ? "검색된 원문" : "조문 내용"}</div>
          <div class="doc-text ${long ? "" : "open"}">${highlight(d.text || "", quotes)}</div>
          ${long ? `<button class="more-text" data-act="expand">전체 보기</button>` : ""}
          <div class="doc-foot"><span>${users.length ? `지문 ${users.map((s) => esc(s.label)).join("·")} 판정에 인용` : "답변에 인용"}${verified ? ` · <span class="verified">인용 문장 원문 대조됨</span>` : ""}</span>
          ${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener">원문 보기 ${icon("external-link")}</a>` : ""}</div>
        </div></article>`;
    }).join("") || `<p class="panel-empty">이 답변에 인용된 근거가 없어요.</p>`;
    icons();
    document.querySelectorAll(".cite.on").forEach((b) => b.classList.remove("on"));
    if (focus) {
      document.querySelectorAll(`.cite[data-i="${i}"][data-k="${k}"]`).forEach((b) => b.classList.toggle("on", b.dataset.doc === focus));
      body.querySelector(".doc.on")?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }
  function closePanel() {
    $("#panel").hidden = true; state.panel.focus = null;
    document.querySelectorAll(".cite.on").forEach((b) => b.classList.remove("on"));
  }
  $("#panelClose").addEventListener("click", closePanel);
  $("#panelTabs").addEventListener("click", (e) => { const b = e.target.closest("[data-f]"); if (!b) return; state.panel.filter = b.dataset.f; state.panel.focus = null; renderPanel(); });
  $("#panelBody").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    if (b.dataset.act === "fold") { const d = b.closest(".doc"); d.classList.toggle("closed"); b.setAttribute("aria-expanded", String(!d.classList.contains("closed"))); }
    if (b.dataset.act === "expand") { const t = b.previousElementSibling; t.classList.toggle("open"); b.textContent = t.classList.contains("open") ? "접기" : "전체 보기"; }
  });

  thread.addEventListener("click", (e) => {
    const conv = e.target.closest("[data-conv]"); if (conv) return openConv(conv.dataset.conv);
    const cite = e.target.closest(".cite, .ref-btn");
    if (cite) return openPanel(+cite.dataset.i, +cite.dataset.k, cite.dataset.doc);
    const act = e.target.closest("[data-act]"); if (!act) return;
    const i = +act.closest(".msg-ai")?.dataset.i;
    const c = current(); if (!c || Number.isNaN(i)) return;
    if (c.messages[i]?.run) return runAction(c, i, act);
    if (act.dataset.act === "retry" || act.dataset.act === "regen") return rerun(i);
    if (act.dataset.act === "copy") navigator.clipboard?.writeText(plain(c.messages[i].result)).then(() => toast("복사했어요"), () => toast("복사하지 못했어요"));
    if (act.dataset.act === "note") toggleNote(c, i);
  });
  function plain(r) {
    if (!r) return "";
    if (r.type === "qa") return r.answer;
    if (r.type === "mcq_batch") return r.items.map((it) => [`정답 ${it.predicted_label || "-"} ${it.form === "single" ? "" : it.predicted_text || ""}`.trim(),
      ...it.statements.map((s) => `${s.label} ${s.verdict === "?" ? "유보" : s.verdict}  ${s.reason || ""}`)].join("\n")).join("\n\n");
    return r.error || "";
  }

  // ---------------------------------------------------------------- 오답 노트 (이 브라우저에 저장)
  function toggleNote(c, i) {
    const key = `${c.id}:${i}`;
    if (state.notes.some((n) => n.key === key)) { state.notes = state.notes.filter((n) => n.key !== key); toast("오답 노트에서 뺐어요"); }
    else {
      const q = c.messages[i - 1]?.text || "", r = c.messages[i].result;
      const ans = r?.type === "mcq_batch" ? r.items.map((it) => `정답 ${it.predicted_label || "-"}`).join(", ") : short(r?.answer, 60);
      state.notes.unshift({ key, convId: c.id, title: short(q, 70), answer: ans, at: Date.now() }); toast("오답 노트에 저장했어요");
    }
    store.set(KEY.notes, state.notes); renderThread(); renderHistory();
  }
  function showNotes() {
    if (state.pending) return toast("답변이 끝난 뒤에 이동할 수 있어요");
    state.view = "notes"; closePanel(); app.classList.remove("is-empty");
    thread.innerHTML = `<div class="notes"><h2>오답 노트</h2>${state.notes.length ? state.notes.map((n) =>
      `<div class="note-item"><button class="t" data-conv="${n.convId}">${esc(n.title || "(질문 없음)")}</button><div class="s">${esc(n.answer || "")} · ${new Date(n.at).toLocaleDateString("ko-KR")}</div></div>`).join("")
      : `<p class="muted">저장한 답변이 없어요. 답변 아래 '오답 노트 저장'으로 모아 둘 수 있어요.</p>`}</div>`;
    icons(); renderHistory();
  }

  // ---------------------------------------------------------------- 팀 소개
  let teamLoaded = false;
  async function openTeam() {
    app.classList.remove("drawer");
    $("#team").hidden = false; $("#teamClose").focus();
    if (teamLoaded) return;
    try {
      const t = await (await fetch("/static/team.json?v=2")).json();
      $("#teamProject").textContent = t.project || "";
      $("#teamPurpose").textContent = t.purpose || "";
      $("#teamMembers").innerHTML = (t.members || []).map((m) => `<div class="member"><img src="${esc(m.image)}" alt="${esc(m.name || "칸트냥이 캐릭터")}">
        ${m.name ? `<div class="nm">${esc(m.name)}</div>` : ""}${m.role ? `<div class="rl">${esc(m.role)}</div>` : ""}
        ${!m.name && !m.role ? `<div class="todo">이름·역할은 team.json 에서 입력</div>` : ""}</div>`).join("");
      teamLoaded = true;
    } catch { $("#teamProject").textContent = "팀 정보를 불러오지 못했어요."; }
  }
  function closeTeam() { $("#team").hidden = true; $("#btnTeam").focus(); }
  $("#btnTeam").addEventListener("click", openTeam);
  $("#teamClose").addEventListener("click", closeTeam);
  $("#team").addEventListener("click", (e) => { if (e.target.id === "team") closeTeam(); });

  // ---------------------------------------------------------------- 보내기
  async function ask(c, i, req) {
    state.pending = true; updateSend();
    c.messages[i] = { role: "ai", pending: true, startedAt: Date.now(), req };
    renderThread(true);
    let result;
    const ctrl = new AbortController(), timer = setTimeout(() => ctrl.abort(), 6 * 60 * 1000);
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req), signal: ctrl.signal });
      result = r.ok ? await r.json() : { type: "error", status_kind: "error", error: `서버 오류 (${r.status})` };
    } catch (err) {
      result = { type: "error", status_kind: "error", error: err.name === "AbortError" ? "시간 초과 (6분)" : "서버에 연결하지 못했어요" };
    } finally { clearTimeout(timer); }
    c.messages[i] = { role: "ai", result, req };
    c.updatedAt = Date.now();
    state.pending = false; saveConvs(); updateSend();
    if (state.currentId === c.id && state.view === "chat") renderThread(true);
    renderHistory();
  }
  function rerun(i) {
    const c = current(); if (!c || state.pending) return;
    const req = c.messages[i]?.req; if (!req) return;
    closePanel();
    ask(c, i, { ...req, model: state.settings.model, mode: state.settings.mode, preset: state.settings.preset });
  }
  function submit() {
    const text = input.value.trim(), att = state.attachment;
    if ((!text && !att) || state.pending || !state.config) return;
    if (att || countQuestions(text) >= 2) return startRun(text, att);
    let c = current();
    if (!c || state.view !== "chat") {
      c = { id: uid(), title: short(text.split("\n")[0], 40), messages: [], updatedAt: Date.now() };
      state.convs.unshift(c); state.currentId = c.id; state.view = "chat";
    }
    c.messages.push({ role: "user", text });
    const req = { text, model: state.settings.model, mode: state.settings.mode, preset: state.settings.preset, intent: state.intent || "auto" };
    input.value = ""; autosize(); setIntent(null);
    c.updatedAt = Date.now(); saveConvs(); renderHistory();
    ask(c, c.messages.length, req);
  }
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); submit(); }
  });
  function autosize() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px"; updateSend(); }
  function updateSend() { sendBtn.disabled = state.pending || (!input.value.trim() && !state.attachment) || !state.config; }
  input.addEventListener("input", autosize);
  $("#file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    if (f.size > 600000) return toast("600KB 이하 파일만 불러올 수 있어요");
    const text = await f.text();
    if (/\.json$/i.test(f.name)) {
      try { const ex = JSON.parse(text); if (!Array.isArray(ex.items)) throw 0; state.attachment = { name: f.name, exam: ex, n: ex.items.length }; }
      catch { return toast("문항 JSON 형식이 아니에요 ({exam, source, items})"); }
    } else state.attachment = { name: f.name, text, n: countQuestions(text) };
    renderAttach(); updateSend(); input.focus();
  });
  function renderAttach() {
    const a = state.attachment, el = $("#attach");
    if (!a) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `${icon("file-text")}<span>${esc(short(a.name, 28))}</span><small>${a.n ? `${a.n}문항` : ""}</small><button type="button" aria-label="첨부 빼기">${icon("x")}</button>`;
    el.querySelector("button").onclick = () => { state.attachment = null; renderAttach(); updateSend(); };
    icons();
  }

  // 추천 버튼: 입력 의도와 안내 문구만 바꾼다 (자동 전송 안 함)
  const SUGGEST = {
    ox: ["ask", "지문 O/X 확인", "확인할 지문을 붙여 넣으세요. 예) 상대방이 대리권 없음을 알았더라도 추인 전이면 철회할 수 있다."],
    exam: ["solve", "기출 문항 풀이", "발문, 지문(ㄱ~ㅁ), 보기(①~⑤)를 그대로 붙여 넣으세요."],
    compare: ["ask", "법리 비교", "비교할 두 법리를 적어 주세요. 예) 해제와 해지의 차이"],
    case: ["ask", "판례 검색", "찾을 판례의 쟁점이나 사건번호를 적어 주세요."],
  };
  $("#suggest").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const [intent, label, ph] = SUGGEST[b.dataset.s]; setIntent(intent, label, ph); input.focus();
  });
  function setIntent(intent, label, ph) {
    state.intent = intent;
    const chip = $("#intentChip");
    input.placeholder = ph || (app.classList.contains("is-empty") ? "민사법 지문이나 기출문항을 입력하세요." : "추가로 궁금한 내용을 질문하세요.");
    if (!intent) { chip.hidden = true; return; }
    chip.hidden = false; chip.innerHTML = `${esc(label)}<button type="button" aria-label="해제">${icon("x")}</button>`;
    chip.querySelector("button").onclick = () => { setIntent(null); input.focus(); };
    icons();
  }
  new MutationObserver(() => { if (!state.intent) setIntent(null); }).observe(app, { attributes: true, attributeFilter: ["class"] });

  // 경과 시간 (실제 경과만, 가짜 진행률 없음)
  setInterval(() => document.querySelectorAll(".elapsed").forEach((el) => { el.textContent = Math.round((Date.now() - +el.dataset.start) / 1000) + "초"; }), 1000);


  // ---------------------------------------------------------------- 시험지 전체 풀이 (문항을 하나씩 요청)
  // 문항마다 결과가 바로 쌓이고, 멈추기·이어 풀기·채점·CSV·오답 노트 담기가 된다. 정답은 채점에만 쓴다.
  const CIRC = ["①", "②", "③", "④", "⑤"];
  const countQuestions = (t) => (String(t || "").match(/(^|\n)\s*(?:【\s*)?문\s*\d+\s*[.】]/g) || []).length;
  const toNum = (a) => CIRC.includes(a) ? CIRC.indexOf(a) + 1 : +a;
  function parseKey(text, qs) { // "3,2" 줄(CSV) / "3:2, 5:5" / 문항 순서대로 "2 5 5 ③ …"
    const key = {}, t = String(text || "");
    const pairs = [...t.matchAll(/(\d+)\s*[,:=\t]\s*([1-5①-⑤])/g)];
    if (pairs.length) for (const [, n, a] of pairs) key[+n] = [toNum(a)];
    else [...t.replace(/[^1-5①-⑤]/g, "")].forEach((a, j) => { if (qs[j]) key[qs[j].number] = [toNum(a)]; });
    return key;
  }
  function grade(run, q) {
    const it = run.results[q.index], acc = run.key?.[q.number];
    if (!it) return "todo";
    if (it.status_kind === "error") return "err";
    if (!acc?.length) return "done";
    return acc.includes(it.predicted) ? "right" : "wrong";
  }
  function runStats(run) {
    const qs = run.questions, g = qs.map((q) => grade(run, q));
    const times = qs.map((q) => run.results[q.index]?.timing_ms?.total || 0).filter(Boolean);
    const avg = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0;
    const done = g.filter((x) => x !== "todo").length;
    return { done, total: qs.length, right: g.filter((x) => x === "right").length, wrong: g.filter((x) => x === "wrong").length,
      graded: g.filter((x) => x === "right" || x === "wrong").length, eta: avg * (qs.length - done) };
  }
  const mins = (ms) => { const s = Math.round(ms / 1000); return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분${s % 60 ? ` ${s % 60}초` : ""}`; };

  function runHtml(run, i) {
    const st = runStats(run), pct = st.total ? Math.round(st.done / st.total * 100) : 0;
    const cur = run.questions.find((q) => q.index === run.cur);
    const status = run.status === "running" ? `${cur ? `문 ${esc(cur.number)} 푸는 중` : "준비 중"}${st.eta ? ` · 남은 시간 약 ${mins(st.eta)}` : ""}`
      : run.status === "done" ? "풀이 완료" : run.error ? esc(run.error) : "멈춤 — 이어 풀 수 있어요";
    let h = `<div class="run">
      <div class="run-head"><div class="run-title">${icon("file-text")}<b>${esc(run.title)}</b></div>
        <div class="run-btns">${run.status === "running" ? `<button class="act-btn" data-act="run-stop">${icon("square")}멈추기</button>`
          : run.status !== "done" ? `<button class="act-btn gold" data-act="run-resume">${icon("play")}이어 풀기</button>` : ""}
          ${st.done ? `<button class="act-btn" data-act="run-csv">${icon("download")}CSV</button>` : ""}</div></div>
      <div class="run-bar"><span style="width:${pct}%"></span></div>
      <div class="run-status"><span>${st.done}/${st.total}문항</span><span class="${run.status === "running" ? "live" : run.error ? "bad" : ""}">${status}</span>${run.status === "running" ? `<span class="elapsed" data-start="${run.startedAt}">0초</span>` : ""}</div>`;
    if (st.graded) h += `<div class="run-score"><b>${st.right}</b><span>/ ${st.graded} 정답</span><em>${Math.round(st.right / st.graded * 100)}%</em>
        ${st.wrong ? `<button class="link-btn" data-act="run-filter">${run.filter === "wrong" ? "전체 보기" : `오답 ${st.wrong}개만 보기`}</button>
        <button class="link-btn" data-act="run-notes">오답 노트에 담기</button>` : ""}</div>`;
    if (!run.hasKey) h += `<form class="run-key"><input name="key" placeholder="정답을 넣으면 채점해요 — 예) 2 5 5 3 … 또는 3:2, 5:5" aria-label="정답"><button type="button" class="act-btn" data-act="run-key">채점</button></form>`;
    const qs = run.questions.filter((q) => run.filter !== "wrong" || grade(run, q) === "wrong");
    const LBL = { right: "맞음", wrong: "틀림", err: "오류", done: "풀이 완료", todo: "대기", now: "푸는 중" };
    h += `<div class="run-grid">${qs.map((q) => {
      const g = run.status === "running" && q.index === run.cur ? "now" : grade(run, q), it = run.results[q.index];
      return `<button class="rq ${g} ${run.open === q.index ? "on" : ""}" data-act="run-open" data-idx="${q.index}" title="문 ${esc(q.number)} · ${LBL[g]}">
        <span class="no">${esc(q.number)}</span><span class="pa">${it?.predicted_label || (g === "now" ? "…" : g === "err" ? "!" : "·")}</span></button>`;
    }).join("")}</div>`;
    if (run.problems?.length) h += noteHtml("warn", "info", "인식하지 못한 부분이 있어요", run.problems.slice(0, 5).join(" · "));
    const q = run.questions.find((x) => x.index === run.open), it = q && run.results[q.index];
    if (q) {
      const acc = run.key?.[q.number], g = grade(run, q);
      h += `<div class="run-detail"><div class="rd-head"><b>문 ${esc(q.number)}</b>${q.subject ? `<span class="tag">${esc(q.subject)}</span>` : ""}
        ${acc?.length ? `<span class="tag ${g}">정답 ${acc.map((a) => CIRC[a - 1]).join("·")}${g === "right" ? " · 맞음" : g === "wrong" ? " · 틀림" : ""}</span>` : ""}</div>
        <p class="q-stem">${esc(q.stem)}</p>
        ${it ? mcqHtml(it, i, q.index, 1) : `<p class="q-stem">${run.status === "running" && q.index === run.cur ? "푸는 중이에요…" : "아직 풀지 않은 문항이에요."}</p>`}</div>`;
    }
    return h + `</div>`;
  }
  function paintRun(c, i) {
    if (state.currentId !== c.id || state.view !== "chat") return;
    const el = thread.querySelector(`.msg-ai[data-i="${i}"]`); if (!el) return renderThread();
    el.innerHTML = runHtml(c.messages[i].run, i); icons();
  }
  async function post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
    return r.json();
  }
  async function parseExam(src) {
    const p = await post("/api/exam/parse", src);
    if (p.status_kind !== "ok") throw new Error(p.error || "시험지를 읽지 못했어요");
    return p;
  }
  async function startRun(text, att) {
    let c = current();
    if (!c || state.view !== "chat") {
      c = { id: uid(), title: att?.name || short(text.split("\n")[0], 40), messages: [], updatedAt: Date.now() };
      state.convs.unshift(c); state.currentId = c.id; state.view = "chat";
    }
    c.messages.push({ role: "user", text: att ? `📎 ${att.name}${text ? `\n\n${text}` : ""}` : text });
    const src = att?.exam ? { exam: att.exam, title: att.exam.exam } : { text: att?.text || text, title: att?.name };
    const i = c.messages.length;
    c.messages.push({ role: "ai", pending: true, startedAt: Date.now() });
    input.value = ""; autosize(); setIntent(null); state.attachment = null; renderAttach();
    saveConvs(); renderHistory(); renderThread(true);
    try {
      const p = await parseExam(src);
      const key = {}; p.questions.forEach((q) => { if (q.accepted?.length) key[q.number] = q.accepted; });
      const hasKey = Object.keys(key).length > 0;
      c.messages[i] = { role: "ai", run: { title: p.title, batchId: p.batch_id, questions: p.questions, problems: p.problems, results: {},
        key, hasKey, status: "running", src: JSON.stringify(src).length < 400000 ? src : null, open: null, filter: "all",
        settings: { model: state.settings.model, mode: state.settings.mode, preset: state.settings.preset } } };
      if (hasKey) toast("시험지에 정답이 있어 자동으로 채점해요");
    } catch (err) {
      c.messages[i] = { role: "ai", result: { type: "error", status_kind: "error", error: err.message } };
      saveConvs(); return renderThread();
    }
    renderThread(); runLoop(c, i);
  }
  async function runLoop(c, i) {
    const run = c.messages[i].run;
    run.status = "running"; run.error = null; run.startedAt = Date.now();
    state.pending = true; updateSend();
    const solve = () => post("/api/exam/solve", { batch_id: run.batchId, index: run.cur, ...run.settings });
    for (const q of run.questions) {
      if (run.status !== "running") break;
      if (run.results[q.index]) continue;
      run.cur = q.index; paintRun(c, i);
      let r;
      try {
        r = await solve();
        if (r.code === "expired") {
          if (!run.src) throw new Error("서버가 다시 켜져 시험지를 다시 첨부해야 해요");
          run.batchId = (await parseExam(run.src)).batch_id; r = await solve();
        }
      } catch (err) { r = { status_kind: "error", error: err.message === "Failed to fetch" ? "서버에 연결하지 못했어요" : err.message }; }
      if (r.status_kind !== "ok") { run.status = "stopped"; run.error = r.code === "setup" ? "검색 색인이 준비되지 않았어요" : r.error; break; }
      run.results[q.index] = r.item;
      if (run.open == null) run.open = q.index;
      c.updatedAt = Date.now(); saveConvs(); paintRun(c, i);
    }
    run.cur = null;
    if (run.status === "running") { run.status = "done"; run.src = null; toast("시험지 풀이를 마쳤어요"); }
    state.pending = false; updateSend(); saveConvs(); paintRun(c, i); renderHistory();
  }
  function runAction(c, i, act) {
    const run = c.messages[i].run, a = act.dataset.act;
    if (a === "run-stop") { run.status = "stopped"; toast("지금 푸는 문항까지만 풀고 멈춰요"); return paintRun(c, i); }
    if (a === "run-resume") return state.pending ? toast("다른 답변이 끝난 뒤에 이어 풀 수 있어요") : runLoop(c, i);
    if (a === "run-open") { const k = +act.dataset.idx; run.open = run.open === k ? null : k; saveConvs(); return paintRun(c, i); }
    if (a === "run-filter") { run.filter = run.filter === "wrong" ? "all" : "wrong"; saveConvs(); return paintRun(c, i); }
    if (a === "retry" && run.open != null) {
      if (state.pending) return toast("풀이가 끝난 뒤에 다시 풀 수 있어요");
      delete run.results[run.open]; run.status = "stopped"; return runLoop(c, i);
    }
    if (a === "run-key") {
      const key = parseKey(act.closest("form").querySelector("input").value, run.questions);
      if (!Object.keys(key).length) return toast("정답을 읽지 못했어요");
      run.key = key; run.hasKey = true; saveConvs(); toast(`${Object.keys(key).length}문항 정답으로 채점했어요`); return paintRun(c, i);
    }
    if (a === "run-csv") {
      const rows = [["문항", "과목", "예측", "정답", "채점", "상태", "시간(초)"]].concat(run.questions.map((q) => {
        const it = run.results[q.index], g = grade(run, q);
        return [q.number, q.subject || "", it?.predicted || "", (run.key?.[q.number] || []).join("|"), g === "right" ? "O" : g === "wrong" ? "X" : "",
          it?.status || "미풀이", it?.timing_ms?.total ? (it.timing_ms.total / 1000).toFixed(1) : ""];
      }));
      const csv = "﻿" + rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" })), link = document.createElement("a");
      link.href = url; link.download = `${short(run.title, 40).replace(/[\\/:*?"<>|]/g, "_")}_풀이.csv`; link.click();
      return setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    if (a === "run-notes") {
      let n = 0;
      for (const q of run.questions) {
        const key = `${c.id}:${i}:${q.index}`;
        if (grade(run, q) !== "wrong" || state.notes.some((x) => x.key === key)) continue;
        state.notes.unshift({ key, convId: c.id, title: `문 ${q.number}. ${short(q.stem, 60)}`,
          answer: `예측 ${run.results[q.index].predicted_label || "-"} · 정답 ${run.key[q.number].map((x) => CIRC[x - 1]).join("·")}`, at: Date.now() }); n++;
      }
      store.set(KEY.notes, state.notes); renderHistory(); toast(n ? `오답 ${n}문항을 노트에 담았어요` : "이미 모두 담겨 있어요");
    }
  }
  thread.addEventListener("submit", (e) => { const f = e.target.closest(".run-key"); if (!f) return; e.preventDefault(); f.querySelector("[data-act]").click(); });

  // ---------------------------------------------------------------- 시작
  icons(); renderHistory(); newChat(); loadConfig().then(updateSend);
  // 주소로 대화·근거 바로 열기: #c=<대화 id>&doc=<근거 번호>
  const hp = new URLSearchParams(location.hash.slice(1));
  if (hp.has("team")) openTeam();
  if (hp.get("c") && state.convs.some((c) => c.id === hp.get("c"))) {
    openConv(hp.get("c"));
    const n = +hp.get("doc");
    if (n) { const b = thread.querySelectorAll(".cite")[n - 1]; if (b) openPanel(+b.dataset.i, +b.dataset.k, b.dataset.doc); }
  }
})();
