import type { DataType, IoLocation } from "../api/types";

/** Field / parameter types (type is required, visible and editable) */
export const DATA_TYPE_LABEL: Record<DataType, string> = {
  string: "文本",
  integer: "整数",
  number: "数字",
  decimal: "小数",
  money: "金额",
  boolean: "是/否",
  date: "日期",
  datetime: "日期时间",
  enum: "枚举",
  reference: "引用",
  object: "对象",
  array: "列表",
};

export const DATA_TYPE_OPTIONS = Object.entries(DATA_TYPE_LABEL).map(([value, label]) => ({
  value,
  label: `${label} (${value})`,
}));

export const LOCATION_LABEL: Record<IoLocation, string> = {
  path: "路径参数",
  query: "查询参数",
  header: "请求头",
  body: "请求体",
  form: "表单",
  response: "响应",
  ui: "页面",
};

export function typeText(t: string | null | undefined): string {
  return (t && DATA_TYPE_LABEL[t as DataType]) || t || "?";
}
