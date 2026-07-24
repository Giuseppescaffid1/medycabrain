import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

/* Shared pill-input classes (search fields, selects, form inputs). */
export const fieldCls =
  "h-10 rounded-full border border-border bg-white px-4 text-sm text-navy " +
  "placeholder:text-muted/70 outline-none transition duration-200 focus:border-secondary";

export function Badge({
  children,
  className,
  color,
}: {
  children: ReactNode;
  className?: string;
  color?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold",
        !color && "border border-border bg-white text-secondary",
        className
      )}
      style={color ? { backgroundColor: color + "22", color } : undefined}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-muted">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-secondary" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-surface", className)} aria-hidden />;
}

export function Button({
  children,
  onClick,
  variant = "primary",
  type = "button",
  disabled,
  loading,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}) {
  const variants = {
    primary: "bg-brand text-white hover:bg-brand-hover",
    secondary: "border border-border bg-white text-navy hover:border-secondary",
    ghost: "text-secondary hover:bg-surface",
    danger: "bg-danger text-white hover:bg-brand-hover",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        "relative inline-flex h-10 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition duration-200 disabled:opacity-50",
        variants[variant],
        className
      )}
    >
      {loading && (
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
        </span>
      )}
      <span className={cn(loading && "invisible", "inline-flex items-center gap-2")}>
        {children}
      </span>
    </button>
  );
}

export function Card({
  children,
  className,
  title,
  dense,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  dense?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-surface shadow-card",
        dense ? "p-4" : "p-6",
        className
      )}
    >
      {title && (
        <h2 className="mb-3 text-xs font-bold uppercase tracking-wider text-muted">{title}</h2>
      )}
      {children}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center text-muted">
      <div className="mb-3 text-4xl">🗂️</div>
      <p className="max-w-md text-sm">{message}</p>
    </div>
  );
}
