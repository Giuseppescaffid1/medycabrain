# Design Tokens (Medyca brand)

Single source of truth. Every value used in UI code must come from this file.

Provenance: values marked SAMPLED were pixel-sampled from a screenshot of www.medyca.it (July 2026). Values marked DERIVED were calculated from the sampled colors (hover shades, borders) and should be confirmed against official brand guidelines if the client provides them.

## Colors

| Token | Value | Source | Usage |
|---|---|---|---|
| `--color-bg` | `#FFFFFF` | SAMPLED | Page background |
| `--color-surface` | `#EEF5FD` | SAMPLED | Panels, cards, notice banners |
| `--color-border` | `#D5E3F2` | DERIVED | Dividers, input borders |
| `--color-text` | `#2C4984` | SAMPLED | Body text, nav links (Medyca navy) |
| `--color-heading` | `#346FAA` | SAMPLED | Headlines, large display text |
| `--color-primary` | `#C93B42` | SAMPLED | Primary CTA, brand red |
| `--color-primary-hover` | `#A93037` | DERIVED | Primary hover state |
| `--color-secondary` | `#4A6FAC` | SAMPLED | Secondary buttons ("Learn more" style) |
| `--color-secondary-hover` | `#3A5B94` | DERIVED | Secondary hover state |
| `--color-success` | `#1E7E4A` | DERIVED | Success states (no green on brand site) |
| `--color-warning` | `#B7791F` | DERIVED | Warnings (no amber on brand site) |
| `--color-danger` | `#C93B42` | SAMPLED | Errors (same as brand red, see note) |

Rules:
- `--color-primary` (red) appears on at most one element per view: the primary action. This matches the live site, where red is reserved for the announcement bar and the booking CTA.
- Because the brand red doubles as the danger color, error states must never rely on color alone: always pair with an error icon and explicit error text.
- White text on `--color-primary` and `--color-secondary` passes the 4.5:1 contrast floor (both roughly 5:1). `--color-text` and `--color-heading` on white also pass. Do not place `--color-heading` text on `--color-surface` at small sizes without checking contrast first.

## Typography

The live site uses a rounded geometric sans for both headings and body. Confirm the exact licensed family with the client; until then use:

| Token | Value |
|---|---|
| `--font-body` | 'Nunito Sans', system-ui, sans-serif (placeholder, confirm with client) |
| `--font-mono` | ui-monospace stack |
| `--text-xs` | 12px / 16px line height |
| `--text-sm` | 14px / 20px |
| `--text-base` | 16px / 24px |
| `--text-lg` | 18px / 28px |
| `--text-xl` | 24px / 32px |
| `--text-2xl` | 32px / 40px |
| `--text-display` | 48px / 56px (hero headlines, `--color-heading`) |

Weights: 400 (body), 500 (labels, buttons), 600 (headings). Headings use `--color-heading`, body uses `--color-text`.

## Spacing scale

4, 8, 12, 16, 24, 32, 48, 64 (px). All padding, margin, and gap values come from this list.

## Radii and shadows

The brand uses fully rounded (pill) buttons and soft cards.

| Token | Value | Usage |
|---|---|---|
| `--radius-sm` | 6px | Inputs, tags |
| `--radius-md` | 12px | Cards, panels |
| `--radius-lg` | 24px | Hero images, large panels |
| `--radius-pill` | 999px | All buttons (matches live site) |
| `--shadow-sm` | `0 1px 2px rgba(44,73,132,.08)` | Cards at rest |
| `--shadow-md` | `0 4px 16px rgba(44,73,132,.12)` | Modals, popovers |

## Motion

- Durations: 120ms (micro), 200ms (standard), 320ms (large surfaces)
- Easing: `cubic-bezier(0.2, 0, 0, 1)`
- All animation wrapped in a `prefers-reduced-motion` check
