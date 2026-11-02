// Launcher token flow (architecture §9): #t=<token> → sessionStorage → fragment removed.
export const TOKEN_KEY = "testagent.token";

export function captureToken(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  storage: Storage = window.sessionStorage,
  history: Pick<History, "replaceState"> = window.history,
): string | null {
  const match = /(?:^#|&)t=([^&]+)/.exec(loc.hash);
  if (match) {
    storage.setItem(TOKEN_KEY, decodeURIComponent(match[1]));
    history.replaceState(null, "", loc.pathname + loc.search);
  }
  return storage.getItem(TOKEN_KEY);
}

export function getToken(storage: Storage = window.sessionStorage): string | null {
  return storage.getItem(TOKEN_KEY);
}
