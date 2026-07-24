import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Wordmark } from "./Sidebar";

export function MobileHeader({ onMenu }: { onMenu: () => void }) {
  const { t } = useTranslation();
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-white/85 px-4 backdrop-blur lg:hidden">
      <Link to="/" className="leading-tight">
        <Wordmark />
      </Link>
      <button
        onClick={onMenu}
        aria-label={t("nav.menu")}
        className="flex h-11 w-11 items-center justify-center rounded-full text-navy transition hover:bg-surface"
      >
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden>
          <path d="M3 6h16M3 11h16M3 16h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
    </header>
  );
}
