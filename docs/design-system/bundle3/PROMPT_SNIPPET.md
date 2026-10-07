# AnyToolAI Bundle 3 Prompt Snippet

Load this guidance before every AnyToolAI Portal UI task, along with
[SKILL.md](SKILL.md), [web.md](web.md) and [tokens.json](tokens.json).

## Authority and identity

Bundle 3 is the single canonical implementation design system. The approved
ANY-539 RU Portal mockup supplied as the local visual reference during
implementation defines the product/visual target: deep navy, flat dark-blue
surfaces, thin blue borders,
amber actions, compact radii/spacing and Plus Jakarta Sans. The earlier mandatory
indigo glass/bento identity is superseded. The mockup is not authority for
providers, tariffs, subscriptions, paid access, usage, availability or legal facts.

## Core semantic tokens

```text
background: #07101f
surfaceCard / surfaceHover / surfaceActive: #0d1929 / #122035 / #1a2d45
border: #1e3250
accentDeep (primary fill): #f59e0b
accentForeground (content on primary fill): #07101f
accent (text/highlight): #fcd34d
accentSecondary / accentSecondaryText: #6366f1 / #818cf8, restrained secondary use
text / textSecondary / textDisabled: #f0f4ff / #8ba3c0 / #4a6480
success: #10b981
headline / body family: Plus Jakarta Sans; optional technical mono: DM Mono
input / button / card / panel / hero radius: 8px / 8px / 14px / 12px / 16px
public maxWidth / gridGap / dashboardRailWidth: 1080px / 14px / 220px
```

The values above summarize the canonical JSON; never turn this snippet or a
page stylesheet into a second token authority. Generated compatibility slots
with historical gradient/glow names do not require those visual effects.

## Rules

- Flat navy backgrounds and opaque panels are normal. Use thin borders and
  minimal shadow; optional navigation blur is restrained to about 12px.
- Primary actions use flat amber with dark `accentForeground` text. Headline
  emphasis can use amber text. Neither requires an indigo gradient/glow.
- Controls commonly use 8–12px corners; cards/panels use 12–16px. Pills and
  compact badges may use their own justified radii.
- Public pages use compact sticky navigation, centered heroes and flat product
  cards. The application uses a narrow supporting rail and a wide flat workspace.
- Both use the same palette, typography and component rules. Do not introduce
  a cabinet-only theme, page-local palette or copied mockup variables.
- Load target fonts through the repository-approved mechanism when integrating
  pages; do not add a remote CSS `@import` from the mockup.
- Preserve visible focus, semantics, keyboard/touch usability, WCAG AA contrast,
  reduced motion, state labels and responsive single-column collapse. Use
  `textSecondary` for readable small metadata; reserve `textDisabled` for
  disabled/decorative detail.
- Preserve routes, product composition/state, auth/session, legal and locale
  behavior. Do not promote mockup demo facts into customer-facing truth.
- Refresh generated token output with `npm run generate`, never by hand.

Step 10 defines this design-system authority; Step 11 applies it to actual pages.
