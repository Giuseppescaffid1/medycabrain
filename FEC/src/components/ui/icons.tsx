/**
 * One stroke-based icon set for the whole app.
 *
 * Emoji were quick but they render differently on every OS and are the first
 * thing that makes an interface look unfinished. These inherit currentColor,
 * so a link's colour carries its icon.
 */
type P = { className?: string };
const base = "h-[18px] w-[18px] shrink-0";

const svg = (d: React.ReactNode) => ({ className }: P) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className ?? base}
    aria-hidden
  >
    {d}
  </svg>
);

export const IconLibrary = svg(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9h18M8 4v5M16 4v5" />
    <path d="m11 13 4 2.5-4 2.5z" />
  </>
);

export const IconAnalytics = svg(
  <>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </>
);

export const IconTimeline = svg(
  <>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18M8 3v4M16 3v4M8 15h3M8 18h6" />
  </>
);

export const IconClusters = svg(
  <>
    <circle cx="12" cy="12" r="2.4" />
    <circle cx="5" cy="6" r="2" />
    <circle cx="19" cy="7" r="2" />
    <circle cx="6" cy="19" r="2" />
    <path d="m10 11-3-3M14 11l3-3M10.5 14 8 17.4" />
  </>
);

export const IconPlan = svg(
  <>
    <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5z" />
    <path d="M8 8h7M8 12h5" />
  </>
);

export const IconMap = svg(
  <>
    <circle cx="6" cy="7" r="2" />
    <circle cx="18" cy="6" r="2" />
    <circle cx="12" cy="13" r="2.2" />
    <circle cx="7" cy="19" r="2" />
    <circle cx="18" cy="18" r="2" />
    <path d="m8 8 2.5 3.5M16.4 7.4 13.6 11.4M11 14.7 8.6 17.3M13.8 14.2l2.6 2.6" />
  </>
);

export const IconChat = svg(
  <>
    <path d="M21 12a8 8 0 0 1-8 8H7l-4 3V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z" />
    <path d="M9 11h6M9 14.5h3.5" />
  </>
);

export const IconStar = svg(
  <path d="m12 3.6 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
);

export const IconAccounts = svg(
  <>
    <circle cx="12" cy="8" r="3.4" />
    <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
  </>
);

export const IconDocs = svg(
  <>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4M9 12h6M9 16h4" />
  </>
);

export const IconPulse = svg(
  <path d="M2 12h4l2.5-6 4 13 3-9 2 2h4.5" />
);

export const IconLogout = svg(
  <>
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
    <path d="M10 8 6 12l4 4M6 12h9" />
  </>
);
