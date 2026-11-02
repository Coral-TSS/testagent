import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthGate } from "./AuthGate";
import { routes } from "./routes";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
});
const router = createBrowserRouter(routes);

export function App() {
  return (
    <ConfigProvider locale={enUS}>
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <AuthGate>
            <RouterProvider router={router} />
          </AuthGate>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
