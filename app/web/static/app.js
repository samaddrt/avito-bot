// SoloMoney Avito OS — Mini App frontend
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const INIT_DATA = tg?.initData || "";
let currentFilter = "";

// ---------- Тема (светлая/тёмная) ----------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("themeBtn");
  if (btn) btn.textContent = theme === "dark" ? "☀️" : "🌙";  // показываем, на что переключим
}
function initTheme() {
  // Приоритет: явный выбор пользователя → тема Telegram → системная → светлая.
  let theme = localStorage.getItem("theme");
  if (!theme) {
    if (tg?.colorScheme) theme = tg.colorScheme;
    else if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) theme = "dark";
    else theme = "light";
  }
  applyTheme(theme);
}
function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  localStorage.setItem("theme", next);
  applyTheme(next);
}
initTheme();

const VERDICT_RU = {
  BUY_NOW: "БРАТЬ", NEGOTIATE: "ТОРГ", WATCH: "НАБЛЮДАТЬ",
  SKIP: "ПРОПУСК", HIGH_RISK: "РИСК",
};
const STATUS_RU = {
  new: "Новая", contacted: "Написал", negotiating: "Торг",
  bought: "Куплено", listed: "Выставлено", sold: "Продано",
  watching: "Наблюдаю", skipped: "Пропущено",
};

function money(v) {
  if (v == null) return "—";
  return v.toLocaleString("ru-RU") + " ₽";
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (INIT_DATA) headers["X-Init-Data"] = INIT_DATA;
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 2200);
}

// ---------- Stats ----------
async function loadStats() {
  try {
    const s = await api("/api/stats");
    const roi = s.roi_pct != null ? s.roi_pct + "%" : "—";
    const avg = s.avg_days_to_sell != null ? s.avg_days_to_sell + " дн" : "—";
    document.getElementById("stats").innerHTML = `
      <div class="stat"><div class="val">${money(s.realized_profit)}</div><div class="lbl">Чистый заработок</div></div>
      <div class="stat"><div class="val">${roi}</div><div class="lbl">ROI</div></div>
      <div class="stat"><div class="val">${s.sold_count}</div><div class="lbl">Продано</div></div>
      <div class="stat"><div class="val">${money(s.month_profit)}</div><div class="lbl">За месяц</div></div>
      <div class="stat"><div class="val">${money(s.capital_tied)}</div><div class="lbl">Заморожено</div></div>
      <div class="stat"><div class="val">${money(s.potential_profit)}</div><div class="lbl">Потенциал</div></div>`;
  } catch (e) { /* dev */ }
}

const LIQ_RU = { high: "ходовой", medium: "средний", low: "медленный" };

window.findOpportunities = async () => {
  const budget = parseInt(document.getElementById("budgetInput").value);
  if (!budget || budget < 1000) { toast("Укажи бюджет"); return; }
  const box = document.getElementById("opportunities");
  box.innerHTML = `<div class="empty">Считаю…</div>`;
  try {
    const opps = await api(`/api/opportunities?budget=${budget}`);
    if (!opps.length) { box.innerHTML = `<div class="empty">На этот бюджет в каталоге ничего нет</div>`; return; }
    box.innerHTML = opps.map((o, i) => `
      <div class="opp">
        <div class="opp-top"><b>${i + 1}. ${escapeHtml(o.model_name)}</b>${o.real_data ? " ⭐️" : ""}
          <span class="badge b-BUY_NOW">${LIQ_RU[o.liquidity]}</span></div>
        <div class="opp-meta">
          Купить ~${money(o.est_buy_price)} → продать ~${money(o.quick_sale_price)}<br>
          Чистыми <b>${money(o.net_profit)}</b>/шт · маржа ${o.margin_pct.toFixed(0)}% ·
          в бюджет ${o.units} шт → потенциал <b>${money(o.total_potential)}</b>
        </div>
      </div>`).join("");
  } catch (e) { box.innerHTML = `<div class="empty">Ошибка: ${e.message}</div>`; }
};

