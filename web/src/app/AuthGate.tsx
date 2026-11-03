import { Alert, Button, Card, Form, Input, Result, Spin, Typography } from "antd";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { AUTH_EVENT, PASSWORD_EVENT, api, describeError } from "../api/client";
import { setCsrfToken, takeTicket, type Me } from "./session";

interface AuthState {
  me: Me | null;
  signOut: () => Promise<void>;
  refresh: (me: Me) => void;
}

const AuthContext = createContext<AuthState>({ me: null, signOut: async () => {}, refresh: () => {} });

/** The signed-in user (null outside the gate, e.g. in page tests). */
export function useAuth(): AuthState {
  return useContext(AuthContext);
}

type Phase = "loading" | "signed-out" | "signed-in";

/** Shows the sign-in page until there is a session; forces a new password when one is required. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const accept = useCallback((next: Me) => {
    setCsrfToken(next.csrf_token);
    setMe(next);
    setPhase("signed-in");
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const ticket = takeTicket();
      if (ticket) {
        try {
          const next = await api<Me>("/auth/ticket", { method: "POST", body: { ticket } });
          if (alive) accept(next);
          return;
        } catch (err) {
          if (alive) setNotice(describeError(err));
        }
      }
      try {
        const next = await api<Me>("/auth/me");
        if (alive) accept(next);
      } catch {
        if (alive) setPhase("signed-out");
      }
    })();
    return () => {
      alive = false;
    };
  }, [accept]);

  useEffect(() => {
    const onAuth = () => {
      setCsrfToken(null);
      setMe(null);
      setNotice("Your session has ended. Please sign in again.");
      setPhase("signed-out");
    };
    const onPassword = () => setMe((m) => (m ? { ...m, must_change_password: true } : m));
    window.addEventListener(AUTH_EVENT, onAuth);
    window.addEventListener(PASSWORD_EVENT, onPassword);
    return () => {
      window.removeEventListener(AUTH_EVENT, onAuth);
      window.removeEventListener(PASSWORD_EVENT, onPassword);
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken(null);
      setMe(null);
      setNotice(null);
      setPhase("signed-out");
    }
  }, []);

  if (phase === "loading") {
    return (
      <div style={{ display: "flex", justifyContent: "center", paddingTop: 120 }}>
        <Spin />
      </div>
    );
  }
  if (phase === "signed-out" || !me) return <LoginPage notice={notice} onSignedIn={accept} />;
  if (me.must_change_password) {
    return (
      <Centered>
        <Card style={{ width: 400 }}>
          <Typography.Title level={4} style={{ marginTop: 0 }}>
            Choose a new password
          </Typography.Title>
          <Typography.Paragraph type="secondary">
            Signed in as {me.username}. Replace the initial password before you continue.
          </Typography.Paragraph>
          <ChangePasswordForm onDone={accept} />
          <Button type="link" style={{ padding: 0 }} onClick={signOut}>
            Sign out
          </Button>
        </Card>
      </Centered>
    );
  }
  return <AuthContext.Provider value={{ me, signOut, refresh: accept }}>{children}</AuthContext.Provider>;
}

function Centered({ children }: { children: ReactNode }) {
  return <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f5f5" }}>{children}</div>;
}

export function LoginPage({ notice, onSignedIn }: { notice?: string | null; onSignedIn: (me: Me) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hasUsers, setHasUsers] = useState(true);
  useEffect(() => {
    api<{ has_users: boolean }>("/auth/status")
      .then((s) => setHasUsers(s.has_users))
      .catch(() => {});
  }, []);
  const onFinish = async (values: { username: string; password: string }) => {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api<Me>("/auth/login", { method: "POST", body: values }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Centered>
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          TestAgent
        </Typography.Title>
        <Typography.Paragraph type="secondary">Sign in to continue</Typography.Paragraph>
        {!hasUsers && (
          <Result
            status="info"
            style={{ padding: "8px 0" }}
            title="No account yet"
            subTitle="Set TESTAGENT_ADMIN_USER and TESTAGENT_ADMIN_PASSWORD in .env and restart, or run: testagent user add <name> --admin"
          />
        )}
        {notice && <Alert type="info" showIcon style={{ marginBottom: 12 }} title={notice} />}
        {error && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={error} />}
        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item name="username" label="User name" rules={[{ required: true, message: "Enter your user name" }]}>
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, message: "Enter your password" }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            Sign in
          </Button>
        </Form>
      </Card>
    </Centered>
  );
}

export function ChangePasswordForm({ onDone }: { onDone: (me: Me) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const onFinish = async (v: { current_password: string; new_password: string }) => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api<Me>("/auth/password", { method: "POST", body: { current_password: v.current_password, new_password: v.new_password } }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
      {error && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={error} />}
      <Form.Item name="current_password" label="Current password" rules={[{ required: true }]}>
        <Input.Password autoComplete="current-password" />
      </Form.Item>
      <Form.Item name="new_password" label="New password (at least 10 characters)" rules={[{ required: true }, { min: 10, message: "At least 10 characters" }]}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name="confirm"
        label="Repeat new password"
        dependencies={["new_password"]}
        rules={[
          { required: true },
          ({ getFieldValue }) => ({
            validator: (_, value) => (!value || value === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("The passwords do not match"))),
          }),
        ]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Button type="primary" htmlType="submit" block loading={busy}>
        Save new password
      </Button>
    </Form>
  );
}
