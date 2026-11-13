/** Numbers the way the Italian client reads them: 4,2 and 1.250. */
export const fmtNum = (n: number, digits = 1) =>
  n.toLocaleString("it-IT", { maximumFractionDigits: digits });

export const clock = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })
    : "";

/** "oggi alle 14:15" / "ieri alle 03:10" / "12/11 alle 03:10". */
export function whenLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const day = same(d, today)
    ? "oggi"
    : same(d, yesterday)
      ? "ieri"
      : d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" });
  return `${day} alle ${clock(iso)}`;
}
