import { Suspense, lazy, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { JobsProvider } from "./contexts/JobsContext";
import { MobileDrawer, Sidebar } from "./components/layout/Sidebar";
import { MobileHeader } from "./components/layout/MobileHeader";
import { StatusBar } from "./components/layout/StatusBar";
import { Spinner } from "./components/ui/primitives";

const Login = lazy(() => import("./pages/Login"));
const Home = lazy(() => import("./pages/Home"));
const Library = lazy(() => import("./pages/Library"));
const Clusters = lazy(() => import("./pages/Clusters"));
const ClusterDetail = lazy(() => import("./pages/ClusterDetail"));
const Timeline = lazy(() => import("./pages/Timeline"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Workspace = lazy(() => import("./pages/Workspace"));
const Accounts = lazy(() => import("./pages/Accounts"));
const SecondBrain = lazy(() => import("./pages/SecondBrain"));
const KnowledgeBank = lazy(() => import("./pages/KnowledgeBank"));
const BrainMap = lazy(() => import("./pages/BrainMap"));
const Documentation = lazy(() => import("./pages/Documentation"));
const Status = lazy(() => import("./pages/Status"));

function Shell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      <Sidebar className="hidden lg:flex" />
      <MobileDrawer open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileHeader onMenu={() => setNavOpen(true)} />
        <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
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
          <Route path="/:scope/analytics" element={<Analytics />} />
          <Route path="/:scope/clusters" element={<Clusters />} />
          <Route path="/:scope/clusters/:id" element={<ClusterDetail />} />
          <Route path="/second-brain" element={<SecondBrain />} />
          <Route path="/knowledge-bank" element={<KnowledgeBank />} />
          <Route path="/brain-map" element={<BrainMap />} />
          <Route path="/documentazione" element={<Documentation />} />
          <Route path="/stato" element={<Status />} />
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
