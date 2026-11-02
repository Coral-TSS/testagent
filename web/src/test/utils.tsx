import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

export function renderPage(element: ReactElement, { path = "/", route = "/" } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ConfigProvider locale={enUS}>
      <AntApp>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={[route]}>
            <Routes>
              <Route path={path} element={element} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  );
}

type Handler = (init: RequestInit & { url: string }) => { status?: number; body?: unknown };

/** Minimal fetch mock: routes "METHOD /path" (path without /api/v1 and query) to handlers. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { method: string; path: string; body?: unknown; headers: Record<string, string> }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = init.method || "GET";
    const path = url.replace(/^\/api\/v1/, "").split("?")[0];
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: (init.headers || {}) as Record<string, string> });
    const handler = routes[`${method} ${path}`];
    const { status = 200, body } = handler ? handler({ ...init, url }) : { status: 404, body: { code: "NOT_FOUND", message: "not mocked" } };
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}
