---
name: anytoolai-bundle3-design
description: Canonical dark glass and bento design system for AnytoolAI Payment Portal UI work.
---

# AnytoolAI Bundle 3 Design System

Use this reference for every visual change in the Payment Portal. The
machine-readable values in [tokens.json](tokens.json) are canonical when prose
and code disagree.

## Visual identity

- Deep indigo layered backgrounds with ambient indigo and teal glows.
- Translucent glass surfaces with blur, subtle white borders, and depth.
- Indigo gradient primary actions; never use a flat primary accent.
- Teal only for live/active emphasis; green for success and red for errors.
- Bento grouping, compact spacing, generous card radii, and strong typographic
  hierarchy.

## Typography

| Role | Family | Weight | Typical size |
|---|---|---:|---:|
| Display | Cabinet Grotesk | 900 | 44–56px |
| Section | Cabinet Grotesk | 800 | 26–36px |
| Card heading | Cabinet Grotesk | 700 | 15–18px |
| Body | DM Sans | 400 | 13–15px |
| Label | DM Sans | 600 | 10–11px |
| Numbers/time | DM Mono | 400–500 | 10–24px |

## Surface levels

- Navigation: `surfaceNav`, 20px blur, bottom border.
- Cards and panels: `surfaceCard`, 16px blur, 16–20px radius.
- Modals: `surfaceModal`, 24px blur, prominent border, 20px radius.

Opaque surfaces are allowed only when browser compositing or modal readability
requires a documented exception.

## Components

- Primary button: gradient, white text, 8–12px radius, indigo glow.
- Secondary button: glass background, prominent translucent border.
- Inputs: glass background, 8px radius, visible indigo focus ring.
- Status badge: compact, uppercase/mono, semantic translucent background.
- Tool card: glass, 18px radius, subtle hover lift and indigo border.
- Legal text: readable line height, restrained width, semantic headings/tables.

## Accessibility and responsive behavior

- Use semantic elements and labels before test-only attributes.
- Preserve visible keyboard focus.
- Do not encode state by color alone.
- At 860px, multi-column layouts collapse to one column.
- At 520px, actions become full width where necessary.
- Validate desktop and mobile screenshots plus automated accessibility checks.

## Prohibited patterns

- Flat primary accent buttons
- Plain solid page background without glow layers
- Sharp elevated cards
- Unapproved Inter, Roboto, or system-font replacement
- Excessive teal decoration
- Missing hover, focus, loading, disabled, or error states

Read [web.md](web.md) for layout details and
[PROMPT_SNIPPET.md](PROMPT_SNIPPET.md) for the short task preamble.
