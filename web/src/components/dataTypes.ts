import type { DataType, IoLocation } from "../api/types";

/** Field / parameter types (type is required, visible and editable) */
export const DATA_TYPE_LABEL: Record<DataType, string> = {
  string: "Text",
  integer: "Integer",
  number: "Number",
  decimal: "Decimal",
  money: "Amount",
  boolean: "Yes/No",
  date: "Date",
  datetime: "Date-time",
  enum: "Enum",
  reference: "Reference",
  object: "object",
  array: "List",
};

export const DATA_TYPE_OPTIONS = Object.entries(DATA_TYPE_LABEL).map(([value, label]) => ({
  value,
  label: `${label} (${value})`,
}));

export const LOCATION_LABEL: Record<IoLocation, string> = {
  path: "Path parameters",
  query: "Query parameters",
  header: "Headers",
  body: "Request body",
  form: "Form",
  response: "Response",
  ui: "Page",
};

export function typeText(t: string | null | undefined): string {
  return (t && DATA_TYPE_LABEL[t as DataType]) || t || "?";
}
