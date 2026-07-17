import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatCount(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return String(n);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("it-IT", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

const FORMAT_LABELS: Record<string, string> = {
  talking_head: "Talking head",
  voiceover: "Voiceover",
  tutorial: "Tutorial",
  testimonianza: "Testimonianza",
  text_overlay: "Testo in sovrimpressione",
  intervista: "Intervista",
  altro: "Altro",
};

export function formatLabel(key: string): string {
  return FORMAT_LABELS[key] || key;
}

/** Resolve a media-relative path to a URL the browser can load. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `/media/${path}`;
}