async function loadProducts() {
  try {
    const list = await api("/api/products");
    const box = document.getElementById("productList");
    if (!box) return;
    box.innerHTML = list.length
      ? list.map(p => `<div class="search-row">
          <span>${{high:"🟢",medium:"🟡",low:"🔴"}[p.liquidity] || "⚪️"} ${escapeHtml(p.model_name)}
            <small style="color:var(--muted)">${money(p.market_price)}→${money(p.quick_sale_price)}</small></span>
          <button class="ghost" onclick="delProduct('${encodeURIComponent(p.model_name)}')">✕</button>
        </div>`).join("")
      : `<div class="empty">Каталог пуст</div>`;
  } catch (e) { /* dev */ }
}
window.addProduct = async () => {
  const body = {
    category: document.getElementById("pCategory").value.trim(),
    model_name: document.getElementById("pModel").value.trim(),
    market_price: parseInt(document.getElementById("pMarket").value),
    quick_sale_price: parseInt(document.getElementById("pQuick").value),
    liquidity: document.getElementById("pLiq").value,
  };
  if (!body.category || !body.model_name || !body.market_price || !body.quick_sale_price) {
    toast("Заполни все поля"); return;
  }
  try {
    await api("/api/products", { method: "POST", body: JSON.stringify(body) });
    ["pCategory","pModel","pMarket","pQuick"].forEach(id => document.getElementById(id).value = "");
    loadProducts(); toast("Добавлено в каталог");
  } catch (e) { toast("Ошибка: " + e.message); }
};
window.delProduct = async (name) => {
  try { await api(`/api/products/${name}`, { method: "DELETE" }); loadProducts(); toast("Удалено"); }
  catch (e) { toast("Ошибка: " + e.message); }
};

async function loadSearches() {
  try {
    const list = await api("/api/searches");
    const box = document.getElementById("searchList");
    if (!box) return;
    box.innerHTML = list.length
      ? list.map(s => `<div class="search-row">
          <span>${s.enabled ? "✅" : "⏹"} ${escapeHtml(s.name)}</span>
          <button class="ghost" onclick="toggleSearch(${s.index})">${s.enabled ? "Выкл" : "Вкл"}</button>
        </div>`).join("")
      : `<div class="empty">Поисков нет</div>`;
  } catch (e) { /* dev */ }
}
window.toggleSearch = async (i) => {
  try { await api(`/api/searches/${i}/toggle`, { method: "POST" }); loadSearches(); }
  catch (e) { toast("Ошибка: " + e.message); }
};
window.addSearch = async () => {
  const url = document.getElementById("searchUrl").value.trim();
  if (!url.startsWith("http")) { toast("Вставь URL поиска Avito"); return; }
  try {
    await api("/api/searches", { method: "POST", body: JSON.stringify({ url }) });
    document.getElementById("searchUrl").value = "";
    loadSearches(); toast("Поиск добавлен");
  } catch (e) { toast("Ошибка: " + e.message); }
};
window.runCalibration = async () => {
  try {
    const sug = await api("/api/calibration");
    if (!sug.length) { toast("Пока нечего калибровать"); return; }
    const txt = sug.map(s => `${s.model_name}: ${s.current_market || "—"} → ${s.suggested_market}₽`).join("\n");
    if (confirm("Обновить цены по твоим продажам?\n\n" + txt)) {
      const r = await api("/api/calibration/apply", { method: "POST" });
      toast("Обновлено моделей: " + r.updated);
    }
  } catch (e) { toast("Ошибка: " + e.message); }
};

async function loadWatcher() {
  try {
    const w = await api("/api/watcher");
    document.getElementById("watcherStatus").textContent = w.status;
  } catch (e) {
    document.getElementById("watcherStatus").textContent = "недоступно";
  }
}

// ---------- Deals ----------
async function loadDeals() {
  const list = document.getElementById("dealsList");
  list.innerHTML = `<div class="empty">Загрузка…</div>`;
  try {
    const q = currentFilter ? `?status=${currentFilter}` : "";
    const deals = await api(`/api/deals${q}`);
    if (!deals.length) { list.innerHTML = `<div class="empty">Сделок нет</div>`; return; }
    list.innerHTML = deals.map(dealCard).join("");
    document.querySelectorAll(".deal").forEach(el =>
      el.addEventListener("click", () => openDeal(el.dataset.id)));
  } catch (e) {
    list.innerHTML = `<div class="empty">Ошибка: ${e.message}</div>`;
  }
}

function dealCard(d) {
  const v = d.verdict || "SKIP";
  return `
    <div class="deal v-${v}" data-id="${d.id}">
      <div class="deal-top">
        <div class="deal-title">${escapeHtml(d.title)}</div>
        <span class="badge b-${v}">${VERDICT_RU[v] || v}</span>
      </div>
      <div class="deal-meta">
        <span>Профит <b>${money(d.expected_profit)}</b></span>
        <span>Маржа <b>${d.margin_pct != null ? d.margin_pct.toFixed(0) + "%" : "—"}</b></span>
        <span>Риск <b>${d.risk_score ?? "—"}</b></span>
        <span class="hot">🔥 ${d.hotness ?? "—"}</span>
        <span>${STATUS_RU[d.status] || d.status}</span>
      </div>
    </div>`;
}

