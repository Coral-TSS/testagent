import { TOKEN_KEY, captureToken } from "./token";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, v),
  };
}

describe("captureToken", () => {
  it("moves #t= into sessionStorage and clears the fragment", () => {
    const storage = memoryStorage();
    const history = { replaceState: vi.fn() };
    const token = captureToken({ hash: "#t=abc%2B1", pathname: "/suts/1", search: "?x=1" }, storage, history);
    expect(token).toBe("abc+1");
    expect(storage.getItem(TOKEN_KEY)).toBe("abc+1");
    expect(history.replaceState).toHaveBeenCalledWith(null, "", "/suts/1?x=1");
  });

  it("keeps an existing token when there is no fragment", () => {
    const storage = memoryStorage();
    storage.setItem(TOKEN_KEY, "old");
    const history = { replaceState: vi.fn() };
    expect(captureToken({ hash: "", pathname: "/", search: "" }, storage, history)).toBe("old");
    expect(history.replaceState).not.toHaveBeenCalled();
  });

  it("ignores unrelated fragments", () => {
    const storage = memoryStorage();
    const history = { replaceState: vi.fn() };
    expect(captureToken({ hash: "#section", pathname: "/", search: "" }, storage, history)).toBeNull();
  });
});
