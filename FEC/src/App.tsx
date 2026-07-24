import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { JobsProvider } from "./contexts/JobsContext";
import { Sidebar } from "./components/layout/Sidebar";
import { StatusBar } from "./components/layout/StatusBar";
import { Spinner } from "./components/ui/primitives";

const Login = lazy(() => import("./pages/Login"));
const Home = lazy(() => import("./pages/Home"));
const Library = lazy(() => import("./pages/Library"));
const Clusters = lazy(() => import("./pages/Clusters"));
const ClusterDetail = lazy(() => import("./pages/ClusterDetail"));
const Timeline = lazy(() => import("./pages/Timeline"));
const Workspace = lazy(() => import("./pages/Workspace"));
const Accounts = lazy(() => import("./pages/Accounts"));
const SecondBrain = lazy(() => import("./pages/SecondBrain"));

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}

function AppRoutes() {
  return (
    <Shell>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/:scope/library" element={<Library />} />
          <Route path="/:scope/timeline" element={<Timeline />} />
          <Route path="/:scope/clusters" element={<Clusters />} />
          <Route path="/:scope/clusters/:id" element={<ClusterDetail />} />
          <Route path="/second-brain" element={<SecondBrain />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  );
}

export default function App() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return (
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    );
  }
  return (
    <JobsProvider>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="/" element={<Home />} />
          <Route path="/*" element={<AppRoutes />} />
        </Routes>
      </Suspense>
      <StatusBar />
    </JobsProvider>
  );
}
