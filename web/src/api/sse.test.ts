import { parseSse, streamEvents } from "./sse";

afterEach(() => vi.unstubAllGlobals());

describe("sse", () => {
  it("parses complete blocks and keeps the rest", () => {
    const { events, rest } = parseSse('event: case\ndata: {"index": 1}\n\n: keepalive\n\nevent: run\ndata: {"sta');
    expect(events).toEqual([{ event: "case", data: { index: 1 } }]);
    expect(rest).toBe('event: run\ndata: {"sta');
  });

  it("streams events with the auth header", async () => {
    const body = 'event: snapshot\ndata: {"status": "running"}\n\nevent: case\ndata: {"index": 1}\n\nevent: end\ndata: {"status": "passed"}\n\n';
    const fetchMock = vi.fn(async () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    vi.stubGlobal("fetch", fetchMock);
    const seen: string[] = [];
    await streamEvents("/runs/r1/events", (e) => seen.push(e.event), new AbortController().signal);
    expect(seen).toEqual(["snapshot", "case", "end"]);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe("/api/v1/runs/r1/events");
  });
});
