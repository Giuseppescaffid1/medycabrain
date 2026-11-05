import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Button } from "./primitives";

/**
 * The net under every render error. Without one, React unmounts the whole tree
 * on the first exception and the client sees a white screen.
 *
 * The only class component in the project: React offers no hook for this.
 * Two levels: around the whole app (last resort, reload) and around `<main>`
 * (the error stays in the page that caused it; menu and status bar live on).
 */
interface Props {
  children: ReactNode;
  level: "app" | "page";
}

export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The console is the only trace a white screen leaves.
    console.error("ErrorBoundary", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return this.props.level === "app" ? (
      <AppFallback />
    ) : (
      <PageFallback onRetry={() => this.setState({ failed: false })} />
    );
  }
}

/* Outside the router (it wraps it): plain anchors and a real reload. */
function AppFallback() {
  const { t } = useTranslation();
  return (
    <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-ground p-6 text-center">
      <p className="text-lg font-bold text-heading">{t("boundary.appTitle")}</p>
      <p className="max-w-md text-sm text-muted">{t("boundary.appBody")}</p>
      <Button onClick={() => window.location.reload()}>{t("boundary.reload")}</Button>
    </div>
  );
}

function PageFallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="flex h-full flex-col items-center justify-center gap-4 px-4 py-20 text-center">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
           strokeLinecap="round" strokeLinejoin="round" className="text-danger" aria-hidden>
        <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
        <path d="M12 9v4M12 17h.01" />
      </svg>
      <p className="text-base font-bold text-heading">{t("boundary.pageTitle")}</p>
      <p className="max-w-md text-sm text-muted">{t("boundary.pageBody")}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button onClick={onRetry}>{t("common.retry")}</Button>
        <Link
          to="/"
          onClick={onRetry}
          className="inline-flex h-10 items-center rounded-full border border-border bg-white px-5 text-sm font-semibold text-navy transition hover:border-secondary"
        >
          {t("boundary.home")}
        </Link>
      </div>
    </div>
  );
}
