import { TOKEN_KEY } from "../app/token";
import { mockFetch } from "../test/utils";
import { AUTH_EVENT, ApiError, api, describeError } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("api client", () => {
  it("sends the bearer token, JSON body and query params", async () => {
    sessionStorage.setItem(TOKEN_KEY, "tok");
    const calls = mockFetch({ "POST /suts": () => ({ status: 201, body: { id: "1" } }) });
    const out = await api<{ id: string }>("/suts", { method: "POST", body: { code: "A" }, params: { x: 1, empty: "" } });
    expect(out.id).toBe("1");
    expect(calls[0].headers.Authorization).toBe("Bearer tok");
    expect(calls[0].body).toEqual({ code: "A" });
    expect((fetch as unknown as { mock: { calls: string[][] } }).mock.calls[0][0]).toBe("/api/v1/suts?x=1");
  });

  it("returns undefined for 204", async () => {
    mockFetch({ "DELETE /suts/1": () => ({ status: 204 }) });
    await expect(api("/suts/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("maps the error envelope to ApiError", async () => {
    mockFetch({
      "POST /suts": () => ({
        status: 422,
        body: { code: "VALIDATION", message: "Bad parameter", field_errors: [{ field: "code", msg: "Required" }] },
      }),
    });
    const err = (await api("/suts", { method: "POST", body: {} }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("VALIDATION");
    expect(describeError(err)).toBe("Bad parameter (code: Required)");
  });

  it("dispatches the auth event on 401", async () => {
    mockFetch({ "GET /suts": () => ({ status: 401, body: { code: "UNAUTHORIZED", message: "Unauthorized" } }) });
    const listener = vi.fn();
    window.addEventListener(AUTH_EVENT, listener);
    await expect(api("/suts")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener(AUTH_EVENT, listener);
  });
});
