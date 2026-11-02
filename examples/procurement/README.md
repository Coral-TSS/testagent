# Procurement approval demo (the example SUT for TestAgent)

## What it is

A tiny "procurement approval" business app built to be the **system under test** for TestAgent: in TestAgent you model it, write requirements, generate cases and scripts, run them and file defects, and watch how the agent actually works. It is not part of the TestAgent platform, and the platform does not depend on it. Data lives in a local SQLite file (`runtime/sample.db`); no real money is involved.

Business objects and rules:

| Object | Description |
|---|---|
| Supplier | Name (required, unique), contact. 3 by default: East China Office Supplies Co., Galaxy Tech Equipment Co., Swift Logistics Services Co. |
| PurchaseOrder | Purpose, supplier (`supplier_id`, foreign key → Supplier), amount (`amount_minor`, **in cents**, CNY 50,000.00 = 5000000), currency, whether approval is required, state, created time |
| Payment | Purchase order (`order_id`, foreign key → PurchaseOrder), callback id (`callback_id`), amount, paid time |

- **PurchaseOrder belongs to Supplier** (N:1); **Payment pays PurchaseOrder** (N:1, at most one valid payment per purchase order).
- Currency CNY and amount **≥ 50,000.00**: approval required, state "pending approval" (pending); below that amount: **auto-approved** (approved).
- Unknown amount or a currency other than CNY: cannot be decided (unknown); it can be neither approved nor paid.
- Only purchase orders "pending approval" can be approved: approve → approved, reject → rejected; approving in any other state returns 409.
- Only "approved" purchase orders can be paid; after payment the state becomes "paid". Re-submitting the same callback id returns the original record (idempotent); paying again with a different callback id returns 409.

## How to start it

- **Docker Compose** (recommended): `docker compose up -d` starts it as the `demo` service next to the platform; it is reachable at http://localhost:8766 from your machine and at `http://demo:8766` from the platform (the seeded environment `local` points there).
- **Local launcher**: `uv run testagent` (or `ops\start.cmd` on Windows) starts it automatically, because the seeded environment `local` carries a start command.
- **By hand**, from the repository root:

```bash
uv run uvicorn examples.procurement.api:create_app --factory --host 127.0.0.1 --port 8766
```

| URL | What |
|---|---|
| http://localhost:8766/ | UI: purchase orders (create, filter, detail, approve/reject, record payment, payments), suppliers (list, create), "Reset demo data" |
| http://localhost:8766/docs | API docs (try requests directly) |
| http://localhost:8766/openapi.json | OpenAPI; use this address in TestAgent "API registry → Import from OpenAPI" |

UI elements have stable `data-testid` (e.g. `order-amount`, `order-submit`, `order-row`, `order-state`, `approve`, `reject`, `pay-callback`, `pay-submit`, `payment-row`, `supplier-name`, `supplier-submit`, `reset-demo`), which makes UI/Playwright cases easy to write.

API (all under `/sample`):

| API | Purpose |
|---|---|
| `GET /sample/suppliers` | List suppliers |
| `POST /sample/suppliers` | Create a supplier (409 on a duplicate name) |
| `GET /sample/suppliers/{supplier_id}` | Get a supplier |
| `GET /sample/orders` | List purchase orders (filter by `state`, `supplier_id`) |
| `POST /sample/orders` | Create a purchase order (decides whether approval is required) |
| `GET /sample/orders/{order_id}` | Get a purchase order |
| `POST /sample/orders/{order_id}/decision` | Approve a purchase order (`{"approved": true/false}`) |
| `POST /sample/orders/{order_id}/payments` | Record a payment (`{"callback_id": "..."}`) |
| `GET /sample/orders/{order_id}/payments` | List payments |
| `POST /sample/reset` | Reset demo data (clears purchase orders, payments and suppliers, restores the 3 default suppliers) |

Repeatable tests: call `POST /sample/reset` before testing, or set the environment variable `PROCUREMENT_RESET_ON_START=1` to reset on every start.

## Seeded bugs

To check whether TestAgent can find problems, the app contains a few **deliberately seeded bugs**, controlled by the environment variable `PROCUREMENT_DEMO_BUGS` : on by default; set to `0` and the app follows the rules above exactly (TestAgent's own automated tests run that way). What they are is written at the very end of this file — **don't look yet**; compare once the agent has finished.

## Suggested walkthrough (from scratch in TestAgent)

1. **SUT**: open "SUT → Procurement approval (demo) (procurement)" and look at the step bar and the "Getting started" checklist. The environment `local` should show "Reachable"; otherwise click "Start".
2. **Import the API**: SUT menu "API registry → Import from OpenAPI", choose environment `local` (it reads `/openapi.json` of the running demo). After the import there are 10 APIs with descriptions for names and fields.
3. **Model**: on the "Model" page create entities (Supplier, PurchaseOrder, Payment) and actions (Create purchase order, Approve purchase order, Record payment, …); use the API field names as field names (`amount_minor`, `state`, `supplier_id`). You can also write requirements first and let the AI completion propose model changes, then accept them one by one under "Model suggestions"; the "Links" tab shows link suggestions generated from foreign-key fields (PurchaseOrder belongs to Supplier, Payment pays PurchaseOrder). When done, open "Model review", check each item and tick "Reviewed".
4. **Version & requirements**: create a version (e.g. v1) and write requirements such as "Purchase orders of 50,000 or more must be approved", "A purchase order can only be paid once", "A rejected purchase order shows as rejected in the list". Assign an owner → "AI structure" → confirm → freeze.
5. **Test strategy**: version page "Test strategy & tasks" → "AI generate strategy" → edit and confirm.
6. **Cases & scripts**: version page "Test cases & coverage" → "AI generate cases". By default an automation script is generated and self-checked for every case in the background; scripts live in the local test repo (the SUT overview page shows the absolute path). After review, set the cases "Ready".
7. **Tasks & execution**: create a task, choose environment `local`, add cases → set ready → run, and follow progress on the run page.
8. **Defects & reports**: on a failed execution → "Create defect" or "AI analyse cause"; read the task report, version report and people stats. Finally compare with the answers below and see how many seeded bugs the agent found.

---

## Seeded bugs (answers — spoilers, don't read first)

<details>
<summary>Click to reveal (active when PROCUREMENT_DEMO_BUGS=1)</summary>

1. **Wrong approval threshold boundary**: a CNY purchase order of exactly 50,000.00 (5000000 cents) is judged "no approval needed" and auto-approved; the rule is "≥ 50,000.00 needs approval". (`service.py` uses `>` instead of `>=`.)
2. **Small purchase orders can be paid twice**: an auto-approved purchase order (amount < 50,000.00) can be paid again with a different callback id after payment, leaving two payment records; large orders that needed approval are not affected.
3. **Wrong state shown in the UI**: after a purchase order is rejected, the UI (list and detail) still shows "Pending approval", while the API returns the correct `state` value `rejected`. Only a UI case can find it.

</details>
