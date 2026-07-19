import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../contexts/AuthContext";
import { cn } from "../../lib/utils";

const LINKS = [
  { to: "/library", key: "library", icon: "🎬" },
  { to: "/clusters", key: "clusters", icon: "🧭" },
  { to: "/knowledge", key: "knowledge", icon: "🧠" },
  { to: "/workspace", key: "workspace", icon: "⭐" },
  { to: "/accounts", key: "accounts", icon: "👤" },
];

export function Sidebar() {
  const { t } = useTranslation();
  const { logout, user } = useAuth();

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950 p-4">
      <div className="mb-8 px-2">
        <div className="text-lg font-bold tracking-tight text-white">
          {t("app.name")}
        </div>
        <div className="text-xs text-indigo-400">{t("app.tagline")}</div>
      </div>
      <nav className="flex flex-1 flex-col gap-1">
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive
                  ? "bg-indigo-600/20 text-indigo-300"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              )
            }
          >
            <span>{l.icon}</span>
            {t(`nav.${l.key}`)}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-zinc-800 pt-3">
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
