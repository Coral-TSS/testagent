"use strict";
const $ = (id) => document.getElementById(id);
const LABELS = { pending: "Pending approval", approved: "Approved", paid: "Paid", unknown: "Undecided" };
if (!window.DEMO_BUGS) LABELS.rejected = "Rejected"; // seeded bug 3 (README): mapping missing
const stateLabel = (s) => LABELS[s] || LABELS.pending;
let orders = [], suppliers = [], selected = null, busy = false;

const yuan = (minor) => (minor / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money = (o) => (o.amount_minor === null ? "Amount unknown" : `${o.currency} ${yuan(o.amount_minor)}`);
function notice(text, error = false) { $("notice").textContent = text; $("notice").classList.toggle("error", error); }
function el(tag, attrs = {}, text) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}
async function api(path, method = "GET", body) {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(`HTTP ${r.status} · ${typeof d === "string" ? d : "Invalid input: check the amount, currency and supplier"}`);
  }
  return data;
}
async function act(fn) {
  if (busy) return;
  busy = true; document.querySelectorAll("button,input,select").forEach((x) => (x.disabled = true));
  try { await fn(); } catch (e) { notice(e.message, true); }
  finally { busy = false; document.querySelectorAll("button,input,select").forEach((x) => (x.disabled = false)); renderDetail(); }
}
function parseAmount(text) {
  const t = text.trim().replace(/,/g, "");
  if (!t) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(t)) throw new Error("Invalid amount: enter a non-negative number with at most two decimals");
  const [i, f = ""] = t.split(".");
  return Number(i) * 100 + Number((f + "00").slice(0, 2));
}

async function loadSuppliers() {
  suppliers = await api("/sample/suppliers");
  const sel = $("supplier");
  sel.replaceChildren(el("option", { value: "" }, "(none)"), ...suppliers.map((s) => el("option", { value: s.id }, s.name)));
  if (suppliers.length) sel.value = suppliers[0].id;
  $("s-count").textContent = String(suppliers.length);
  $("suppliers").replaceChildren(...suppliers.map((s) => {
    const tr = el("tr", { "data-testid": "supplier-row", "data-supplier-id": s.id });
    tr.append(el("td", {}, s.name), el("td", {}, s.contact || "-"), el("td", {}, String(orders.filter((o) => o.supplier_id === s.id).length)));
    return tr;
  }));
}
async function loadOrders() {
  const f = $("state-filter").value;
  orders = await api("/sample/orders" + (f ? `?state=${f}` : ""));
  $("count").textContent = String(orders.length);
  const list = $("orders");
  if (!orders.length) { list.replaceChildren(el("p", { class: "empty", "data-testid": "order-list-empty" }, "No purchase orders yet; create the first one above.")); }
  else list.replaceChildren(...orders.map((o) => {
    const b = el("button", { type: "button", class: `order${o.id === selected ? " selected" : ""}`, "data-testid": "order-row", "data-order-id": o.id });
    b.append(el("span", { class: `badge s-${o.state}`, "data-testid": "order-state" }, stateLabel(o.state)),
      el("strong", {}, o.title || "(no purpose)"), el("span", { class: "muted" }, `${o.supplier_name || "No supplier"} · ${money(o)}`));
    b.onclick = () => { selected = o.id; render(); };
    return b;
  }));
}
async function renderDetail() {
  const o = orders.find((x) => x.id === selected);
  $("empty-detail").hidden = !!o; $("order-detail").hidden = !o;
  if (!o) return;
  $("d-state").textContent = stateLabel(o.state); $("d-state").className = `badge s-${o.state}`;
  $("d-title").textContent = o.title || "(no purpose)";
  $("d-supplier").textContent = o.supplier_name || "Not set";
  $("d-amount").textContent = money(o);
  $("d-required").textContent = o.approval_required === null ? "Undecided" : o.approval_required ? "Approval required" : "Not required (auto-approved)";
  $("d-id").textContent = o.id;
  if (!busy) { const p = o.state === "pending"; $("approve").disabled = !p; $("reject").disabled = !p; }
  const pays = await api(`/sample/orders/${o.id}/payments`);
  $("pay-count").textContent = String(pays.length);
  $("payments").replaceChildren(...pays.map((p) => {
    const tr = el("tr", { "data-testid": "payment-row" });
    tr.append(el("td", {}, p.callback_id), el("td", {}, p.amount === null ? "-" : `¥${yuan(p.amount)}`), el("td", {}, new Date(p.paid_at).toLocaleString("en-US")));
    return tr;
  }));
}
async function render() { await loadOrders(); await renderDetail(); }
async function refreshAll() { await loadOrders(); await loadSuppliers(); await renderDetail(); }

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $("page-orders").hidden = t.dataset.tab !== "orders"; $("page-suppliers").hidden = t.dataset.tab !== "suppliers";
  }));
  $("state-filter").onchange = () => act(render);
  $("order-form").onsubmit = (e) => { e.preventDefault(); act(async () => {
    const body = { title: $("title").value.trim() || null, supplier_id: $("supplier").value || null, amount_minor: parseAmount($("amount").value), currency: $("currency").value };
    const o = await api("/sample/orders", "POST", body);
    selected = o.id; $("state-filter").value = "";
    notice(`Created purchase order: ${money(o)}, state ${stateLabel(o.state)}`);
    await refreshAll();
  }); };
  const decide = (approved) => act(async () => {
    await api(`/sample/orders/${selected}/decision`, "POST", { approved });
    notice(approved ? "Approved" : "Rejected"); await render();
  });
  $("approve").onclick = () => decide(true);
  $("reject").onclick = () => decide(false);
  $("pay").onclick = () => act(async () => {
    const p = await api(`/sample/orders/${selected}/payments`, "POST", { callback_id: $("callback").value });
    notice(`Payment recorded ¥${yuan(p.amount)} (callback id ${p.callback_id})`); await render();
  });
  $("supplier-form").onsubmit = (e) => { e.preventDefault(); act(async () => {
    const s = await api("/sample/suppliers", "POST", { name: $("s-name").value, contact: $("s-contact").value.trim() || null });
    $("s-name").value = ""; $("s-contact").value = "";
    notice(`Created supplier: ${s.name}`); await loadSuppliers();
  }); };
  $("reset").onclick = () => { if (confirm("Clear all purchase orders, payments and suppliers and restore the 3 default suppliers?")) act(async () => {
    await api("/sample/reset", "POST"); selected = null; notice("Demo data reset"); await refreshAll();
  }); };
  act(async () => { await refreshAll(); notice("Ready"); });
});
