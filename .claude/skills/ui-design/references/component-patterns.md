# Component Patterns

Approved patterns. Reuse these; do not invent parallel variants.

## Buttons

Variants: `primary` (one per view), `secondary` (bordered, surface background), `ghost` (text only), `danger`.

- Height: 40px (touch target minimum), padding 0 16px, `--radius-md`, weight 500.
- Loading state: replace label with spinner, keep the button width fixed to avoid layout shift, set `disabled`.
- Never use a link styled as a button for a destructive action.

## Form fields

Structure, top to bottom: label, input, helper text or error (same slot, error replaces helper).

- Label always visible; placeholders are examples, never labels.
- Validate on blur, re-validate on change once a field has an error.
- Error text is specific: "Enter a date after today", not "Invalid input".
- Group related fields with 24px gaps between groups, 12px within.

## Cards

- `--color-surface` background, `--color-border` 1px border, `--radius-md`, `--shadow-sm`.
- Padding 16px (dense) or 24px (default).
- A card is clickable OR contains actions, never both.

## Tables

- Header row: `--text-sm`, weight 500, `--color-text-muted`.
- Right-align numeric columns, left-align text.
- Row height minimum 44px. Zebra striping only for tables over 10 rows.
- Empty state inside the table body: one sentence plus the action that fills the table.
- Over ~50 rows: paginate or virtualize; never render unbounded lists.

## Modals

- Max width 480px (confirm) or 720px (forms). `--radius-lg`, `--shadow-md`.
- Focus trap inside; Escape closes; return focus to the trigger on close.
- Primary action bottom-right, cancel to its left. Destructive confirms use the `danger` button and name the object: "Delete report Q3-final?".

## Toasts / notifications

- One line, auto-dismiss success after 4s; errors persist until dismissed.
- Mirror the action's verb: "Publish" button, "Published" toast.
