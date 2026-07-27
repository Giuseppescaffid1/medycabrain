import { Suspense, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { JobsProvider } from "./contexts/JobsContext";
import { MobileDrawer, Sidebar } from "./components/layout/Sidebar";
import { MobileHeader } from "./components/layout/MobileHeader";
import { StatusBar } from "./components/layout/StatusBar";
import { Spinner } from "./components/ui/primitives";
import { lazyPage } from "./lib/lazyPage";

const Login = lazyPage(() => import("./pages/Login"));
const Home = lazyPage(() => import("./pages/Home"));
const Library = lazyPage(() => import("./pages/Library"));
const Clusters = lazyPage(() => import("./pages/Clusters"));
const ClusterDetail = lazyPage(() => import("./pages/ClusterDetail"));
const Timeline = lazyPage(() => import("./pages/Timeline"));
const Analytics = lazyPage(() => import("./pages/Analytics"));
const Workspace = lazyPage(() => import("./pages/Workspace"));
const Accounts = lazyPage(() => import("./pages/Accounts"));
const SecondBrain = lazyPage(() => import("./pages/SecondBrain"));
const KnowledgeBank = lazyPage(() => import("./pages/KnowledgeBank"));
const BrainMap = lazyPage(() => import("./pages/BrainMap"));
const Documentation = lazyPage(() => import("./pages/Documentation"));
const Status = lazyPage(() => import("./pages/Status"));

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
