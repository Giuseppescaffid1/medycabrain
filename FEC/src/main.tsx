import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import { AuthProvider } from "./contexts/AuthContext";
import App from "./App";
import "./i18n";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 60_000 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <MotionConfig reducedMotion="user">
          <AuthProvider>
            <App />
          </AuthProvider>
        </MotionConfig>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
