import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";

import { mockFetch } from "../test/utils";
import { AuthGate, useAuth } from "./AuthGate";
import { getCsrfToken, setCsrfToken } from "./session";

const ME = { id: "u1", username: "alice", display_name: "Alice", role: "member", must_change_password: false, csrf_token: "csrf-1" };

function Who() {
  const { me } = useAuth();
  return <div>inside as {me?.username}</div>;
}

const gate = () =>
  render(
    <AntApp>
      <AuthGate>
        <Who />
      </AuthGate>
    </AntApp>,
  );

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  window.history.replaceState(null, "", "/");
});

describe("AuthGate", () => {
  it("shows the app when a session exists", async () => {
    mockFetch({ "GET /auth/me": () => ({ body: ME }) });
    gate();
    expect(await screen.findByText("inside as alice")).toBeTruthy();
    expect(getCsrfToken()).toBe("csrf-1");
  });

  it("signs in with user name and password", async () => {
    const calls = mockFetch({
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED", message: "需要登录" } }),
      "GET /auth/status": () => ({ body: { has_users: true } }),
      "POST /auth/login": () => ({ body: ME }),
    });
    gate();
    fireEvent.change(await screen.findByLabelText("用户名"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "secret-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("inside as alice")).toBeTruthy();
    expect(calls.find((c) => c.path === "/auth/login")?.body).toEqual({ username: "alice", password: "secret-pass-1" });
  });

  it("shows the error of a failed sign-in", async () => {
    mockFetch({
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED", message: "需要登录" } }),
      "GET /auth/status": () => ({ body: { has_users: true } }),
      "POST /auth/login": () => ({ status: 401, body: { code: "LOGIN_FAILED", message: "用户名或密码错误" } }),
    });
    gate();
    fireEvent.change(await screen.findByLabelText("用户名"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "nope-nope-1" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText("用户名或密码错误")).toBeTruthy();
  });

  it("explains how to create the first admin", async () => {
    mockFetch({
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED" } }),
      "GET /auth/status": () => ({ body: { has_users: false } }),
    });
    gate();
    expect(await screen.findByText("还没有账号")).toBeTruthy();
  });

  it("redeems the launcher ticket from the fragment", async () => {
    window.history.replaceState(null, "", "/suts#ticket=tk1");
    const calls = mockFetch({ "POST /auth/ticket": () => ({ body: ME }) });
    gate();
    expect(await screen.findByText("inside as alice")).toBeTruthy();
    expect(calls[0].body).toEqual({ ticket: "tk1" });
    expect(window.location.hash).toBe("");
  });

  it("asks for a new password first when required", async () => {
    mockFetch({
      "GET /auth/me": () => ({ body: { ...ME, must_change_password: true } }),
      "POST /auth/password": () => ({ body: ME }),
    });
    gate();
    expect(await screen.findByText("请设置新密码")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "initial-pass-1" } });
    fireEvent.change(screen.getByLabelText("新密码（至少 10 个字符）"), { target: { value: "new-pass-123" } });
    fireEvent.change(screen.getByLabelText("再次输入新密码"), { target: { value: "new-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新密码" }));
    await waitFor(() => expect(screen.getByText("inside as alice")).toBeTruthy());
  });
});
