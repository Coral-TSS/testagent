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
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED", message: "Sign-in required" } }),
      "GET /auth/status": () => ({ body: { has_users: true } }),
      "POST /auth/login": () => ({ body: ME }),
    });
    gate();
    fireEvent.change(await screen.findByLabelText("User name"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("inside as alice")).toBeTruthy();
    expect(calls.find((c) => c.path === "/auth/login")?.body).toEqual({ username: "alice", password: "secret-pass-1" });
  });

  it("shows the error of a failed sign-in", async () => {
    mockFetch({
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED", message: "Sign-in required" } }),
      "GET /auth/status": () => ({ body: { has_users: true } }),
      "POST /auth/login": () => ({ status: 401, body: { code: "LOGIN_FAILED", message: "Wrong user name or password" } }),
    });
    gate();
    fireEvent.change(await screen.findByLabelText("User name"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope-nope-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Wrong user name or password")).toBeTruthy();
  });

  it("explains how to create the first admin", async () => {
    mockFetch({
      "GET /auth/me": () => ({ status: 401, body: { code: "AUTH_REQUIRED" } }),
      "GET /auth/status": () => ({ body: { has_users: false } }),
    });
    gate();
    expect(await screen.findByText("No account yet")).toBeTruthy();
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
    expect(await screen.findByText("Choose a new password")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "initial-pass-1" } });
    fireEvent.change(screen.getByLabelText("New password (at least 10 characters)"), { target: { value: "new-pass-123" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "new-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new password" }));
    await waitFor(() => expect(screen.getByText("inside as alice")).toBeTruthy());
  });
});
