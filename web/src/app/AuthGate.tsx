import { Result } from "antd";
import { useEffect, useState, type ReactNode } from "react";

import { AUTH_EVENT } from "../api/client";
import { getToken } from "./token";

/** Shows a clear hint instead of broken pages when the launcher token is missing/expired. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [expired, setExpired] = useState(() => !getToken());
  useEffect(() => {
    const onAuth = () => setExpired(true);
    window.addEventListener(AUTH_EVENT, onAuth);
    return () => window.removeEventListener(AUTH_EVENT, onAuth);
  }, []);
  if (expired) {
    return (
      <Result
        status="403"
        title="Sign-in required"
        subTitle="Reopen the platform from the launcher (run uv run testagent; the browser gets a fresh access token automatically), or open the sign-in link printed in the server log (it ends with #t=<access token>)."
      />
    );
  }
  return <>{children}</>;
}
