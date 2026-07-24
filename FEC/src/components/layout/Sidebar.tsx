import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import { cn } from "../../lib/utils";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
    isActive
      ? "bg-indigo-600/20 text-indigo-300"
      : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
  );

function Section({ label }: { label: string }) {
  return (
    <div className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
      {label}
    </div>
  );
}

export function Sidebar() {
  const { t } = useTranslation();
  const { logout, user } = useAuth();

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col overflow-y-auto border-r border-zinc-800 bg-zinc-950 p-4">
      <NavLink to="/" className="mb-4 block px-2">
        <div className="text-lg font-bold tracking-tight text-white">
          Med<span className="text-red-400">y</span>ca
        </div>
        <div className="text-xs text-indigo-400">Content Intelligence</div>
      </NavLink>

      <nav className="flex flex-1 flex-col gap-0.5">
        <Section label={t("nav.medyca")} />
        <NavLink to="/medyca/library" className={linkClass}>🎬 {t("nav.library")}</NavLink>
        <NavLink to="/medyca/analytics" className={linkClass}>📊 {t("nav.analytics")}</NavLink>
        <NavLink to="/medyca/timeline" className={linkClass}>📅 {t("nav.timeline")}</NavLink>
        <NavLink to="/medyca/clusters" className={linkClass}>🧭 {t("nav.clusters")}</NavLink>

        <Section label={t("nav.competitor")} />
        <NavLink to="/competitor/library" className={linkClass}>🎬 {t("nav.library")}</NavLink>
        <NavLink to="/competitor/analytics" className={linkClass}>📊 {t("nav.analytics")}</NavLink>
        <NavLink to="/competitor/timeline" className={linkClass}>📅 {t("nav.timeline")}</NavLink>
        <NavLink to="/competitor/clusters" className={linkClass}>🧭 {t("nav.clusters")}</NavLink>

        <Section label={t("nav.tools")} />
        <NavLink to="/second-brain" className={linkClass}>🧠 {t("nav.secondBrain")}</NavLink>
        <NavLink to="/brain-map" className={linkClass}>🕸️ {t("nav.brainMap")}</NavLink>
        <NavLink to="/knowledge-bank" className={linkClass}>📚 {t("nav.knowledgeBank")}</NavLink>
        <NavLink to="/workspace" className={linkClass}>⭐ {t("nav.workspace")}</NavLink>
        <NavLink to="/accounts" className={linkClass}>👤 {t("nav.accounts")}</NavLink>
      </nav>

      <div className="mt-2 border-t border-zinc-800 pt-3">
        <div className="mb-2 px-3 text-xs text-zinc-500">{user?.username}</div>
        <button
          onClick={logout}
          className="w-full rounded-lg px-3 py-2 text-left text-sm text-zinc-400 hover:bg-zinc-900 hover:text-red-400"
        >
          ⏻ {t("nav.logout")}
        </button>
      </div>
    </aside>
  );
}