async function openDeal(id) {
  try {
    const d = await api(`/api/deals/${id}`);
    const a = d.analysis || {};
    const nego = a.negotiation_messages || {};
    const modalBody = document.getElementById("modalBody");
    modalBody.innerHTML = `
      <h2>${escapeHtml(d.title)}</h2>
      <p style="color:var(--muted);font-size:13px;margin-bottom:12px">
        <span class="badge b-${d.verdict}">${VERDICT_RU[d.verdict] || d.verdict}</span>
        &nbsp;🔥 ${d.hotness ?? "—"} · ${STATUS_RU[d.status] || d.status}</p>
      <div class="row"><span>Цена продавца</span><span>${money(d.seller_price)}</span></div>
      <div class="row"><span>Рыночная</span><span>${money(d.market_price)}</span></div>
      <div class="row"><span>Быстрая продажа</span><span>${money(d.quick_sale_price)}</span></div>
      <div class="row"><span>Цель покупки</span><span>${money(d.target_buy_price)}</span></div>
      <div class="row"><span>Расходы (прогноз)</span><span>~${money(d.expected_costs)}</span></div>
      <div class="row"><span>Чистая прибыль</span><span><b>${money(d.expected_profit)}</b> <small style="color:var(--muted)">(вал. ${money(d.gross_profit)})</small></span></div>
      <div class="row"><span>Маржа</span><span>${d.margin_pct != null ? d.margin_pct.toFixed(0)+"%" : "—"}</span></div>
      <div class="row"><span>Риск</span><span>${d.risk_score ?? "—"}/100</span></div>
      ${d.actual_profit != null ? `<div class="row"><span>Факт. прибыль</span><span><b>${money(d.actual_profit)}</b> · ROI ${d.roi_pct ?? "—"}%</span></div>` : ""}
      ${a.why_good ? `<div class="section"><h4>Почему</h4><p>${escapeHtml(a.why_good)}</p></div>` : ""}
      ${listSection("Что проверить", a.what_to_check)}
      ${listSection("Чек-лист встречи", a.meeting_checklist)}
      ${listSection("Вопросы продавцу", a.questions_to_seller)}
      ${a.scam_flags?.length ? `<div class="section"><h4 class="flag">Флаги риска</h4><ul>${a.scam_flags.map(f=>`<li class="flag">${escapeHtml(f)}</li>`).join("")}</ul></div>` : ""}
      ${negoSection(nego)}
      ${d.url ? `<div class="section"><a class="ghost" href="${d.url}" target="_blank">🔗 Открыть на Avito</a></div>` : ""}
      <div class="action-row">
        ${statusBtn(id, "contacted", "📌 Написал")}
        ${statusBtn(id, "negotiating", "💬 Торг")}
        ${statusBtn(id, "bought", "✅ Купил")}
        ${statusBtn(id, "listed", "🏷 Выставил")}
        ${statusBtn(id, "sold", "💰 Продал")}
        ${statusBtn(id, "watching", "👁 Наблюдать")}
        ${statusBtn(id, "skipped", "❌ Пропустить")}
      </div>
      <div class="action-row">
        <button class="primary" onclick="genResale(${id})">📦 Черновик перепродажи</button>
      </div>
      <div id="resaleSlot"></div>`;
    document.getElementById("modal").classList.remove("hidden");
    if (a.resale_draft) renderResale(a.resale_draft);
  } catch (e) { toast("Ошибка: " + e.message); }
}

function listSection(title, items) {
  if (!items || !items.length) return "";
  return `<div class="section"><h4>${title}</h4><ul>${items.map(i=>`<li>${escapeHtml(i)}</li>`).join("")}</ul></div>`;
}

function negoSection(nego) {
  const tones = [["polite","🙂 Вежливо"],["firm","😐 Жёстко"],["quick_meet","🚗 Сегодня"]];
  const blocks = tones.filter(([k]) => nego[k]).map(([k,label]) =>
    `<div class="section"><h4>${label}</h4>
      <div class="copybox">${escapeHtml(nego[k])}
        <button class="ghost" onclick="copyText(this)">Копировать</button></div></div>`).join("");
  return blocks ? `<div class="section"><h4>Сообщения продавцу</h4></div>${blocks}` : "";
}

