import { Fragment, Suspense, useState } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { JobsProvider } from "./contexts/JobsContext";
import { MobileDrawer, Sidebar } from "./components/layout/Sidebar";
import { MobileHeader } from "./components/layout/MobileHeader";
import { StatusBar } from "./components/layout/StatusBar";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
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
const ContentDetail = lazyPage(() => import("./pages/ContentDetail"));
const BrainMap = lazyPage(() => import("./pages/BrainMap"));
const Documentation = lazyPage(() => import("./pages/Documentation"));
const Status = lazyPage(() => import("./pages/Status"));

function Shell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  return (
    <div className="flex h-dvh overflow-hidden bg-white">
      <Sidebar className="hidden lg:flex" />
      <MobileDrawer open={navOpen} onClose={() => setNavOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileHeader onMenu={() => setNavOpen(true)} />
        <main className="min-w-0 flex-1 overflow-y-auto">
          {/* The key resets the boundary on navigation: an error stays in the
              page that caused it and "Riprova" starts that page from scratch. */}
          <ErrorBoundary key={pathname} level="page">
            {children}
          </ErrorBoundary>
        </main>
        {/* In the flow, under <main>: the pages get shorter instead of being
            covered. A fixed bar hid the chat's send row. */}
        <StatusBar />
      </div>
    </div>
  );
}

/** React Router keeps the same page mounted when only `:scope` changes, so
 *  filters, the selected month and an open drawer used to survive the switch
 *  from Medyca to Competitor, showing one side's ids under the other's name.
 *  Keying on the scope remounts the page. */
function Scoped({ children }: { children: React.ReactNode }) {
  const { scope } = useParams();
  return <Fragment key={scope}>{children}</Fragment>;
}

function AppRoutes() {
  return (
    <Shell>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/:scope/library" element={<Scoped><Library /></Scoped>} />
          <Route path="/:scope/timeline" element={<Scoped><Timeline /></Scoped>} />
          <Route path="/:scope/analytics" element={<Scoped><Analytics /></Scoped>} />
          <Route path="/:scope/clusters" element={<Scoped><Clusters /></Scoped>} />
          <Route path="/:scope/clusters/:id" element={<Scoped><ClusterDetail /></Scoped>} />
          <Route path="/second-brain" element={<SecondBrain />} />
          <Route path="/knowledge-bank" element={<KnowledgeBank />} />
          <Route path="/content/:kind/:id" element={<ContentDetail />} />
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

/** Where to go after the login: back to the page the client asked for (an MCP
 *  link opened while logged out), but only inside the app. `from` comes from
 *  navigation state we wrote ourselves; the check keeps an odd value from
 *  becoming an open redirect. */
function afterLoginTarget(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  if (typeof from !== "string" || !from.startsWith("/") || from.startsWith("//")) return "/";
  if (from === "/login" || from.startsWith("/login?")) return "/";
  return from;
}

function AfterLogin() {
  const { state } = useLocation();
  return <Navigate to={afterLoginTarget(state)} replace />;
}

function ToLogin() {
  const { pathname, search, hash } = useLocation();
  return <Navigate to="/login" replace state={{ from: pathname + search + hash }} />;
}

export default function App() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return (
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<ToLogin />} />
        </Routes>
      </Suspense>
    );
  }
  return (
    <JobsProvider>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/login" element={<AfterLogin />} />
          {/* Home is a full-screen page outside the shell, so its job bar floats. */}
          <Route
            path="/"
            element={
              <ErrorBoundary level="page">
                <Home />
                <StatusBar floating />
              </ErrorBoundary>
            }
          />
          <Route path="/*" element={<AppRoutes />} />
        </Routes>
      </Suspense>
    </JobsProvider>
  );
}
