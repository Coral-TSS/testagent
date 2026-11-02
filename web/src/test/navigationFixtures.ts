import type { ModelReview, SutProgress } from "../api/types";

export const progress: SutProgress = {
  sut: { id: "s1", code: "PROC", name: "Procurement system" },
  version: { id: "v1", name: "v1", status: "frozen" },
  versions: [{ id: "v1", name: "v1", status: "frozen" }],
  steps: [
    { key: "sut", title: "SUT", status: "done", summary: "1 environment(s)", path: "/suts/s1", action: null },
    { key: "model", title: "Model", status: "done", summary: "3 entities", path: "/suts/s1/model", action: null },
    { key: "requirements", title: "Requirements", status: "done", summary: "2 requirements · frozen", path: "/versions/v1", action: null },
    { key: "strategy", title: "Strategy", status: "doing", summary: "Strategy draft", path: "/versions/v1?tab=strategy", action: { label: "Create/confirm test strategy", path: "/versions/v1?tab=strategy" } },
    { key: "tasks", title: "Tasks", status: "todo", summary: "0 task(s)", path: "/versions/v1?tab=strategy", action: { label: "New task", path: "/versions/v1?tab=strategy" } },
    { key: "cases", title: "Cases", status: "todo", summary: "0 case(s)", path: "/versions/v1?tab=cases", action: { label: "Generate cases", path: "/versions/v1?tab=strategy" } },
    { key: "runs", title: "Runs", status: "todo", summary: "Not run", path: "/executions?sut_id=s1&version_id=v1", action: { label: "Run task", path: "/versions/v1?tab=strategy" } },
    { key: "results", title: "Results", status: "todo", summary: "None", path: "/defects?sut_id=s1&version_id=v1", action: null },
  ],
  next: { key: "strategy", title: "Strategy", label: "Create/confirm test strategy", path: "/versions/v1?tab=strategy" },
  repo_path: "D:/TestAgent/runtime/repos/PROC",
} as unknown as SutProgress;

const cov = { requirements: [], cases: [] };
export const review: ModelReview = {
  sut: { id: "s1", code: "PROC", name: "Procurement system" },
  generated_at: "2026-11-02T02:00:00Z",
  summary: { entities: 2, fields: 2, links: 1, actions: 1, total: 4, reviewed: 1, stale: 1, uncovered: 2, pending_suggestions: 3 },
  pending_by_kind: {},
  entities: [
    {
      id: "n1",
      name: "PurchaseOrder",
      description: "Purchase request",
      digest: "a",
      uncovered: false,
      coverage: { requirements: [{ id: "r1", code: "REQ-001", title: "Create purchase order", version_id: "v1", version_name: "v1" }], cases: [{ id: "c1", code: "TC-001", title: "Amount approval" }] },
      relations: ["PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)"],
      fields: [
        { id: "f1", name: "amount", display_name: "Amount", data_type: "money", required: true, uncovered: false, coverage: cov, description: null, storage_name: null, enum_values: null, ref_node_name: null },
        { id: "f2", name: "status", display_name: "Status", data_type: "enum", required: false, uncovered: true, coverage: cov, description: null, storage_name: null, enum_values: ["draft", "done"], ref_node_name: null },
      ],
      mark: { reviewed: true, stale: false, note: "ok", reviewed_by: "me", reviewed_at: "2026-11-02T02:00:00Z" },
    },
    { id: "n2", name: "Supplier", description: null, digest: "b", uncovered: true, coverage: cov, relations: [], fields: [], mark: { reviewed: true, stale: true, note: null, reviewed_by: "me", reviewed_at: "2026-11-01T02:00:00Z" } },
  ],
  links: [
    {
      id: "l1",
      forward: "PurchaseOrder belongs to Supplier",
      reverse: "Supplier supplies PurchaseOrder",
      text: "",
      cardinality: "N:1",
      fk_field: "PurchaseOrder.supplier_id",
      via_name: null,
      required: true,
      api_names: [],
      description: null,
      digest: "c",
      uncovered: true,
      coverage: cov,
      mark: null,
    },
  ],
  actions: [
    {
      id: "a1",
      name: "Submit purchase order",
      description: "Submit for approval",
      inputs: ["amount (amount, required)"],
      outputs: ["id"],
      formats: [],
      preconditions: ["PurchaseOrder.status = draft"],
      effects: ["PurchaseOrder.status → submitted"],
      apis: [{ id: "api1", method: "POST", path: "/orders/{id}/submit" }],
      digest: "d",
      uncovered: false,
      coverage: cov,
      mark: null,
    },
  ],
} as unknown as ModelReview;