function statusBtn(id, status, label) {
  return `<button class="ghost" onclick="setStatus(${id},'${status}')">${label}</button>`;
}

window.setStatus = async (id, status) => {
  const body = { status };
  // При покупке/продаже спрашиваем фактические цифры — для честного ROI.
  if (status === "bought") {
    const buy = prompt("Цена покупки, ₽:");
    if (buy) body.actual_buy_price = parseInt(buy);
    const costs = prompt("Доп. расходы (дорога/ремонт), ₽:", "0");
    if (costs) body.extra_costs = parseInt(costs);
  }
  if (status === "sold") {
    const sell = prompt("Цена продажи, ₽:");
    if (sell) body.actual_sell_price = parseInt(sell);
  }
  try {
    await api(`/api/deals/${id}/status`, { method: "POST", body: JSON.stringify(body) });
    toast("Статус: " + (STATUS_RU[status] || status));
    closeModal(); loadDeals(); loadStats();
  } catch (e) { toast("Ошибка: " + e.message); }
};

window.genResale = async (id) => {
  toast("Готовлю черновик…");
  try {
    const r = await api(`/api/deals/${id}/resale`, { method: "POST" });
    renderResale(r.resale_draft);
  } catch (e) { toast("Ошибка: " + e.message); }
};

function renderResale(draft) {
  const slot = document.getElementById("resaleSlot");
  if (!slot || !draft) return;
  slot.innerHTML = `
    <div class="section"><h4>Черновик объявления</h4>
      <div class="copybox"><b>${escapeHtml(draft.title)}</b><br>${escapeHtml(draft.description)}
        <button class="ghost" onclick="copyText(this)">Копировать</button></div>
      <div class="row"><span>Цена</span><span>${money(draft.price)}</span></div>
      <div class="row"><span>Минимум</span><span>${money(draft.min_price)}</span></div>
      ${draft.price_drop_strategy ? `<p style="font-size:13px;color:var(--muted);margin-top:8px">${escapeHtml(draft.price_drop_strategy)}</p>` : ""}
    </div>`;
}

window.copyText = (btn) => {
  const text = btn.parentElement.childNodes[0].textContent.trim() + "\n" +
    Array.from(btn.parentElement.childNodes).filter(n=>n.nodeType===3).map(n=>n.textContent).join("");
  navigator.clipboard.writeText(btn.parentElement.innerText.replace("Копировать","").trim());
  toast("Скопировано");
};

function closeModal() { document.getElementById("modal").classList.add("hidden"); }

function escapeHtml(s) {
  return (s||"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

// ---------- Manual analyze ----------
document.getElementById("analyzeBtn").addEventListener("click", async () => {
  const text = document.getElementById("analyzeInput").value.trim();
  if (text.length < 15) { toast("Слишком короткий текст"); return; }
  toast("Анализирую…");
  try {
    const d = await api("/api/analyze", { method: "POST", body: JSON.stringify({ text }) });
    document.getElementById("analyzeInput").value = "";
    loadDeals(); loadStats();
    openDeal(d.id);
  } catch (e) { toast("Ошибка: " + e.message); }
});

// ---------- Controls ----------
document.getElementById("themeBtn").addEventListener("click", toggleTheme);
document.getElementById("refreshBtn").addEventListener("click", () => { loadStats(); loadWatcher(); loadDeals(); loadSearches(); loadProducts(); });
document.getElementById("modalClose").addEventListener("click", closeModal);
document.getElementById("modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.getElementById("pauseBtn").addEventListener("click", async () => { await api("/api/watcher/pause",{method:"POST"}); loadWatcher(); toast("Пауза"); });
document.getElementById("resumeBtn").addEventListener("click", async () => { await api("/api/watcher/resume",{method:"POST"}); loadWatcher(); toast("Старт"); });
document.getElementById("backupBtn").addEventListener("click", async () => {
  try { const r = await api("/api/backup",{method:"POST"}); toast("Бэкап: " + r.backup); }
  catch(e){ toast("Ошибка: " + e.message); }
});
document.getElementById("exportBtn").addEventListener("click", () => {
  const headers = INIT_DATA ? `?_=${Date.now()}` : "";
  window.open("/api/export.csv" + headers, "_blank");
});
document.querySelectorAll(".chip").forEach(chip =>
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    currentFilter = chip.dataset.status;
    loadDeals();
  }));

// ---------- Init ----------
loadStats(); loadWatcher(); loadDeals(); loadSearches(); loadProducts();
