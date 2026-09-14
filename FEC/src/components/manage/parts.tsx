import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/utils";
import { fieldCls } from "../ui/primitives";

/**
 * Shared shell for the management screen (`/accounts`).
 *
 * The three things you manage here — Instagram profiles, blogs, uploaded
 * interviews — are the same job three times: a list you scan, a search to
 * find one row, a form you only need when adding. Keeping the pieces in one
 * file means the three panels cannot drift into three different layouts.
 */

/* ── Tabs ──────────────────────────────────────────────────────────────── */

export type TabItem = { id: string; label: string; count?: number };

export function Tabs({
  items,
  value,
  onChange,
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Sezioni"
      className="-mx-4 flex flex-nowrap gap-1 overflow-x-auto px-4 sm:mx-0 sm:px-0"
    >
      {items.map((tab) => {
        const on = tab.id === value;
        return (
          <button
            key={tab.id}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={on}
            aria-controls={`panel-${tab.id}`}
            onClick={() => onChange(tab.id)}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition duration-200",
              "outline-none focus-visible:ring-2 focus-visible:ring-secondary",
              on
                ? "bg-secondary/10 text-secondary"
                : "text-navy/70 hover:bg-surface hover:text-navy"
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-xs font-bold tabular-nums",
                  on ? "bg-secondary/15 text-secondary" : "bg-surface text-muted"
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ── Panel head: what this list is, and the one primary action ─────────── */

export function PanelHeader({
  description,
  action,
}: {
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <p className="max-w-[60ch] text-sm text-muted">{description}</p>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** The add form, folded away until asked for: the list is what you come for. */
export function AddForm({ open, children }: { open: boolean; children: ReactNode }) {
  if (!open) return null;
  return (
    <div className="mb-4 rounded-xl border border-border bg-surface p-4 shadow-card">
      {children}
    </div>
  );
}

export function FormError({ message }: { message: string }) {
  return (
    <p role="alert" className="mt-3 flex items-start gap-2 text-sm font-semibold text-danger">
      <span aria-hidden>⚠</span>
      <span>{message}</span>
    </p>
  );
}

/* ── Toolbar: search + filters, above every list ───────────────────────── */

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex flex-wrap items-center gap-2">{children}</div>;
}

export function SearchField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label={placeholder}
      className={fieldCls + " w-full min-w-0 sm:w-64"}
    />
  );
}

export function FilterSelect({
  value,
  onChange,
  label,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      className={fieldCls + " w-auto pr-3"}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function ResultCount({ shown, total }: { shown: number; total: number }) {
  const { t } = useTranslation();
  return (
    <span className="ml-auto text-xs font-semibold text-muted tabular-nums">
      {t("manage.showing", { shown, total })}
    </span>
  );
}

/* ── Table frame: one look for all three lists ─────────────────────────── */

export function TableFrame({
  head,
  minWidth = 640,
  children,
}: {
  head: ReactNode;
  minWidth?: number;
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-white shadow-card">
      <table className="w-full text-sm" style={{ minWidth }}>
        <thead className="bg-surface text-left text-xs font-bold uppercase tracking-wider text-muted">
          <tr>{head}</tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
}: {
  children?: ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th className={cn("px-4 py-3 font-bold", align === "right" && "text-right")}>
      {children}
    </th>
  );
}

/** Nothing to show: say what fills the list, never just "vuoto". */
export function PanelEmpty({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-surface px-6 py-12 text-center">
      <p className="max-w-[46ch] text-sm text-muted">{message}</p>
      {action}
    </div>
  );
}

/** Row actions, always right-aligned and in the same order across lists. */
export function RowActions({ children }: { children: ReactNode }) {
  return <div className="flex items-center justify-end gap-3">{children}</div>;
}

export function RowAction({
  onClick,
  disabled,
  tone = "neutral",
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  tone?: "neutral" | "danger" | "action";
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-full px-1 text-xs font-semibold transition duration-200",
        "outline-none focus-visible:ring-2 focus-visible:ring-secondary disabled:opacity-50",
        tone === "danger" && "text-muted hover:text-danger",
        tone === "action" && "text-secondary hover:text-heading",
        tone === "neutral" && "text-muted hover:text-navy"
      )}
    >
      {children}
    </button>
  );
}

/** A status pill you can click to flip. Same affordance in all three lists. */
export function StatusToggle({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="rounded-full outline-none transition duration-200 hover:opacity-80 focus-visible:ring-2 focus-visible:ring-secondary"
    >
      {children}
    </button>
  );
}
