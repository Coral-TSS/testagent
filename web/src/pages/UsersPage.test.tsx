import { fireEvent, screen, waitFor } from "@testing-library/react";

import * as auth from "../app/AuthGate";
import { mockFetch, renderPage } from "../test/utils";
import { UsersPage } from "./UsersPage";

const ADMIN = { id: "u1", username: "boss", display_name: "Boss", role: "admin" as const, must_change_password: false, csrf_token: "c" };
const ROWS = [
  { id: "u1", username: "boss", display_name: "Boss", role: "admin", is_active: true, must_change_password: false, locked: false, has_password: true, last_login_at: null, created_at: "2026-11-03T00:00:00Z" },
  { id: "u2", username: "alice", display_name: "Alice", role: "member", is_active: true, must_change_password: true, locked: true, has_password: true, last_login_at: null, created_at: "2026-11-03T00:00:00Z" },
];

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("UsersPage", () => {
  it("lists accounts with their state and unlocks", async () => {
    vi.spyOn(auth, "useAuth").mockReturnValue({ me: ADMIN, signOut: async () => {}, refresh: () => {} });
    const calls = mockFetch({
      "GET /users": () => ({ body: ROWS }),
      "PATCH /users/u2": () => ({ body: { ...ROWS[1], locked: false } }),
    });
    renderPage(<UsersPage />);
    expect(await screen.findByRole("heading", { name: "用户 (2)" })).toBeTruthy();
    expect(screen.getByText("已锁定")).toBeTruthy();
    expect(screen.getByText("必须修改密码")).toBeTruthy();
    expect(screen.getByText("我")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "解锁" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ unlock: true }));
  });

  it("tells members it is admin-only", () => {
    vi.spyOn(auth, "useAuth").mockReturnValue({ me: { ...ADMIN, role: "member" }, signOut: async () => {}, refresh: () => {} });
    mockFetch({});
    renderPage(<UsersPage />);
    expect(screen.getByText("只有管理员可以管理账号。")).toBeTruthy();
  });
});
