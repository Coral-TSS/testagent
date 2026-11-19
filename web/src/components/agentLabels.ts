/** Readable labels for agent tools shown in traces. */
export const TOOL_LABEL: Record<string, string> = {
  list_nodes: "查看模型节点",
  get_node: "查看节点详情",
  search_nodes: "搜索模型节点",
  get_graph_neighbors: "查看相邻节点",
  list_fields: "查看实体字段",
  list_links: "查看关系",
  list_apis: "列出 API",
  get_api_schema: "查看 API 模式",
  list_requirements: "列出需求",
  get_requirement: "查看需求",
  get_requirement_people: "查看需求负责人",
  list_cases: "列出用例",
  get_case: "查看用例",
  get_coverage: "查看覆盖",
  search_memory: "搜索记忆",
  write_test_file: "写测试文件",
  run_pytest: "运行自检（pytest）",
  browser_goto: "浏览器 · 打开页面",
  browser_click: "浏览器 · 点击",
  browser_fill: "浏览器 · 填写",
  browser_select: "浏览器 · 选择",
  browser_press: "浏览器 · 按键",
  browser_read: "浏览器 · 读取",
  browser_assert: "浏览器 · 断言",
  api_request: "API · 发送请求",
  api_assert: "API · 断言",
  submit_result: "提交结果",
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
