---
name: ui-design
description: Project UI standards for building or modifying any user interface in this repo. Use this skill whenever the task touches components, pages, layouts, styling, CSS, themes, forms, tables, dashboards, or visual polish, even if the user only says "make it look better", "add a button", or "fix the layout". Always consult it before writing frontend code so output matches the project's design tokens and component conventions.
---

# UI Design Skill

Purpose: make every UI change in this project look like it was built by the same person on the same day. Consistency beats novelty here. Before writing any frontend code, load the token reference and follow the rules below.

## Workflow

1. Read `references/design-tokens.md` and use only those colors, spacing steps, radii, and type scale values. Never hardcode a hex value or pixel size that is not in the tokens file.
2. Check whether a similar component already exists in the codebase. Extend or reuse before creating something new. A second slightly different button variant is a bug, not a feature.
3. Sketch the layout in one or two sentences (regions, hierarchy, primary action) before coding. The page has one primary action; everything else is visually subordinate.
4. Build, then self-review against the checklist at the bottom.

## Component conventions

- One component, one file, one responsibility. Name components by what the user sees, not by implementation (`UserCard`, not `DataWrapperV2`).
- Props/inputs describe intent (`variant="danger"`), not styling (`color="red"`).
- Every interactive element has all five states designed: default, hover, focus-visible, disabled, loading. If a state is missing, the component is not done.
- Empty states, error states, and loading states are part of the component, not an afterthought. An empty screen tells the user what to do next.
- Forms: label every field, validate on blur, show errors next to the field in plain language that says how to fix the problem. Buttons say what they do ("Save changes", not "Submit").

## Layout rules

- Use the spacing scale for all gaps, padding, and margins. If two adjacent elements use spacing values not on the scale, fix it.
- Align to a grid. Left-align text; never center long-form text.
- Maximum content width for reading surfaces: 720px. Data tables and dashboards may go full width.
- Mobile first: the layout must work at 380px before you add breakpoints upward.

## Accessibility floor (non-negotiable)

- Text contrast at least 4.5:1 against its background (3:1 for large text).
- Keyboard: everything clickable is reachable by Tab, with a visible focus ring (never `outline: none` without a replacement).
- Images and icons that carry meaning get alt text or aria-labels; decorative ones get `aria-hidden`.
- Respect `prefers-reduced-motion`: gate all non-essential animation behind it.

## Writing in the UI

Words are design material. Active voice, sentence case, plain verbs. An action keeps the same name through the whole flow: a "Publish" button produces a "Published" toast. Errors explain what went wrong and how to fix it; they never apologize and are never vague.

## Self-review checklist

Before presenting UI work, verify:

- [ ] Only token values used (colors, spacing, radius, type scale)
- [ ] No duplicate of an existing component
- [ ] All five interactive states present
- [ ] Empty, loading, and error states handled
- [ ] Works at 380px width
- [ ] Focus visible, contrast passes, reduced motion respected
- [ ] Copy follows the writing rules

If any box is unchecked, fix it before showing the result. If a rule genuinely conflicts with the task, say so explicitly and propose the deviation instead of silently breaking the standard.

## Bundled references

- `references/design-tokens.md` - the single source of truth for colors, type, spacing, radii, shadows. Read it at the start of every UI task.
- `references/component-patterns.md` - approved patterns for buttons, forms, cards, tables, and modals with examples. Read it when building or modifying one of those components.
