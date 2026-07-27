import { useEffect } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "../../contexts/AuthContext";
import { cn } from "../../lib/utils";
import { EASE } from "../ui/motion";
import {
  IconAccounts, IconAnalytics, IconChat, IconClusters, IconDocs, IconLibrary,
  IconLogout, IconMap, IconPlan, IconPulse, IconStar, IconTimeline,
} from "../ui/icons";

type Scope = "medyca" | "competitor";

/** Which content set the scoped links point at. Read from the URL, which is
 *  where the pages already take it from, so navigation and page state cannot
 *  disagree. */
function useScope(): [Scope, (s: Scope) => void] {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current: Scope = pathname.startsWith("/competitor") ? "competitor" : "medyca";
  const set = (s: Scope) => {
    const rest = pathname.match(/^\/(?:medyca|competitor)\/(.*)$/)?.[1];
    navigate(rest ? `/${s}/${rest}` : `/${s}/library`);
  };
  return [current, set];
}

export function Wordmark() {
  return (
    <>
      <div className="text-lg font-bold tracking-tight text-heading">
        Med<span className="text-brand">y</span>ca
      </div>
      <div className="text-xs font-semibold text-secondary">Content Intelligence</div>
    </>
  );
}

/** Medyca / Competitor. The four scoped links below follow it, so the nav
 *  carries one set of entries instead of the same four twice over. */
function ScopeSwitch({ scope, onChange }: { scope: Scope; onChange: (s: Scope) => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex rounded-full border border-border bg-white p-1">
      {(["medyca", "competitor"] as Scope[]).map((s) => {
        const on = scope === s;
        return (
          <button
            key={s}
            onClick={() => onChange(s)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-full py-1.5 text-xs font-bold transition duration-200",
              on
                ? s === "medyca"
                  ? "bg-secondary/10 text-secondary"
                  : "bg-warning/10 text-warning"
                : "text-muted hover:text-navy"
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                s === "medyca" ? "bg-secondary" : "bg-warning",
                on ? "" : "opacity-40"
              )}
              aria-hidden
            />
            {t(`scope.${s}`)}
          </button>
        );
      })}
    </div>
  );
}

function GroupLabel({ label }: { label: string }) {
  return (
    <div className="px-3 pb-1 pt-4 text-[10px] font-bold uppercase tracking-[0.14em] text-muted/70">
      {label}
    </div>
  );
}

function Item({
  to,
  icon: Icon,
  label,
  tone,
  onNavigate,
}: {
  to: string;
  icon: (p: { className?: string }) => JSX.Element;
  label: string;
  tone?: Scope;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "relative flex min-h-10 items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold transition duration-200",
          isActive
            ? tone === "competitor"
              ? "bg-warning/10 text-warning"
              : "bg-secondary/10 text-secondary"
            : "text-navy/75 hover:bg-surface hover:text-navy"
        )
      }
    >
      {({ isActive }) => (
        <>
          {/* active marker: a rail, quieter than a fully filled pill */}
          <span
            className={cn(
              "absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full transition",
              isActive
                ? tone === "competitor"
                  ? "bg-warning"
                  : "bg-secondary"
                : "bg-transparent"
            )}
            aria-hidden
          />
          <Icon />
          <span className="truncate">{label}</span>
        </>
      )}
    </NavLink>
  );
}

export function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();
  const [scope, setScope] = useScope();

  return (
    <>
      <NavLink to="/" className="block px-3 pb-4" onClick={onNavigate}>
        <Wordmark />
      </NavLink>

      <div className="border-t border-border pt-3">
        <ScopeSwitch scope={scope} onChange={setScope} />
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 pt-2">
        <Item to={`/${scope}/library`} icon={IconLibrary} label={t("nav.library")} tone={scope} onNavigate={onNavigate} />
        <Item to={`/${scope}/analytics`} icon={IconAnalytics} label={t("nav.analytics")} tone={scope} onNavigate={onNavigate} />
        <Item to={`/${scope}/timeline`} icon={IconTimeline} label={t("nav.timeline")} tone={scope} onNavigate={onNavigate} />
        <Item to={`/${scope}/clusters`} icon={IconClusters} label={t("nav.clusters")} tone={scope} onNavigate={onNavigate} />

        <GroupLabel label={t("nav.tools")} />
        <Item to="/second-brain" icon={IconPlan} label={t("nav.plan")} onNavigate={onNavigate} />
        <Item to="/knowledge-bank" icon={IconChat} label={t("nav.knowledgeBank")} onNavigate={onNavigate} />
        <Item to="/brain-map" icon={IconMap} label={t("nav.brainMap")} onNavigate={onNavigate} />
        <Item to="/workspace" icon={IconStar} label={t("nav.workspace")} onNavigate={onNavigate} />

        <GroupLabel label={t("nav.manage")} />
        <Item to="/accounts" icon={IconAccounts} label={t("nav.accounts")} onNavigate={onNavigate} />
        <Item to="/documentazione" icon={IconDocs} label={t("nav.documentation")} onNavigate={onNavigate} />
        <Item to="/stato" icon={IconPulse} label={t("nav.status")} onNavigate={onNavigate} />
      </nav>

      <div className="mt-3 flex items-center gap-3 border-t border-border pt-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-xs font-bold uppercase text-secondary">
          {(user?.username ?? "?").slice(0, 2)}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-navy">
          {user?.username}
        </span>
        <button
          onClick={logout}
          aria-label={t("nav.logout")}
          title={t("nav.logout")}
          className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-surface hover:text-danger"
        >
          <IconLogout />
        </button>
      </div>
    </>
  );
}

export function Sidebar({ className }: { className?: string }) {
  return (
    <aside
      className={cn(
        "h-full w-64 shrink-0 flex-col overflow-y-auto border-r border-border bg-ground p-3",
        className ?? "flex"
      )}
    >
      <NavContent />
    </aside>
  );
}

export function MobileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const location = useLocation();

  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-navy/30 lg:hidden"
            aria-hidden
          />
          <motion.aside
            key="drawer"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.32, ease: EASE }}
            className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col overflow-y-auto bg-ground p-3 shadow-float lg:hidden"
            role="dialog"
            aria-modal="true"
            aria-label={t("nav.menu")}
          >
            <button
              onClick={onClose}
              aria-label={t("nav.closeMenu")}
              className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:bg-surface hover:text-navy"
            >
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </button>
            <NavContent onNavigate={onClose} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
