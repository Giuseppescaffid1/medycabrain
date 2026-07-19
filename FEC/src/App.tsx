import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { Sidebar } from "./components/layout/Sidebar";
import { Spinner } from "./components/ui/primitives";

const Login = lazy(() => import("./pages/Login"));
const Library = lazy(() => import("./pages/Library"));
const Clusters = lazy(() => import("./pages/Clusters"));
const ClusterDetail = lazy(() => import("./pages/ClusterDetail"));
const Workspace = lazy(() => import("./pages/Workspace"));
const Accounts = lazy(() => import("./pages/Accounts"));
const KnowledgeBank = lazy(() => import("./pages/KnowledgeBank"));

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

function ProtectedRoutes() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return (
    <Shell>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/library" element={<Library />} />
          <Route path="/clusters" element={<Clusters />} />
          <Route path="/clusters/:id" element={<ClusterDetail />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/knowledge" element={<KnowledgeBank />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="*" element={<Navigate to="/library" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}

export default function App() {
  const { isAuthenticated } = useAuth();
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route
          path="/login"
          element={isAuthenticated ? <Navigate to="/library" replace /> : <Login />}
        />
        <Route path="/*" element={<ProtectedRoutes />} />
      </Routes>
    </Suspense>
  );
}
