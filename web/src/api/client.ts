import { getToken } from "../app/token";

export interface FieldError {
  field: string;
  msg?: string;
}

export class ApiError extends Error {
  code: string;
  status: number;
  fieldErrors: FieldError[];
  related: string[];

  constructor(status: number, body: Partial<{ code: string; message: string; field_errors: FieldError[]; related: string[] }>) {
    super(body.message || `Request failed (${status})`);
    this.status = status;
    this.code = body.code || "UNKNOWN";
    this.fieldErrors = body.field_errors || [];
    this.related = body.related || [];
  }
}

export const AUTH_EVENT = "testagent:auth-required";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export async function api<T = unknown>(
  path: string,
  options: { method?: Method; body?: unknown; params?: Record<string, string | number | boolean | undefined | null> } = {},
): Promise<T> {
  const query = Object.entries(options.params || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const resp = await fetch(`/api/v1${path}${query ? `?${query}` : ""}`, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!resp.ok) {
    const err = new ApiError(resp.status, data || {});
    if (resp.status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
    throw err;
  }
  return data as T;
}

/** Authenticated binary fetch (artifacts, exports). */
export async function fetchBlob(path: string, params: Record<string, string> = {}): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const query = new URLSearchParams(params).toString();
  const resp = await fetch(`/api/v1${path}${query ? `?${query}` : ""}`, { headers });
  if (!resp.ok) {
    const text = await resp.text();
    if (resp.status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
    throw new ApiError(resp.status, text ? JSON.parse(text) : {});
  }
  return resp.blob();
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Authenticated file download (export endpoints). */
export async function download(path: string, params: Record<string, string>, filename: string): Promise<void> {
  saveBlob(await fetchBlob(path, params), filename);
}

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const fields = err.fieldErrors.map((f) => `${f.field}${f.msg ? `: ${f.msg}` : ""}`);
    const extra = [...fields, ...err.related].filter(Boolean);
    return extra.length ? `${err.message} (${extra.join("; ")})` : err.message;
  }
  return err instanceof Error ? err.message : String(err);
}
