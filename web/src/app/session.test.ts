import { getCsrfToken, setCsrfToken, takeTicket } from "./session";

describe("session helpers", () => {
  it("takes the launcher ticket from the fragment and removes it", () => {
    const history = { replaceState: vi.fn() };
    expect(takeTicket({ hash: "#ticket=abc%2B1", pathname: "/suts/1", search: "?x=1" }, history)).toBe("abc+1");
    expect(history.replaceState).toHaveBeenCalledWith(null, "", "/suts/1?x=1");
  });

  it("ignores other fragments", () => {
    const history = { replaceState: vi.fn() };
    expect(takeTicket({ hash: "#t=old-token", pathname: "/", search: "" }, history)).toBeNull();
    expect(history.replaceState).not.toHaveBeenCalled();
  });

  it("keeps the CSRF token in memory", () => {
    setCsrfToken("c1");
    expect(getCsrfToken()).toBe("c1");
    setCsrfToken(null);
    expect(getCsrfToken()).toBeNull();
  });
});
