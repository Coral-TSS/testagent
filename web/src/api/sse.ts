import { getToken } from "../app/token";
import { ApiError } from "./client";

export interface SseEvent {
  event: string;
  data: unknown;
}

/** Parses complete SSE blocks out of `buffer`; returns the events and the unparsed rest. */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) continue;
    const text = data.join("\n");
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      /* plain text payload */
    }
    events.push({ event, data: parsed });
  }
  return { events, rest };
}

/** Server-sent events over fetch (EventSource cannot send the Authorization header). */
export async function streamEvents(path: string, onEvent: (e: SseEvent) => void, signal: AbortSignal): Promise<void> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`/api/v1${path}`, { headers, signal });
  if (!resp.ok || !resp.body) throw new ApiError(resp.status, {});
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSse(buffer);
    buffer = rest;
    events.forEach(onEvent);
  }
  const { events } = parseSse(buffer + "\n\n");
  events.forEach(onEvent);
}
