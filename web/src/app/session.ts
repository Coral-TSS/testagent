// Sign-in state shared by the API client (t98u). The session itself is an HttpOnly cookie the
// page never sees; only the CSRF token for writes lives here, in memory.

export interface Me {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "member";
  must_change_password: boolean;
  csrf_token: string;
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

/** Desktop launcher: #ticket=<one-time ticket> → returned once, fragment removed from the address bar. */
export function takeTicket(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  history: Pick<History, "replaceState"> = window.history,
): string | null {
  const match = /(?:^#|&)ticket=([^&]+)/.exec(loc.hash || "");
  if (!match) return null;
  history.replaceState(null, "", loc.pathname + loc.search);
  return decodeURIComponent(match[1]);
}
