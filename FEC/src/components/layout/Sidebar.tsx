import { useEffect } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "../../contexts/AuthContext";
import { cn } from "../../lib/utils";
import { EASE } from "../ui/motion";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex min-h-11 items-center gap-3 rounded-full px-4 py-2 text-sm font-semibold transition duration-200",
    isActive
      ? "bg-surface text-heading"
      : "text-navy/70 hover:bg-surface/60 hover:text-navy"
  );

function Section({ label }: { label: string }) {
  return (
    <div className="px-4 pb-1 pt-4 text-[10px] font-bold uppercase tracking-wider text-muted/80">
      {label}
    </div>
  );
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

/* Nav content shared between the desktop rail and the mobile drawer. */
export function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { logout, user } = useAuth();

  return (
    <>
      <NavLink to="/" className="mb-2 block px-2" onClick={onNavigate}>
        <Wordmark />
      </NavLink>

      <nav className="flex flex-1 flex-col gap-0.5">
        <Section label={t("nav.medyca")} />
        <NavLink to="/medyca/library" className={linkClass} onClick={onNavigate}>🎬 {t("nav.library")}</NavLink>
        <NavLink to="/medyca/analytics" className={linkClass} onClick={onNavigate}>📊 {t("nav.analytics")}</NavLink>
        <NavLink to="/medyca/timeline" className={linkClass} onClick={onNavigate}>📅 {t("nav.timeline")}</NavLink>
        <NavLink to="/medyca/clusters" className={linkClass} onClick={onNavigate}>🧭 {t("nav.clusters")}</NavLink>

        <Section label={t("nav.competitor")} />
        <NavLink to="/competitor/library" className={linkClass} onClick={onNavigate}>🎬 {t("nav.library")}</NavLink>
        <NavLink to="/competitor/analytics" className={linkClass} onClick={onNavigate}>📊 {t("nav.analytics")}</NavLink>
        <NavLink to="/competitor/timeline" className={linkClass} onClick={onNavigate}>📅 {t("nav.timeline")}</NavLink>
        <NavLink to="/competitor/clusters" className={linkClass} onClick={onNavigate}>🧭 {t("nav.clusters")}</NavLink>

        <Section label={t("nav.tools")} />
        <NavLink to="/second-brain" className={linkClass} onClick={onNavigate}>🧠 {t("nav.secondBrain")}</NavLink>
        <NavLink to="/brain-map" className={linkClass} onClick={onNavigate}>🕸️ {t("nav.brainMap")}</NavLink>
        <NavLink to="/knowledge-bank" className={linkClass} onClick={onNavigate}>📚 {t("nav.knowledgeBank")}</NavLink>
        <NavLink to="/workspace" className={linkClass} onClick={onNavigate}>⭐ {t("nav.workspace")}</NavLink>
        <NavLink to="/accounts" className={linkClass} onClick={onNavigate}>👤 {t("nav.accounts")}</NavLink>
        <NavLink to="/documentazione" className={linkClass} onClick={onNavigate}>📘 {t("nav.documentation")}</NavLink>
        <NavLink to="/stato" className={linkClass} onClick={onNavigate}>📡 {t("nav.status")}</NavLink>
      </nav>

      <div className="mt-2 border-t border-border pt-3">
        <div className="mb-2 px-4 text-xs font-semibold text-muted">{user?.username}</div>
        <button
          onClick={logout}
          className="flex min-h-11 w-full items-center rounded-full px-4 py-2 text-left text-sm font-semibold text-muted transition hover:bg-surface hover:text-danger"
        >
          ⏻ {t("nav.logout")}
        </button>
      </div>
    </>
  );
}

export function Sidebar({ className }: { className?: string }) {
  return (
    <aside
      className={cn(
        "h-full w-60 shrink-0 flex-col overflow-y-auto border-r border-border bg-ground p-4",
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

  // Close on navigation and on Escape.
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
            className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col overflow-y-auto bg-white p-4 shadow-float lg:hidden"
            role="dialog"
            aria-modal="true"
            aria-label={t("nav.menu")}
          >
            <div className="mb-1 flex items-start justify-between">
              <div className="flex-1" />
              <button
                onClick={onClose}
                aria-label={t("nav.closeMenu")}
                className="flex h-11 w-11 items-center justify-center rounded-full text-muted transition hover:bg-surface hover:text-navy"
              >
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            <NavContent onNavigate={onClose} />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
