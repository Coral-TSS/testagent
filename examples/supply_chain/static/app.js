const STATUS = {
  draft: "草稿",
  submitted: "待审批",
  approved: "已批准",
  rejected: "已驳回",
  converted: "已转换",
  pending_approval: "待审批",
  issued: "已下达",
  partial_received: "部分收货",
  received: "已收货",
  closed: "已关闭",
  cancelled: "已取消",
  qualified: "合格",
  potential: "潜在",
  frozen: "冻结",
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function fill(select, rows, label) {
  select.innerHTML = rows.map((row) => `<option value="${row.id}">${label(row)}</option>`).join("");
}

async function refresh() {
  const [materials, buyers, suppliers, reqs, orders, stock] = await Promise.all([
    api("/sample/materials"),
    api("/sample/buyers"),
    api("/sample/suppliers"),
    api("/sample/requisitions"),
    api("/sample/orders"),
    api("/sample/inventory"),
  ]);
  fill(document.querySelector("#material"), materials, (row) => `${row.code} ${row.name}`);
  fill(document.querySelector("#buyer"), buyers, (row) => `${row.code} ${row.name}`);
  fill(document.querySelector("#supplier"), suppliers, (row) => `${row.code} ${row.name}`);
  document.querySelector("#reqs").innerHTML = reqs
    .map((row) => `<li>${row.code} ${row.materialCode} × ${row.qty} <span class="badge">${STATUS[row.status] || row.status}</span></li>`)
    .join("");
  document.querySelector("#orders").innerHTML = orders
    .map((row) => `<li>${row.code} ${row.amount} ${row.currency} <span class="badge">${STATUS[row.status] || row.status}</span></li>`)
    .join("");
  document.querySelector("#stock").innerHTML = stock
    .map((row) => `<li>${row.warehouseCode} ${row.materialCode} 在库 ${row.onHandQty}</li>`)
    .join("");
}

document.querySelector("#req-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    materialId: document.querySelector("#material").value,
    qty: Number(document.querySelector("#qty").value),
    buyerId: document.querySelector("#buyer").value,
    supplierId: document.querySelector("#supplier").value,
  };
  const created = await api("/sample/requisitions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  document.querySelector("#badge").textContent = STATUS[created.status] || created.status;
  await refresh();
});

document.querySelector("#reset").addEventListener("click", async () => {
  await api("/sample/reset", { method: "POST" });
  document.querySelector("#badge").textContent = "";
  await refresh();
});

refresh();
