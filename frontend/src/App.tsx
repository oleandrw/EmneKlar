import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";

import { ApiError } from "./core/api/client";
import { SessionProvider } from "./core/session";
import { UiProvider } from "./core/ui";
import { ToastProvider } from "./design-system";
import { AppRoutes } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
      staleTime: 15_000,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionProvider>
          <UiProvider>
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
          </UiProvider>
        </SessionProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
