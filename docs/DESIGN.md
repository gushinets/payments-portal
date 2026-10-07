# Design System

Status: authoritative entry point
Last updated: 2026-10-07

AnyToolAI Portal UI follows AnyToolAI Bundle 3, the single canonical
implementation design system. The approved RU Portal mockup attached to ANY-539
is the product and visual target; Bundle 3 encodes its deep navy background,
opaque dark-blue surfaces, thin blue borders, amber primary actions, compact radii/spacing and
Plus Jakarta Sans typography. Public discovery, product details and the
account/auth cabinet share this language. Indigo is a restrained secondary
accent. Shadows are minimal; subtle navigation blur is optional.

ANY-636 Step 10 supersedes the older mandatory indigo gradients, radial glows,
glass/bento cards, large radii and blur-heavy surfaces. Flat backgrounds,
opaque panels and flat amber actions are normal Bundle 3 styling. This step
defines the design-system target; page restyling and font loading belong to
Step 11. No replacement theme or parallel token authority is introduced.

Before UI work, read:

1. [Bundle 3 overview](design-system/bundle3/README.md)
2. [Full rules](design-system/bundle3/SKILL.md)
3. [Web layout rules](design-system/bundle3/web.md)
4. [Machine-readable tokens](design-system/bundle3/tokens.json)

The machine-readable tokens are canonical for values consumed by the app.
The existing repository generator produces
[web token CSS](../apps/web/src/app/tokens.generated.css); never edit that output
by hand. Preserve visible keyboard focus, semantic controls, sufficient text
and control contrast, usable touch targets, responsive single-column layouts
and state meaning beyond color. UI changes must include desktop and mobile
screenshots plus accessibility results.

The mockup is visual/product evidence only. Its provider names, tariffs,
subscription/access states, usage/quota values, roadmap products and
legal/privacy claims are not business or runtime authority.

Ordinary Portal-owned copy follows the active route locale (`en`, `fr`, `it`,
`de`, `es`, `ru`, or `pt`) within the implemented `ru` contour. Locale does not
select a contour or data plane. Canonical RU legal content and acceptance text
remain source-owned and Russian. Billing, paid-access, and usage/quota panels
must present unavailable/unknown states without implying no subscription, no
access, or zero usage/quota. See the
[as-built RU Portal 4F handoff](product/ru-mvp.md).
