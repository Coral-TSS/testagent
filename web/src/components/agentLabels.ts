/** Readable labels for agent tools shown in traces. */
export const TOOL_LABEL: Record<string, string> = {
  list_nodes: "View model node",
  get_node: "View node detail",
  search_nodes: "Search model nodes",
  get_graph_neighbors: "View neighbour nodes",
  list_fields: "View entity fields",
  list_links: "View links",
  list_apis: "List APIs",
  get_api_schema: "View API schema",
  list_requirements: "List requirements",
  get_requirement: "View requirement",
  get_requirement_people: "View requirement owners",
  list_cases: "List cases",
  get_case: "View case",
  get_coverage: "View coverage",
  search_memory: "Search memories",
  write_test_file: "Write test file",
  run_pytest: "Run self-check (pytest)",
  browser_goto: "Browser · open page",
  browser_click: "Browser · click",
  browser_fill: "Browser · fill",
  browser_select: "Browser · select",
  browser_press: "Browser · press key",
  browser_read: "Browser · read",
  browser_assert: "Browser · assert",
  api_request: "API · send request",
  api_assert: "API · assert",
  submit_result: "Submission result",
};

export function toolLabel(name?: string): string {
  if (!name) return "";
  return TOOL_LABEL[name] ? `${TOOL_LABEL[name]} (${name})` : name;
}

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** Replaces known UUIDs in a text with their readable labels: “PurchaseOrder” instead of b1d6…. */
export function withLabels(text: string, labels?: Record<string, string>): string {
  if (!labels) return text;
  return text.replace(UUID, (id) => {
    const label = labels[id.toLowerCase()];
    return label ? `${label} [${id.slice(0, 8)}]` : id;
  });
}
