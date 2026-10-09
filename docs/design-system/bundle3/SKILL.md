---
name: anytoolai-bundle3-design
description: Canonical navy, amber and compact design system for AnyToolAI Portal UI work.
---

# AnyToolAI Bundle 3 Design System

Use this reference for every visual change in the AnyToolAI Portal. The approved
ANY-539 RU Portal mockup supplied as the local visual reference during
implementation defines the product/visual target; Bundle 3 is its single
canonical implementation encoding.
Use the mockup for hierarchy, density, palette, typography, surfaces and layout,
without copying its demo or business/runtime facts. The
machine-readable values in [tokens.json](tokens.json) are canonical when prose
and code disagree. Never create a second theme or token source.

## Visual identity

- Flat deep navy page background: `background` (`#07101f`).
- Opaque dark-blue surfaces: `surfaceCard` (`#0d1929`), `surfaceHover`
  (`#122035`) and `surfaceActive` (`#1a2d45`). Use thin `border` (`#1e3250`)
  outlines for grouping; stronger outlines serve controls that need contrast.
- Flat amber primary fill: `accentDeep` (`#f59e0b`), with dark
  `accentForeground` (`#07101f`) text. `accent` (`#fcd34d`) is the readable
  amber text/highlight color.
- `accentSecondary` (`#6366f1`) and `accentSecondaryText` (`#818cf8`) are
  optional restrained indigo accents for a justified secondary grouping.
- Primary text uses `text` (`#f0f4ff`), supporting text uses `textSecondary`
  (`#8ba3c0`), and disabled/decorative detail uses `textDisabled` (`#4a6480`).
- Success uses `success` (`#10b981`); error and warning use their semantic
  tokens with a label or icon. A color never establishes a product state.
- Compact typography and spacing, 8–12px controls and 12–16px cards/panels.
  Flat workspaces and minimal shadow are normal. Glass, gradients, bento
  grouping and ambient glows are no longer mandatory visual treatments.

Existing token names and generated CSS aliases are retained for consumers.
`accentGlow` is a restrained amber emphasis fill, not a required glow/shadow.
The legacy `teal`/`tealGlow` slots use the success palette, not a second brand
accent. The legacy `gradients.accent` and `gradients.headline` slots now contain
flat amber fills; their names do not require gradient actions or headings.
Newly styled surfaces use semantic color tokens directly.

## Typography

Manrope is the target `headline` and `body` family for both public
and application surfaces, with a sans-serif fallback. Use weights 400–800:

- Public display: 32px on mobile up to 56px on desktop, weight 800,
  approximately 1.08 line height and restrained negative letter spacing.
- Public section/product heading: 26–32px, weight 700–800.
- Application heading: 22–26px, weight 700.
- Card heading: 13–16px, weight 600–700.
- Body: 13–15px, weight 400–500, approximately 1.6 line height.
- Supporting labels and metadata: 11–13px, weight 500–700; compact uppercase
  section labels may use restrained tracking.

DM Mono remains the optional `mono` family for code/technical values. Ordinary
numbers, dates and badges use the body family; monospacing is not mandatory.
The ANY-636 Cyrillic coverage correction replaces the original Plus Jakarta
Sans family, which lacks basic Cyrillic U+0400–U+045F. Load Manrope through
`next/font/google` with Cyrillic and Latin subsets across all seven locales.
Declaring a token does not load a font. Do not add a remote CSS `@import` or
copy the mockup's Google Fonts import. Preserve readable fallbacks while loading.

## Surface levels

- Page/workspace: opaque `background`, with no required radial glow layers.
- Navigation: opaque `surfaceNav` by default; an optional near-opaque treatment
  with up to 12px backdrop blur may follow the mockup. Always retain a readable
  opaque fallback and a thin bottom border.
- Cards: opaque `surfaceCard`, thin border, 14px `card` radius, 18–24px padding.
- Compact application/support panels: opaque `surfaceCard` or `surfaceHover`,
  thin border, 12px `panel` radius, 18–20px padding.
- Large preview/dialog surfaces: opaque surface, 16px `hero` radius. Dialogs
  retain a clear boundary, focus management and readable content.
- Hover/selected surface levels use `surfaceHover`/`surfaceActive`; a selected
  item may use a restrained semantic emphasis fill with explicit text/icon
  meaning. Avoid heavy shadows or blurred cards as the default elevation cue.

Opaque surfaces do not require an exception. Decorative borders need not carry
control/state meaning; essential control boundaries must have sufficient
contrast, using `borderStrong` when appropriate.

## Components

- Primary button: flat `accentDeep` fill, dark `accentForeground` text,
  8px `button` radius. Larger hero actions may use 11–12px radii. No required
  gradient/glow.
- Secondary button: transparent or opaque dark surface, thin border and
  readable secondary or amber text. Maintain sufficient control contrast.
- Inputs: opaque dark surface, 8px `input` radius, readable labels/placeholders,
  visible amber focus ring. Never rely on a decorative border alone for meaning.
- Status badge: compact body type, semantic fill, readable label and optional
  icon; small badge radii or pills are allowed. Color does not imply a fact.
- Tool/product card: flat dark surface, 12–16px radius, thin blue border,
  restrained surface/border hover change. Whole-card navigation and embedded
  actions must remain semantic and keyboard usable.
- Dashboard rail: supporting navigation and compact account context beside a
  wide flat product workspace; use the shared palette and components.
- Legal text: readable line height, restrained width, semantic headings/tables.

## Accessibility and responsive behavior

- Use semantic elements and labels before test-only attributes.
- Preserve visible keyboard focus and logical focus order; use a visible
  outline with spacing from the focused control.
- Keep WCAG AA contrast: at least 4.5:1 for normal text, 3:1 for large text and
  essential control/state indicators. `textDisabled` is only for disabled or
  decorative content; use `textSecondary` for readable small labels/metadata
  instead of blindly copying the mockup's low-contrast tertiary text.
- Do not encode state by color alone.
- Keep controls keyboard usable and touch targets sufficiently large even when
  their visual treatment is compact; honor reduced-motion preferences.
- At 860px or earlier if content needs it, multi-column layouts collapse to one
  column and the dashboard rail becomes supporting content above the workspace.
- At 520px, actions become full width where necessary.
- Preserve navigation access, text zoom and wrapping on small screens; do not
  copy the mockup's inaccessible clickable divs or hidden mobile navigation.
- Validate desktop and mobile screenshots plus automated accessibility checks.

## Prohibited patterns

- Page-local palettes or a parallel theme/token authority
- Restoring mandatory purple/indigo glows, glass/bento cards or gradient actions
- Unapproved replacement font identities or new remote CSS font imports
- Excessive brand/status decoration, heavy shadows or blur on every surface
- Unverified provider, tariff, subscription, access, usage or legal facts
- Missing hover, focus, loading, disabled, or error states

Read [web.md](web.md) for layout details and
[PROMPT_SNIPPET.md](PROMPT_SNIPPET.md) for the short task preamble.
