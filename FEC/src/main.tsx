import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import { AuthProvider } from "./contexts/AuthContext";
import App from "./App";
import { errorStatus } from "./api/client";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import "./i18n";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // One retry for a dropped connection or a 5xx (gunicorn restarting);
      // never for a 4xx: a 404 does not turn into a 200 on the second try, it
      // only doubles the wait before "not found" appears.
      retry: (failures, error) => {
        const status = errorStatus(error);
        return failures < 1 && (status === undefined || status >= 500);
      },
      refetchOnWindowFocus: false,
      staleTime: 60_000,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary level="app">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <MotionConfig reducedMotion="user">
            <AuthProvider>
              <App />
            </AuthProvider>
          </MotionConfig>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
